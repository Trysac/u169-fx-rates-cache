# fx-rates-cache

Convert amounts between currencies with `Decimal` using dated rates from a pluggable source, bounded LRU caching, weekend lookback, and cross rates through a base currency.

## Features

- **Decimal-Only Arithmetic**: Prevents floating-point rounding errors in financial computations.
- **Pluggable Source**: Clean `RateSource` protocol easily adapted to any rates API (ECB, Fed, commercial).
- **Exact Rate Tracking**: Every conversion includes the exact `rate_date` used.
- **Weekend and Holiday Lookback**: Automatically falls back to previous business days when rates are unpublished.
- **Bounded LRU Cache**: In-memory thread-safe `OrderedDict` with TTL expiration for current-day rates and permanent caching for historical dates.

## Usage Example

```python
import datetime
from decimal import Decimal
from fx_rates_cache import FxConverter


class DailySource:
    def fetch(self, day: datetime.date, base: str):
        return {"USD": Decimal("1.0800"), "GBP": Decimal("0.8500")}


converter = FxConverter(DailySource(), base="EUR")
res = converter.convert(Decimal("100"), "EUR", "USD", on=datetime.date(2026, 11, 6))
print(f"{res.amount} {res.to_ccy} on {res.rate_date}")
```

## European Central Bank (ECB) XML Adapter Example

```python
import datetime
from decimal import Decimal
import xml.etree.ElementTree as ET
import urllib.request
from fx_rates_cache import RateNotAvailable, RateSource


class EcbDailySource(RateSource):
    URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    NS = {
        "gesmes": "http://www.gesmes.org/xml/2002-08-01",
        "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
    }

    def fetch(self, day: datetime.date, base: str) -> dict[str, Decimal]:
        if base != "EUR":
            raise RateNotAvailable("ECB base currency is EUR")
        with urllib.request.urlopen(self.URL) as resp:
            tree = ET.parse(resp)
        root = tree.getroot()
        cube_time = root.find(".//ecb:Cube[@time]", self.NS)
        if cube_time is None or cube_time.attrib["time"] != day.isoformat():
            raise RateNotAvailable(f"Rates for {day} not found in daily XML")
        rates = {}
        for cube in cube_time.findall("ecb:Cube", self.NS):
            rates[cube.attrib["currency"]] = Decimal(cube.attrib["rate"])
        return rates
```
