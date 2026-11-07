# Decimal precision conversion with pluggable rate source and bounded lookback cache

Status: accepted (generated, pending human review)

## Context

Applications performing financial calculations frequently suffer from float rounding errors, stale weekend lookups, and undocumented rates dates. We need a lightweight, offline-testable, Decimal-only conversion utility with pluggable rate providers and deterministic caching.

## Decision

Implement `FxConverter` using standard library Decimal arithmetic in a 28-precision context with `ROUND_HALF_EVEN`. Enforce 3-letter currency codes and reject floats. Implement lookback across non-publishing days and store results in a thread-safe LRU cache with monotonic TTL expiration for current-day rates.

## Consequences

Zero runtime dependencies. Full determinism and high precision in money arithmetic. Downstream applications provide their own rate provider adapters without network coupling in core conversion logic.
