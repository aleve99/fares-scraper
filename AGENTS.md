# AGENTS.md

## Cursor Cloud specific instructions

### Overview

`fares-scraper` is a Python library (not a standalone app/service) for asynchronously scraping airline fares. There are no servers, databases, or Docker containers to run. The library is consumed programmatically via `async with SomeScraper() as scraper:` patterns.

### Development setup

```bash
pip install -e .          # editable install with all deps
pip install ruff pytest   # dev tooling (not in pyproject.toml extras yet)
```

### Lint

```bash
ruff check .
```

The codebase has some existing E701 (multiple statements on one line) violations. These are pre-existing style choices, not regressions.

### Tests

No test suite exists yet. `pytest` is installed for future use. Verify correctness by importing and running scraper instances programmatically.

### Hello-world verification

```python
import asyncio
from datetime import date, timedelta
from fares_scraper.airlines import RyanairScraper
from fares_scraper.base import ScraperSettings

async def demo():
    async with RyanairScraper(config=ScraperSettings(timeout=30)) as s:
        await s.update_active_airports()
        print(f"Airports: {len(s.active_airports)}")

asyncio.run(demo())
```

This makes a real HTTP call to the Ryanair API — no API keys or proxies required for basic testing.

### Key caveats

- All scrapers require outbound HTTP access (airline APIs / Google Flights). No authentication tokens are needed for Ryanair; Google Flights scraper works without API keys.
- Proxy rotation is optional — configured via `SCRAPER_PROXIES` env var or `.env` file.
- The library targets Python >= 3.10; the VM has Python 3.12.
- `ruff` and `pytest` are not declared as project optional-dependencies — install them separately.
