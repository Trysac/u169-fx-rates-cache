"""Tests for fx_rates_cache library."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from fx_rates_cache import Conversion, FxConverter, FxError, RateNotAvailable, RateSource


class DictRateSource:
    """Test rates source backed by a dictionary mapping date -> dict of rates."""

    def __init__(self, data: dict[datetime.date, dict[str, Decimal]]) -> None:
        self.data = data
        self.call_count = 0
        self.calls: list[tuple[datetime.date, str]] = []

    def fetch(self, day: datetime.date, base: str) -> dict[str, Decimal]:
        self.call_count += 1
        self.calls.append((day, base))
        if day in self.data:
            return self.data[day]
        raise RateNotAvailable(f"No rates for {day}")


def test_protocol_conformance() -> None:
    source = DictRateSource({})
    assert isinstance(source, RateSource)


def test_acceptance_1_base_to_target() -> None:
    # With a source returning {'USD': Decimal('1.0800'), 'GBP': Decimal('0.8500')} for
    # date(2026, 11, 6) and base 'EUR',
    # convert(Decimal('100'), 'EUR', 'USD', on=date(2026, 11, 6)) returns amount
    # Decimal('108.0000'), rate Decimal('1.0800')
    # and rate_date date(2026, 11, 6)
    source_data = {
        datetime.date(2026, 11, 6): {
            "USD": Decimal("1.0800"),
            "GBP": Decimal("0.8500"),
        }
    }
    source = DictRateSource(source_data)
    converter = FxConverter(source, base="EUR")
    res = converter.convert(Decimal("100"), "EUR", "USD", on=datetime.date(2026, 11, 6))

    assert isinstance(res, Conversion)
    assert res.amount == Decimal("108.0000")
    assert res.rate == Decimal("1.0800")
    assert res.rate_date == datetime.date(2026, 11, 6)
    assert res.from_ccy == "EUR"
    assert res.to_ccy == "USD"


def test_acceptance_2_cross_rate_and_places() -> None:
    # convert(Decimal('10'), 'USD', 'GBP', on=date(2026, 11, 6), places=2) returns
    # rate Decimal('0.8500') / Decimal('1.0800')
    # computed with precision 28 and amount Decimal('7.87') (ROUND_HALF_EVEN)
    source_data = {
        datetime.date(2026, 11, 6): {
            "USD": Decimal("1.0800"),
            "GBP": Decimal("0.8500"),
        }
    }
    source = DictRateSource(source_data)
    converter = FxConverter(source, base="EUR")
    res = converter.convert(Decimal("10"), "USD", "GBP", on=datetime.date(2026, 11, 6), places=2)

    expected_rate = Decimal("0.8500") / Decimal("1.0800")
    assert res.rate == expected_rate
    assert res.amount == Decimal("7.87")
    assert res.rate_date == datetime.date(2026, 11, 6)


def test_acceptance_3_lookback_weekend() -> None:
    # For Saturday date(2026, 11, 7), where the source raises RateNotAvailable,
    # the result has rate_date date(2026, 11, 6); with max_lookback_days=0 it
    # raises FxError with code 'rate_unavailable'
    source_data = {
        datetime.date(2026, 11, 6): {
            "USD": Decimal("1.0800"),
            "GBP": Decimal("0.8500"),
        }
    }
    source = DictRateSource(source_data)
    converter = FxConverter(source, base="EUR", max_lookback_days=7)
    res = converter.convert(Decimal("100"), "EUR", "USD", on=datetime.date(2026, 11, 7))
    assert res.rate_date == datetime.date(2026, 11, 6)

    source_no_lookback = DictRateSource(source_data)
    converter_no_lookback = FxConverter(source_no_lookback, base="EUR", max_lookback_days=0)
    with pytest.raises(FxError) as exc_info:
        converter_no_lookback.convert(Decimal("100"), "EUR", "USD", on=datetime.date(2026, 11, 7))
    assert exc_info.value.code == "rate_unavailable"


def test_acceptance_4_lru_caching() -> None:
    # Two conversions for the same date call the source once, and with max_entries=2
    # conversions on three different dates evict the oldest entry so a fourth conversion
    # on the first date calls the source again
    d1 = datetime.date(2026, 11, 1)
    d2 = datetime.date(2026, 11, 2)
    d3 = datetime.date(2026, 11, 3)
    source_data = {
        d1: {"USD": Decimal("1.1")},
        d2: {"USD": Decimal("1.2")},
        d3: {"USD": Decimal("1.3")},
    }
    source = DictRateSource(source_data)
    converter = FxConverter(source, base="EUR", max_entries=2)

    converter.convert(10, "EUR", "USD", on=d1)
    assert source.call_count == 1
    converter.convert(20, "EUR", "USD", on=d1)
    assert source.call_count == 1

    converter.convert(10, "EUR", "USD", on=d2)
    assert source.call_count == 2

    converter.convert(10, "EUR", "USD", on=d3)
    assert source.call_count == 3

    # d1 should have been evicted (max_entries=2, d2 and d3 are in cache)
    converter.convert(10, "EUR", "USD", on=d1)
    assert source.call_count == 4


def test_acceptance_5_ttl_expiration_for_current_day() -> None:
    # With a clock where today is date(2026, 11, 6), the entry for 2026-11-06 is fetched again
    # after ttl_s=3600 seconds have elapsed on the injected monotonic clock, while the entry
    # for 2026-11-05 is never refetched
    current_time = 1000.0

    def mock_monotonic() -> float:
        return current_time

    def mock_today() -> datetime.date:
        return datetime.date(2026, 11, 6)

    d_today = datetime.date(2026, 11, 6)
    d_past = datetime.date(2026, 11, 5)

    source_data = {
        d_today: {"USD": Decimal("1.0800")},
        d_past: {"USD": Decimal("1.0700")},
    }
    source = DictRateSource(source_data)
    converter = FxConverter(
        source,
        base="EUR",
        ttl_s=3600.0,
        today=mock_today,
        monotonic=mock_monotonic,
    )

    converter.convert(10, "EUR", "USD", on=d_past)
    assert source.call_count == 1
    converter.convert(10, "EUR", "USD", on=d_today)
    assert source.call_count == 2

    # Advance monotonic time by 4000 seconds (past 3600s TTL)
    current_time += 4000.0

    # Past date should NOT expire
    converter.convert(10, "EUR", "USD", on=d_past)
    assert source.call_count == 2

    # Today's date SHOULD expire and trigger refetch
    converter.convert(10, "EUR", "USD", on=d_today)
    assert source.call_count == 3


def test_acceptance_6_validations() -> None:
    # Currency 'usd' raises FxError with code 'invalid_currency',
    # the amount 1.5 (a float) raises 'invalid_amount',
    # 'EUR' to 'EUR' returns rate Decimal('1') without calling the source,
    # and a currency missing from the rates raises 'rate_unavailable'
    source_data = {
        datetime.date(2026, 11, 6): {"USD": Decimal("1.0800")},
    }
    source = DictRateSource(source_data)
    converter = FxConverter(source, base="EUR")

    with pytest.raises(FxError) as exc_usd:
        converter.convert(Decimal(10), "usd", "EUR", on=datetime.date(2026, 11, 6))
    assert exc_usd.value.code == "invalid_currency"

    with pytest.raises(FxError) as exc_float:
        converter.convert(1.5, "EUR", "USD", on=datetime.date(2026, 11, 6))  # type: ignore[arg-type]
    assert exc_float.value.code == "invalid_amount"

    same_res = converter.convert(Decimal(50), "EUR", "EUR", on=datetime.date(2026, 11, 6))
    assert same_res.rate == Decimal("1")
    assert same_res.amount == Decimal("50")
    assert source.call_count == 0

    with pytest.raises(FxError) as exc_missing:
        converter.convert(Decimal(10), "EUR", "JPY", on=datetime.date(2026, 11, 6))
    assert exc_missing.value.code == "rate_unavailable"


def test_acceptance_7_invalid_rates_and_exceptions() -> None:
    # A source rate of 1.08 (float), Decimal('0') or Decimal('NaN') raises code 'invalid_rate',
    # and a ConnectionError from the source propagates unchanged and is not cached
    d = datetime.date(2026, 11, 6)

    # Float rate
    conv_float_rate = FxConverter(DictRateSource({d: {"USD": 1.08}}), base="EUR")  # type: ignore[dict-item]
    with pytest.raises(FxError) as exc1:
        conv_float_rate.convert(10, "EUR", "USD", on=d)
    assert exc1.value.code == "invalid_rate"

    # Zero rate
    conv_zero_rate = FxConverter(DictRateSource({d: {"USD": Decimal("0")}}), base="EUR")
    with pytest.raises(FxError) as exc2:
        conv_zero_rate.convert(10, "EUR", "USD", on=d)
    assert exc2.value.code == "invalid_rate"

    # NaN rate
    conv_nan_rate = FxConverter(DictRateSource({d: {"USD": Decimal("NaN")}}), base="EUR")
    with pytest.raises(FxError) as exc3:
        conv_nan_rate.convert(10, "EUR", "USD", on=d)
    assert exc3.value.code == "invalid_rate"

    # Negative rate
    conv_neg_rate = FxConverter(DictRateSource({d: {"USD": Decimal("-1.5")}}), base="EUR")
    with pytest.raises(FxError) as exc_neg:
        conv_neg_rate.convert(10, "EUR", "USD", on=d)
    assert exc_neg.value.code == "invalid_rate"

    # ConnectionError propagation
    class FailingSource:
        def __init__(self) -> None:
            self.attempts = 0

        def fetch(self, day: datetime.date, base: str) -> dict[str, Decimal]:
            self.attempts += 1
            raise ConnectionError("remote connection failed")

    fail_source = FailingSource()
    conv_fail = FxConverter(fail_source, base="EUR")
    with pytest.raises(ConnectionError, match="remote connection failed"):
        conv_fail.convert(10, "EUR", "USD", on=d)

    assert fail_source.attempts == 1
    # Verify it was not cached: calling again invokes source again
    with pytest.raises(ConnectionError):
        conv_fail.convert(10, "EUR", "USD", on=d)
    assert fail_source.attempts == 2


def test_config_validations() -> None:
    source = DictRateSource({})
    # Invalid base currency
    with pytest.raises(FxError) as exc:
        FxConverter(source, base="euro")
    assert exc.value.code == "invalid_currency"

    # Invalid max_entries
    with pytest.raises(FxError) as exc:
        FxConverter(source, base="EUR", max_entries=0)
    assert exc.value.code == "invalid_config"

    # Invalid ttl_s
    with pytest.raises(FxError) as exc:
        FxConverter(source, base="EUR", ttl_s=-1.0)
    assert exc.value.code == "invalid_config"

    # Invalid lookback
    with pytest.raises(FxError) as exc:
        FxConverter(source, base="EUR", max_lookback_days=-1)
    assert exc.value.code == "invalid_config"
    with pytest.raises(FxError) as exc:
        FxConverter(source, base="EUR", max_lookback_days=32)
    assert exc.value.code == "invalid_config"

    converter = FxConverter(source, base="EUR")
    # Invalid places
    with pytest.raises(FxError) as exc:
        converter.convert(10, "EUR", "EUR", on=datetime.date(2026, 1, 1), places=-1)
    assert exc.value.code == "invalid_config"
    with pytest.raises(FxError) as exc:
        converter.convert(10, "EUR", "EUR", on=datetime.date(2026, 1, 1), places=9)
    assert exc.value.code == "invalid_config"
    with pytest.raises(FxError) as exc:
        converter.convert(10, "EUR", "EUR", on=datetime.date(2026, 1, 1), places=True)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_config"


def test_amount_type_validations() -> None:
    converter = FxConverter(DictRateSource({}), base="EUR")
    d = datetime.date(2026, 1, 1)
    with pytest.raises(FxError) as exc:
        converter.convert(True, "EUR", "EUR", on=d)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_amount"

    with pytest.raises(FxError) as exc:
        converter.convert(Decimal("Infinity"), "EUR", "EUR", on=d)
    assert exc.value.code == "invalid_amount"

    with pytest.raises(FxError) as exc:
        converter.convert("100", "EUR", "EUR", on=d)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_amount"


def test_rate_validations_in_fetch() -> None:
    d = datetime.date(2026, 1, 1)
    # Source returning invalid currency key
    conv = FxConverter(DictRateSource({d: {"us": Decimal("1.2")}}), base="EUR")
    with pytest.raises(FxError) as exc:
        conv.convert(10, "EUR", "USD", on=d)
    assert exc.value.code == "invalid_currency"

    # Source returning bool rate
    conv_bool = FxConverter(DictRateSource({d: {"USD": True}}), base="EUR")  # type: ignore[dict-item]
    with pytest.raises(FxError) as exc:
        conv_bool.convert(10, "EUR", "USD", on=d)
    assert exc.value.code == "invalid_rate"


def test_target_to_base_conversion() -> None:
    # Converting from target to base: 1 / rate
    d = datetime.date(2026, 1, 1)
    source = DictRateSource({d: {"USD": Decimal("2.0")}})
    converter = FxConverter(source, base="EUR")
    res = converter.convert(Decimal("50"), "USD", "EUR", on=d)
    assert res.rate == Decimal("0.5")
    assert res.amount == Decimal("25.0")

    # Missing source currency in rates when converting to base
    source_empty = DictRateSource({d: {}})
    converter_empty = FxConverter(source_empty, base="EUR")
    with pytest.raises(FxError) as exc:
        converter_empty.convert(Decimal("50"), "USD", "EUR", on=d)
    assert exc.value.code == "rate_unavailable"


def test_same_currency_with_places() -> None:
    converter = FxConverter(DictRateSource({}), base="EUR")
    d = datetime.date(2026, 1, 1)
    res = converter.convert(Decimal("10.12345"), "USD", "USD", on=d, places=2)
    assert res.amount == Decimal("10.12")
    assert res.rate == Decimal("1")


def test_probed_dates_all_cached() -> None:
    # When looking back over Saturday and Sunday to Friday, all probed dates are cached
    fri = datetime.date(2026, 11, 6)
    sat = datetime.date(2026, 11, 7)
    sun = datetime.date(2026, 11, 8)

    source = DictRateSource({fri: {"USD": Decimal("1.08")}})
    converter = FxConverter(source, base="EUR", max_lookback_days=3)

    # Sunday conversion probes sun, sat, fri (calls source 3 times)
    res_sun = converter.convert(10, "EUR", "USD", on=sun)
    assert res_sun.rate_date == fri
    assert source.call_count == 3

    # Saturday should now be cached without calling source
    res_sat = converter.convert(10, "EUR", "USD", on=sat)
    assert res_sat.rate_date == fri
    assert source.call_count == 3
