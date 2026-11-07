"""Unit tests for fx_rates_cache library."""

from __future__ import annotations

import datetime
import decimal
from collections.abc import Mapping
from decimal import Decimal

import pytest

from fx_rates_cache import Conversion, FxConverter, FxError, RateNotAvailable, RateSource


class DictRateSource:
    """Mock RateSource backed by a dictionary mapping (date, base) -> dict[str, Decimal]."""

    def __init__(
        self,
        rates_by_date: dict[tuple[datetime.date, str], Mapping[str, Decimal]] | None = None,
    ) -> None:
        self._rates = rates_by_date or {}
        self.calls: list[tuple[datetime.date, str]] = []

    def fetch(self, day: datetime.date, base: str) -> Mapping[str, Decimal]:
        self.calls.append((day, base))
        key = (day, base)
        if key not in self._rates:
            raise RateNotAvailable(f"No rates for {day} {base}")
        return self._rates[key]


def test_protocol_conformance() -> None:
    src = DictRateSource()
    assert isinstance(src, RateSource)


def test_acceptance_1_base_to_target() -> None:
    # With a source returning {'USD': Decimal('1.0800'), 'GBP': Decimal('0.8500')}
    # for date(2026, 11, 6) and base 'EUR', convert(Decimal('100'), 'EUR', 'USD',
    # on=date(2026, 11, 6)) returns amount Decimal('108.0000'), rate
    # Decimal('1.0800') and rate_date date(2026, 11, 6)
    d = datetime.date(2026, 11, 6)
    source = DictRateSource({(d, "EUR"): {"USD": Decimal("1.0800"), "GBP": Decimal("0.8500")}})
    converter = FxConverter(source, base="EUR")
    res = converter.convert(Decimal("100"), "EUR", "USD", on=d)

    assert res == Conversion(
        amount=Decimal("108.0000"),
        rate=Decimal("1.0800"),
        rate_date=d,
        from_ccy="EUR",
        to_ccy="USD",
    )


def test_acceptance_2_cross_rate_and_places() -> None:
    # convert(Decimal('10'), 'USD', 'GBP', on=date(2026, 11, 6), places=2) returns rate
    # Decimal('0.8500') / Decimal('1.0800') computed with precision 28 and amount Decimal('7.87')
    # (ROUND_HALF_EVEN)
    d = datetime.date(2026, 11, 6)
    source = DictRateSource({(d, "EUR"): {"USD": Decimal("1.0800"), "GBP": Decimal("0.8500")}})
    converter = FxConverter(source, base="EUR")
    res = converter.convert(Decimal("10"), "USD", "GBP", on=d, places=2)

    with decimal.localcontext() as ctx:
        ctx.prec = 28
        ctx.rounding = decimal.ROUND_HALF_EVEN
        expected_rate = Decimal("0.8500") / Decimal("1.0800")
        expected_amount = (Decimal("10") * expected_rate).quantize(Decimal("0.01"))

    assert res.rate == expected_rate
    assert res.amount == Decimal("7.87")
    assert res.amount == expected_amount
    assert res.rate_date == d


def test_acceptance_3_weekend_lookback() -> None:
    # For Saturday date(2026, 11, 7), where the source raises RateNotAvailable, the result has
    # rate_date date(2026, 11, 6); with max_lookback_days=0 it raises FxError with code
    # 'rate_unavailable'
    friday = datetime.date(2026, 11, 6)
    saturday = datetime.date(2026, 11, 7)
    source = DictRateSource({(friday, "EUR"): {"USD": Decimal("1.0800"), "GBP": Decimal("0.8500")}})
    converter = FxConverter(source, base="EUR", max_lookback_days=7)
    res = converter.convert(Decimal("100"), "EUR", "USD", on=saturday)
    assert res.rate_date == friday
    assert res.amount == Decimal("108.0000")

    converter_no_lookback = FxConverter(source, base="EUR", max_lookback_days=0)
    with pytest.raises(FxError) as exc_info:
        converter_no_lookback.convert(Decimal("100"), "EUR", "USD", on=saturday)
    assert exc_info.value.code == "rate_unavailable"


def test_acceptance_4_lru_caching_and_eviction() -> None:
    # Two conversions for the same date call the source once, and with max_entries=2 conversions
    # on three different dates evict the oldest entry so a fourth conversion on the first date
    # calls the source again
    d1 = datetime.date(2026, 11, 1)
    d2 = datetime.date(2026, 11, 2)
    d3 = datetime.date(2026, 11, 3)

    source = DictRateSource(
        {
            (d1, "EUR"): {"USD": Decimal("1.05")},
            (d2, "EUR"): {"USD": Decimal("1.06")},
            (d3, "EUR"): {"USD": Decimal("1.07")},
        }
    )
    # Fixed today in the future so entries are considered historical
    today = lambda: datetime.date(2026, 12, 1)  # noqa: E731
    converter = FxConverter(source, base="EUR", max_entries=2, today=today)

    converter.convert(10, "EUR", "USD", on=d1)
    converter.convert(20, "EUR", "USD", on=d1)
    assert source.calls == [(d1, "EUR")]

    converter.convert(10, "EUR", "USD", on=d2)
    assert source.calls == [(d1, "EUR"), (d2, "EUR")]

    converter.convert(10, "EUR", "USD", on=d3)
    assert source.calls == [(d1, "EUR"), (d2, "EUR"), (d3, "EUR")]

    # d1 was evicted because max_entries=2 (cache now holds d2 and d3)
    converter.convert(10, "EUR", "USD", on=d1)
    assert source.calls == [(d1, "EUR"), (d2, "EUR"), (d3, "EUR"), (d1, "EUR")]


def test_acceptance_5_ttl_expiration_for_current_day() -> None:
    # With a clock where today is date(2026, 11, 6), the entry for 2026-11-06 is fetched again
    # after ttl_s=3600 seconds have elapsed on the injected monotonic clock, while the entry
    # for 2026-11-05 is never refetched
    d_today = datetime.date(2026, 11, 6)
    d_yesterday = datetime.date(2026, 11, 5)

    source = DictRateSource(
        {
            (d_today, "EUR"): {"USD": Decimal("1.08")},
            (d_yesterday, "EUR"): {"USD": Decimal("1.07")},
        }
    )

    now_time = 1000.0

    def mock_monotonic() -> float:
        return now_time

    def mock_today() -> datetime.date:
        return d_today

    converter = FxConverter(
        source,
        base="EUR",
        ttl_s=3600.0,
        today=mock_today,
        monotonic=mock_monotonic,
    )

    # Initial fetches
    converter.convert(1, "EUR", "USD", on=d_today)
    converter.convert(1, "EUR", "USD", on=d_yesterday)
    assert source.calls == [(d_today, "EUR"), (d_yesterday, "EUR")]

    # Advance monotonic clock by 3601 seconds
    now_time += 3601.0

    # d_yesterday should still be cached
    converter.convert(1, "EUR", "USD", on=d_yesterday)
    assert source.calls == [(d_today, "EUR"), (d_yesterday, "EUR")]

    # d_today should expire and refetch
    converter.convert(1, "EUR", "USD", on=d_today)
    assert source.calls == [(d_today, "EUR"), (d_yesterday, "EUR"), (d_today, "EUR")]


def test_acceptance_6_validation_and_same_currency() -> None:
    # Currency 'usd' raises FxError with code 'invalid_currency', the amount 1.5 (a float)
    # raises 'invalid_amount', 'EUR' to 'EUR' returns rate Decimal('1') without calling the
    # source, and a currency missing from the rates raises 'rate_unavailable'
    d = datetime.date(2026, 11, 6)
    source = DictRateSource({(d, "EUR"): {"USD": Decimal("1.0800")}})
    converter = FxConverter(source, base="EUR")

    # 'usd' lowercase invalid currency
    with pytest.raises(FxError) as exc1:
        converter.convert(Decimal("10"), "usd", "EUR", on=d)
    assert exc1.value.code == "invalid_currency"

    with pytest.raises(FxError) as exc1b:
        converter.convert(Decimal("10"), "EUR", "usd", on=d)
    assert exc1b.value.code == "invalid_currency"

    # float amount raises invalid_amount
    with pytest.raises(FxError) as exc2:
        converter.convert(1.5, "EUR", "USD", on=d)  # type: ignore[arg-type]
    assert exc2.value.code == "invalid_amount"

    # bool amount raises invalid_amount
    with pytest.raises(FxError) as exc2b:
        converter.convert(True, "EUR", "USD", on=d)  # type: ignore[arg-type]
    assert exc2b.value.code == "invalid_amount"

    # 'EUR' to 'EUR' returns Decimal('1') without calling source
    res = converter.convert(Decimal("42"), "EUR", "EUR", on=d)
    assert res.rate == Decimal("1")
    assert res.amount == Decimal("42")
    assert res.rate_date == d
    assert len(source.calls) == 0

    # 'EUR' to 'EUR' with places
    res_places = converter.convert(Decimal("42"), "EUR", "EUR", on=d, places=2)
    assert res_places.amount == Decimal("42.00")

    # missing target currency
    with pytest.raises(FxError) as exc3:
        converter.convert(Decimal("10"), "EUR", "JPY", on=d)
    assert exc3.value.code == "rate_unavailable"

    # missing source currency
    with pytest.raises(FxError) as exc4:
        converter.convert(Decimal("10"), "JPY", "EUR", on=d)
    assert exc4.value.code == "rate_unavailable"

    # missing currency in cross rate
    with pytest.raises(FxError) as exc5:
        converter.convert(Decimal("10"), "JPY", "USD", on=d)
    assert exc5.value.code == "rate_unavailable"


def test_acceptance_7_invalid_rate_and_exception_propagation() -> None:
    # A source rate of 1.08 (float), Decimal('0') or Decimal('NaN') raises code 'invalid_rate',
    # and a ConnectionError from the source propagates unchanged and is not cached
    d = datetime.date(2026, 11, 6)

    for bad_rate in [1.08, Decimal("0"), Decimal("NaN"), Decimal("-1.5"), Decimal("Infinity")]:
        source = DictRateSource(
            {
                (d, "EUR"): {"USD": bad_rate}  # type: ignore[dict-item]
            }
        )
        converter = FxConverter(source, base="EUR")
        with pytest.raises(FxError) as exc:
            converter.convert(Decimal("10"), "EUR", "USD", on=d)
        assert exc.value.code == "invalid_rate"

    class FailingSource:
        def fetch(self, day: datetime.date, base: str) -> Mapping[str, Decimal]:
            raise ConnectionError("Network unreachable")

    fail_converter = FxConverter(FailingSource(), base="EUR")
    with pytest.raises(ConnectionError, match="Network unreachable"):
        fail_converter.convert(Decimal("10"), "EUR", "USD", on=d)

    # Check that nothing was cached
    assert len(fail_converter._cache) == 0


def test_target_to_base_conversion() -> None:
    d = datetime.date(2026, 11, 6)
    source = DictRateSource({(d, "EUR"): {"USD": Decimal("1.25")}})
    converter = FxConverter(source, base="EUR")
    res = converter.convert(Decimal("250"), "USD", "EUR", on=d)
    # 250 * (1 / 1.25) = 200
    assert res.rate == Decimal("1") / Decimal("1.25")
    assert res.amount == Decimal("200")
    assert res.rate_date == d


def test_int_amount_conversion() -> None:
    d = datetime.date(2026, 11, 6)
    source = DictRateSource({(d, "EUR"): {"USD": Decimal("1.50")}})
    converter = FxConverter(source, base="EUR")
    res = converter.convert(100, "EUR", "USD", on=d)
    assert res.amount == Decimal("150.00")


def test_config_validations() -> None:
    src = DictRateSource()
    with pytest.raises(FxError) as exc1:
        FxConverter(src, base="eur")
    assert exc1.value.code == "invalid_currency"

    with pytest.raises(FxError) as exc2:
        FxConverter(src, base="EUROPE")
    assert exc2.value.code == "invalid_currency"

    with pytest.raises(FxError) as exc3:
        FxConverter(src, base="EUR", max_entries=0)
    assert exc3.value.code == "invalid_config"

    with pytest.raises(FxError) as exc3b:
        FxConverter(src, base="EUR", max_entries=-5)
    assert exc3b.value.code == "invalid_config"

    with pytest.raises(FxError) as exc4:
        FxConverter(src, base="EUR", ttl_s=-1.0)
    assert exc4.value.code == "invalid_config"

    with pytest.raises(FxError) as exc5:
        FxConverter(src, base="EUR", max_lookback_days=32)
    assert exc5.value.code == "invalid_config"

    with pytest.raises(FxError) as exc6:
        FxConverter(src, base="EUR", max_lookback_days=-1)
    assert exc6.value.code == "invalid_config"

    converter = FxConverter(src, base="EUR")
    assert converter.base == "EUR"
    d = datetime.date(2026, 11, 6)
    with pytest.raises(FxError) as exc7:
        converter.convert(Decimal("10"), "EUR", "USD", on=d, places=-1)
    assert exc7.value.code == "invalid_config"

    with pytest.raises(FxError) as exc8:
        converter.convert(Decimal("10"), "EUR", "USD", on=d, places=9)
    assert exc8.value.code == "invalid_config"


def test_invalid_rates_mapping() -> None:
    d = datetime.date(2026, 11, 6)

    class NonMappingSource:
        def fetch(self, day: datetime.date, base: str) -> Mapping[str, Decimal]:
            return [("USD", Decimal("1.0"))]  # type: ignore[return-value]

    converter = FxConverter(NonMappingSource(), base="EUR")
    with pytest.raises(FxError) as exc:
        converter.convert(Decimal("10"), "EUR", "USD", on=d)
    assert exc.value.code == "invalid_rate"

    class BadCcyKeySource:
        def fetch(self, day: datetime.date, base: str) -> Mapping[str, Decimal]:
            return {"invalid": Decimal("1.0")}

    converter2 = FxConverter(BadCcyKeySource(), base="EUR")
    with pytest.raises(FxError) as exc2:
        converter2.convert(Decimal("10"), "EUR", "USD", on=d)
    assert exc2.value.code == "invalid_currency"


def test_lookback_probed_keys_cached() -> None:
    # Probing Sunday 2026-11-08 falls back to Friday 2026-11-06.
    # Both Sunday and Saturday should be cached with Friday's rate.
    d_fri = datetime.date(2026, 11, 6)
    d_sat = datetime.date(2026, 11, 7)
    d_sun = datetime.date(2026, 11, 8)

    source = DictRateSource({(d_fri, "EUR"): {"USD": Decimal("1.10")}})
    converter = FxConverter(source, base="EUR", max_lookback_days=3)
    res = converter.convert(100, "EUR", "USD", on=d_sun)
    assert res.rate_date == d_fri
    assert source.calls == [(d_sun, "EUR"), (d_sat, "EUR"), (d_fri, "EUR")]

    # Requesting Saturday or Sunday now should hit cache without calling source
    converter.convert(50, "EUR", "USD", on=d_sat)
    converter.convert(50, "EUR", "USD", on=d_sun)
    assert len(source.calls) == 3
