# Project record

## Objective

Convert amounts between currencies with Decimal using dated rates from a pluggable source, bounded LRU caching, weekend lookback and cross rates through the base.

## Scope

- Public API documented in README.md, typed and tested.

## Out of Scope

- Shipping a real network rates provider.
- Minor-unit conversion tables.
- Historical bulk loading.
- Bid and ask spreads.

## Effort metrics

| Metric | Value |
|---|---|
| Tokens (input / output) | 371240 / 12185 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.0932 |

## Factory run u169b (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4137 | 9572 | 0 | 0 | 0.0195 |
| fix-1 | gemini-3.1-flash-lite | no | 20455 | 913 | 0 | 12196 | 0.0068 |
| audit | gemini-3.1-flash-lite | no | 37228 | 176 | 0 | 85506 | 0.0117 |
| docs | gemini-3.1-flash-lite | no | 211718 | 1524 | 0 | 0 | 0.0552 |

Total: $0.0932. Prices: Anthropic list prices.
