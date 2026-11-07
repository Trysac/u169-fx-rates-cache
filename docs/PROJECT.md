# Project record

## Objective

Convert amounts between currencies with Decimal using dated rates from a pluggable source, bounded LRU caching, weekend lookback and cross rates through the base

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 1169123 / 28090 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.1725 |

## Factory run u169 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4103 | 627 | 0 | 0 | 0.0027 |
| generation | gemini-3.8-flash | yes | 4103 | 9456 | 0 | 0 | 0.0193 |
| generation | gemini-3.8-flash | yes | 4137 | 9705 | 0 | 0 | 0.0197 |
| fix-1 | gemini-3.1-flash-lite | no | 26380 | 1569 | 0 | 34461 | 0.0098 |
| fix-2 | gemini-3.1-flash-lite | no | 101186 | 2931 | 0 | 582239 | 0.0442 |
| fix-3 | gemini-3.1-flash-lite | no | 48542 | 1349 | 0 | 140586 | 0.0177 |
| fix-4 | gemini-3.1-flash-lite | no | 16966 | 623 | 0 | 2004 | 0.0052 |
| docs | gemini-3.1-flash-lite | no | 204416 | 1830 | 0 | 0 | 0.0538 |

Total: $0.1725. Prices: Anthropic list prices.
