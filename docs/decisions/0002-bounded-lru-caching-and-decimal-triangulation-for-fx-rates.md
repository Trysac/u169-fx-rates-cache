# Bounded LRU Caching and Decimal Triangulation for FX Rates

Status: accepted (generated, pending human review)

## Context

Converting currency requires reliable non-float arithmetic, weekend/holiday rate lookback, and safe bounded caching to prevent unbounded memory usage.

## Decision

Use Python stdlib Decimal with localcontext (prec=28, ROUND_HALF_EVEN), an OrderedDict LRU cache guarded by threading.Lock, and an explicit RateSource protocol with RateNotAvailable lookback fallback.

## Consequences

Offline-testable, deterministic financial operations with bounded memory footprints and strict validation of currency codes and rates.
