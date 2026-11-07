# Architecture

## Overview

`fx-rates-cache` converts money using precise `Decimal` calculations. It is decoupled from third-party network providers.

### Components

1. **`RateSource` Protocol**:
   - Requires `fetch(day: datetime.date, base: str) -> Mapping[str, Decimal]`.
   - Raises `RateNotAvailable` if the date has no publication.

2. **`FxConverter`**:
   - Validates currency codes against `^[A-Z]{3}$`.
   - Arithmetic runs under `localcontext()` (prec=28, `ROUND_HALF_EVEN`).
   - Cross rates are computed as: `rates[target] / rates[source]` (or inverse if base is involved).
   - Lookback: Probes `on` day backwards up to `max_lookback_days`.
   - Caching: `OrderedDict` (LRU) with `threading.Lock`. Current-day entries expire after `ttl_s` seconds via injected `monotonic` and `today` clocks.