# Testing

## Running

`uv run pytest --cov=fx_rates_cache`

## Policy

- Branch coverage must remain >= 80%.
- Tests exercise the public API (`import fx_rates_cache`) and assert every observable effect: return values, raised exceptions, and error messages.
- Deterministic: no network, no wall clock, no dependence on test order.

## Layout

`tests/test_fx_rates_cache.py`: Covers acceptance criteria (source rates, lookback logic, cache LRU, validations, exception propagation). Shared fixtures reside in `tests/conftest.py`.