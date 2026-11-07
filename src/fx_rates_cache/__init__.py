"""Pluggable FX conversion with Decimal precision, bounded LRU caching, and lookback."""

from __future__ import annotations

import datetime
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
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

CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")

FxErrorCode = Literal[
    "invalid_currency",
    "invalid_amount",
    "invalid_rate",
    "rate_unavailable",
    "invalid_config",
]


class FxError(Exception):
    """Base error class for FX conversion operations."""

    def __init__(self, code: FxErrorCode, message: str | None = None) -> None:
        self.code = code
        msg = message or f"FX operation failed with code: {code}"
        # Limit error message length to avoid leaking huge payloads
        super().__init__(msg[:200])


class RateNotAvailable(Exception):
    """Raised by a RateSource when no publication exists for the requested day."""


@runtime_checkable
class RateSource(Protocol):
    """Protocol for rates providers."""

    def fetch(self, day: datetime.date, base: str) -> Mapping[str, Decimal]:
        """Fetch rates for given day expressed as units of currency per 1 base currency."""
        ...


@dataclass(frozen=True)
class Conversion:
    """Result of an FX conversion."""

    amount: Decimal
    rate: Decimal
    rate_date: datetime.date
    from_ccy: str
    to_ccy: str


class FxConverter:
    """Converts currency amounts using dated rates from a pluggable RateSource."""

    def __init__(
        self,
        source: RateSource,
        *,
        base: str,
        max_entries: int = 1_000,
        ttl_s: float = 3600.0,
        max_lookback_days: int = 7,
        today: Callable[[], datetime.date] = datetime.date.today,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validate_currency_code(base)
        if max_entries < 1:
            raise FxError("invalid_config", "max_entries must be at least 1")
        if ttl_s < 0:
            raise FxError("invalid_config", "ttl_s must be non-negative")
        if not (0 <= max_lookback_days <= 31):
            raise FxError("invalid_config", "max_lookback_days must be between 0 and 31")

        self._source = source
        self._base = base
        self._max_entries = max_entries
        self._ttl_s = ttl_s
        self._max_lookback_days = max_lookback_days
        self._today = today
        self._monotonic = monotonic

        # Cache maps (day: date, base: str) -> (rates: dict[str, Decimal],
        # rate_date: date, fetched_at: float)
        self._cache: OrderedDict[
            tuple[datetime.date, str], tuple[dict[str, Decimal], datetime.date, float]
        ] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _validate_currency_code(code: str) -> None:
        if not isinstance(code, str) or not CURRENCY_CODE_RE.match(code):
            raise FxError("invalid_currency", f"Invalid currency code: {code!r}")

    @staticmethod
    def _validate_amount(amount: Decimal | int) -> Decimal:
        # Ensure bool is rejected since bool is a subclass of int in Python
        if isinstance(amount, (bool, float)):
            raise FxError(
                "invalid_amount", f"Amount must be Decimal or int, got {type(amount).__name__}"
            )
        if isinstance(amount, int):
            return Decimal(amount)
        if isinstance(amount, Decimal):
            if not amount.is_finite():
                raise FxError("invalid_amount", "Amount must be a finite Decimal")
            return amount
        raise FxError(
            "invalid_amount", f"Amount must be Decimal or int, got {type(amount).__name__}"
        )

    def _validate_rates(self, rates: Mapping[str, Decimal]) -> dict[str, Decimal]:
        validated: dict[str, Decimal] = {}
        for ccy, rate in rates.items():
            self._validate_currency_code(ccy)
            if isinstance(rate, bool) or not isinstance(rate, Decimal):
                raise FxError(
                    "invalid_rate", f"Rate for {ccy} must be Decimal, got {type(rate).__name__}"
                )
            if not rate.is_finite() or rate <= 0:
                raise FxError("invalid_rate", f"Rate for {ccy} must be finite and positive: {rate}")
            validated[ccy] = rate
        return validated

    def _get_rates_and_date(self, on: datetime.date) -> tuple[dict[str, Decimal], datetime.date]:
        cache_key = (on, self._base)
        now = self._monotonic()
        current_day = self._today()

        with self._lock:
            if cache_key in self._cache:
                entry_rates, rate_date, fetched_at = self._cache[cache_key]
                # Expire if day is today or in future and ttl_s elapsed
                if on >= current_day and (now - fetched_at) >= self._ttl_s:
                    # Expired, remove from cache
                    del self._cache[cache_key]
                else:
                    self._cache.move_to_end(cache_key)
                    return entry_rates, rate_date

        # Cache miss or expired: fetch without holding lock (allows concurrent
        # source calls as documented)
        probed_dates: list[datetime.date] = []
        published_rates: dict[str, Decimal] | None = None
        effective_date: datetime.date | None = None

        for day_offset in range(self._max_lookback_days + 1):
            probe_day = on - datetime.timedelta(days=day_offset)
            probed_dates.append(probe_day)
            try:
                raw_rates = self._source.fetch(probe_day, self._base)
                published_rates = self._validate_rates(raw_rates)
                effective_date = probe_day
                break
            except RateNotAvailable:
                continue

        if published_rates is None or effective_date is None:
            raise FxError("rate_unavailable", f"No rates published for {on} within lookback window")

        fetched_at = self._monotonic()
        with self._lock:
            for probed in probed_dates:
                k = (probed, self._base)
                self._cache[k] = (published_rates, effective_date, fetched_at)
                self._cache.move_to_end(k)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

        return published_rates, effective_date

    def convert(
        self,
        amount: Decimal | int,
        from_ccy: str,
        to_ccy: str,
        *,
        on: datetime.date,
        places: int | None = None,
    ) -> Conversion:
        """Convert amount from from_ccy to to_ccy on the specified date."""
        if places is not None and not (
            isinstance(places, int) and not isinstance(places, bool) and 0 <= places <= 8
        ):
            raise FxError("invalid_config", "places must be an integer between 0 and 8")

        self._validate_currency_code(from_ccy)
        self._validate_currency_code(to_ccy)
        dec_amount = self._validate_amount(amount)

        if from_ccy == to_ccy:
            rate = Decimal("1")
            rate_date = on
            converted_amount = dec_amount * rate
            if places is not None:
                with localcontext() as ctx:
                    ctx.prec = 28
                    ctx.rounding = ROUND_HALF_EVEN
                    scale = Decimal(1).scaleb(-places)
                    converted_amount = converted_amount.quantize(scale)
            return Conversion(
                amount=converted_amount,
                rate=rate,
                rate_date=rate_date,
                from_ccy=from_ccy,
                to_ccy=to_ccy,
            )

        rates, rate_date = self._get_rates_and_date(on)

        with localcontext() as ctx:
            ctx.prec = 28
            ctx.rounding = ROUND_HALF_EVEN

            # Resolve rate
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
                rate = Decimal(1) / rates[from_ccy]
            else:
                if from_ccy not in rates or to_ccy not in rates:
                    missing = from_ccy if from_ccy not in rates else to_ccy
                    raise FxError("rate_unavailable", f"Currency {missing} missing from rates")
                rate = rates[to_ccy] / rates[from_ccy]

            converted_amount = dec_amount * rate
            if places is not None:
                try:
                    scale = Decimal(1).scaleb(-places)
                    converted_amount = converted_amount.quantize(scale)
                except InvalidOperation as exc:
                    raise FxError("invalid_amount", "Quantization failed") from exc

        return Conversion(
            amount=converted_amount,
            rate=rate,
            rate_date=rate_date,
            from_ccy=from_ccy,
            to_ccy=to_ccy,
        )
