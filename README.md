# fx-rates-cache

![Build Status](https://github.com/u169-fx-rates-cache/actions/workflows/ci.yml/badge.svg)

Applications that convert money often call rates APIs repeatedly, rely on floating-point arithmetic, and ignore that rates are published per business day. This library converts amounts with 28-digit Decimal precision, uses a pluggable source for rates, caches results by date, transparently resolves non-publishing days (weekends/holidays) via a configurable lookback, and reports the effective rate date.

## Installation

`pip install fx-rates-cache`

## Usage

```python
from decimal import Decimal
import datetime
from fx_rates_cache import FxConverter


class Source:
    def fetch(self, day: datetime.date, base: str) -> dict[str, Decimal]:
        return {"USD": Decimal("1.0800")}


conv = FxConverter(Source(), base="EUR")
res = conv.convert(Decimal("100"), "EUR", "USD", on=datetime.date(2026, 11, 6))
print(res.amount)
```

## API Summary

### Errors
- `FxError`: Raised for `invalid_currency`, `invalid_amount`, `invalid_rate`, `rate_unavailable`, `invalid_config`.

### Options & Limits
- `max_entries`: Bounded LRU cache size (default 1,000, must be >= 1).
- `max_lookback_days`: Lookback range (0-31 days).
- `ttl_s`: Expiration in seconds for current-day entries (default 3600.0).
- `places`: Optional quantization (0-8 digits) using `ROUND_HALF_EVEN`.

## Why not forex-python?

This library is offline-testable, uses `Decimal` only (no floats), explicitly reports the effective rate date used for conversion, and includes a bounded cache to prevent memory growth.

## Security

See [docs/SECURITY.md](docs/SECURITY.md).