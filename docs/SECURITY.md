# Security Policy

## Threat Model

1. **DoS via Unbounded Growth**:
   - Mitigated by `max_entries` cache bound and `max_lookback_days` limit (0-31).

2. **Numeric Precision Hazards**:
   - Floating-point inputs are explicitly rejected (only `Decimal` or `int` allowed).
   - Arithmetic is strictly handled with `Decimal` (prec=28).

3. **Information Leakage**:
   - Error messages are truncated to 200 characters and contain no sensitive data.

## Limits
- The library does not perform network I/O; security of the `RateSource` implementation is the user's responsibility.
- No global mutable state is used; logging uses `NullHandler`.