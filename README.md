# fx-rates-cache

[![PyPI version](https://img.shields.io/pypi/v/trysac-fx-rates-cache)](https://pypi.org/project/trysac-fx-rates-cache/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-fx-rates-cache)](LICENSE)
[![CI](https://github.com/Trysac/u169-fx-rates-cache/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u169-fx-rates-cache/actions/workflows/ci.yml)

Convert amounts between currencies with Decimal using dated rates from a pluggable source, bounded LRU caching, weekend lookback and cross rates through the base

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-fx-rates-cache
# or
uv add trysac-fx-rates-cache
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import fx_rates_cache

# normalize() trims surrounding whitespace and lower-cases the text.
print(fx_rates_cache.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    fx_rates_cache.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
