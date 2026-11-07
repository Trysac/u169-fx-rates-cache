"""Convert amounts between currencies with Decimal using dated rates from a pluggable source."""

from __future__ import annotations

import datetime
import decimal
import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "Conversion",
    "FxConverter",
    "FxError",
    "RateNotAvailable",
    "RateSource",
    "__version__",
]

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")

ErrorCode = Literal[
    "invalid_currency",
    "invalid_amount",
    "invalid_rate",
    "rate_unavailable",
    "invalid_config",
]


class FxError(Exception):
    """Base exception raised for foreign exchange errors."""

    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code: ErrorCode = code


class RateNotAvailable(Exception):
    """Raised by RateSource when no publication exists for a requested date."""


@runtime_checkable
class RateSource(Protocol):
    """Pluggable protocol for fetching exchange rates relative to a base currency."""

    def fetch(self, day: datetime.date, base: str) -> Mapping[str, Decimal]:
        """Fetch rates for given day and base currency.

        Raises:
            RateNotAvailable: When that day has no publication.
        """
        ...


@dataclass(frozen=True)
class Conversion:
    """Immutable result of a currency conversion."""

    amount: Decimal
    rate: Decimal
    rate_date: datetime.date
    from_ccy: str
    to_ccy: str


@dataclass(frozen=True)
class _CacheEntry:
    rates: dict[str, Decimal]
    rate_date: datetime.date
    fetched_at: float


class FxConverter:
    """Currency converter using Decimal arithmetic and bounded LRU caching."""

    def __init__(
        self,
        source: RateSource,
        *,
        base: str,
        max_entries: int = 1_000,
        ttl_s: float = 3600.0,
        max_lookback_days: int = 7,
        today: Callable[[], datetime.date] = datetime.date.today,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        import time

        if not isinstance(base, str) or not _CURRENCY_CODE_RE.match(base):
            raise FxError("invalid_currency", f"Invalid base currency code: {base!r}")
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
            raise FxError("invalid_config", "max_entries must be an integer >= 1")
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or ttl_s < 0:
            raise FxError("invalid_config", "ttl_s must be a non-negative number")
        if (
            isinstance(max_lookback_days, bool)
            or not isinstance(max_lookback_days, int)
            or not (0 <= max_lookback_days <= 31)
        ):
            raise FxError(
                "invalid_config",
                "max_lookback_days must be an integer between 0 and 31",
            )

        self._source = source
        self._base = base
        self._max_entries = max_entries
        self._ttl_s = float(ttl_s)
        self._max_lookback_days = max_lookback_days
        self._today = today
        self._monotonic = monotonic or time.monotonic

        self._cache: OrderedDict[tuple[datetime.date, str], _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def base(self) -> str:
        """Default base currency used for fetching rates."""
        return self._base

    def _validate_currency(self, ccy: str) -> None:
        if not isinstance(ccy, str) or not _CURRENCY_CODE_RE.match(ccy):
            preview = str(ccy)[:200]
            raise FxError("invalid_currency", f"Invalid currency code: {preview!r}")

    def _validate_amount(self, amount: Decimal | int) -> Decimal:
        if isinstance(amount, bool) or not isinstance(amount, (Decimal, int)):
            preview = str(amount)[:200]
            raise FxError("invalid_amount", f"Amount must be Decimal or int, got {preview!r}")
        dec_val = Decimal(amount)
        if not dec_val.is_finite():
            raise FxError("invalid_amount", "Amount must be finite")
        return dec_val

    def _validate_rates(self, raw_rates: Mapping[str, Decimal]) -> dict[str, Decimal]:
        if not isinstance(raw_rates, Mapping):
            raise FxError("invalid_rate", "Source returned non-mapping rates")

        cleaned: dict[str, Decimal] = {}
        for ccy, rate in raw_rates.items():
            if not isinstance(ccy, str) or not _CURRENCY_CODE_RE.match(ccy):
                raise FxError("invalid_currency", f"Invalid currency in rates: {ccy!r}")
            if isinstance(rate, bool) or not isinstance(rate, Decimal):
                raise FxError("invalid_rate", f"Rate for {ccy} must be Decimal")
            if not rate.is_finite() or rate <= Decimal("0"):
                raise FxError("invalid_rate", f"Rate for {ccy} must be finite and > 0")
            cleaned[ccy] = rate
        return cleaned

    def _get_rates_with_cache(self, on: datetime.date) -> tuple[dict[str, Decimal], datetime.date]:
        cache_key = (on, self._base)
        now_mono = self._monotonic()
        current_today = self._today()

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None:
                is_today_or_future = on >= current_today
                is_expired = is_today_or_future and (now_mono - entry.fetched_at >= self._ttl_s)
                if not is_expired:
                    self._cache.move_to_end(cache_key)
                    return entry.rates, entry.rate_date

        # Cache miss or expired: fetch without holding lock across source call
        probed_dates: list[datetime.date] = []
        published_rates: dict[str, Decimal] | None = None
        published_date: datetime.date | None = None

        for offset in range(self._max_lookback_days + 1):
            day_to_try = on - datetime.timedelta(days=offset)
            probed_dates.append(day_to_try)
            try:
                raw = self._source.fetch(day_to_try, self._base)
            except RateNotAvailable:
                continue
            except Exception:
                raise

            published_rates = self._validate_rates(raw)
            published_date = day_to_try
            break

        if published_rates is None or published_date is None:
            raise FxError(
                "rate_unavailable",
                f"No exchange rates available for {on} (lookback={self._max_lookback_days})",
            )

        fetched_at = self._monotonic()
        cached_entry = _CacheEntry(
            rates=published_rates,
            rate_date=published_date,
            fetched_at=fetched_at,
        )

        with self._lock:
            for probed_day in probed_dates:
                k = (probed_day, self._base)
                self._cache[k] = cached_entry
                self._cache.move_to_end(k)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)

        return published_rates, published_date

    def convert(
        self,
        amount: Decimal | int,
        from_ccy: str,
        to_ccy: str,
        *,
        on: datetime.date,
        places: int | None = None,
    ) -> Conversion:
        """Convert an amount from one currency to another on a given date."""
        self._validate_currency(from_ccy)
        self._validate_currency(to_ccy)
        dec_amount = self._validate_amount(amount)

        if places is not None and (
            isinstance(places, bool) or not isinstance(places, int) or not (0 <= places <= 8)
        ):
            raise FxError("invalid_config", "places must be an integer between 0 and 8")

        if from_ccy == to_ccy:
            rate = Decimal("1")
            with localcontext() as ctx:
                ctx.prec = 28
                ctx.rounding = decimal.ROUND_HALF_EVEN
                calc_amount = dec_amount * rate
                if places is not None:
                    calc_amount = calc_amount.quantize(Decimal(1).scaleb(-places))
            return Conversion(
                amount=calc_amount,
                rate=rate,
                rate_date=on,
                from_ccy=from_ccy,
                to_ccy=to_ccy,
            )

        rates, effective_date = self._get_rates_with_cache(on)

        with localcontext() as ctx:
            ctx.prec = 28
            ctx.rounding = decimal.ROUND_HALF_EVEN

            if from_ccy == self._base:
                if to_ccy not in rates:
                    raise FxError(
                        "rate_unavailable", f"Target currency {to_ccy} missing from rates"
                    )
                rate = rates[to_ccy]
            elif to_ccy == self._base:
                if from_ccy not in rates:
                    raise FxError(
                        "rate_unavailable", f"Source currency {from_ccy} missing from rates"
                    )
                rate = Decimal("1") / rates[from_ccy]
            else:
                if from_ccy not in rates:
                    raise FxError(
                        "rate_unavailable", f"Source currency {from_ccy} missing from rates"
                    )
                if to_ccy not in rates:
                    raise FxError(
                        "rate_unavailable", f"Target currency {to_ccy} missing from rates"
                    )
                rate = rates[to_ccy] / rates[from_ccy]

            calc_amount = dec_amount * rate
            if places is not None:
                calc_amount = calc_amount.quantize(Decimal(1).scaleb(-places))

        return Conversion(
            amount=calc_amount,
            rate=rate,
            rate_date=effective_date,
            from_ccy=from_ccy,
            to_ccy=to_ccy,
        )
