# Architecture

`fx-rates-cache` handles currency conversion and rate caching without floating point drift or unrecorded rate dates.

## Key Design Aspects

1. **RateSource Protocol**:
   - Decoupled from any network or HTTP library.
   - Contract: `fetch(day: date, base: str) -> Mapping[str, Decimal]`.
   - Raises `RateNotAvailable` when no rates were published on that date.

2. **Triangulation via Base Currency**:
   - Converting from Base to Target: `rate = rates[target]`
   - Converting from Source to Base: `rate = 1 / rates[source]`
   - Converting between Non-Base Currencies: `rate = rates[target] / rates[source]`
   - Identity: `from_ccy == to_ccy` returns rate `1` without querying the source.

3. **Local Decimal Context**:
   - All computations run within a thread-local decimal context: `prec=28` and `ROUND_HALF_EVEN`.
   - Quantization is applied only if `places` is explicitly requested (0 to 8).

4. **Bounded Thread-Safe LRU Cache**:
   - `_cache` is an `OrderedDict` keyed by `(day, base)`.
   - Historical entries (`day < today()`) never expire.
   - Current and future entries (`day >= today()`) expire when `monotonic() - fetched_at >= ttl_s`.
   - Lookback caching: all probed non-published days share the cached result under their respective date keys.
   - Guarded by a `threading.Lock`.
