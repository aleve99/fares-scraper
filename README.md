# Fares Scraper Framework

A modular, asynchronous framework for scraping airline fares. Supports airline-specific API scrapers and a Google Flights fallback for any airline.

## Structure

- `fares_scraper/`: Main package directory.
    - `base/`: Core components independent of any specific airline.
        - `base_scraper.py`: `BaseScraper` abstract class handling async sessions and retries.
        - `google_flights.py`: `GoogleFlightsScraper` — concrete `BaseScraper` using Google Flights as data source.
        - `session_manager.py`: Manages `aiohttp` sessions and proxy rotation.
        - `payload.py`: `BasePayload` class for API request data.
        - `types.py`: Common Pydantic models (`OneWayFare`, `RoundTripFare`, `Airport`, etc.).
        - `config.py`: `ScraperSettings` with env-variable support.
        - `exceptions.py`: `ScraperError`, `ProxyError`, `RateLimitError`.
    - `airlines/`: Airline-specific implementations.
        - `ryanair/`: Ryanair (Farfnd + Availability APIs).
        - `wizzair/`: WizzAir (timetableV2 + travelAgencyBooking APIs).
    - `utils/`: Shared utilities.
- `pyproject.toml`: Modern packaging configuration.
- `requirements.txt`: Package dependencies for pip.

## Installation

You can install the framework in editable mode for development:

```bash
pip install -e .
```

## Adding a new airline

### Option A: Google Flights (no reverse engineering needed)

For any airline, create a scraper by just specifying carrier codes. Google Flights provides fare data without needing access to the airline's own API.

**As a subclass:**

```python
from fares_scraper.base import GoogleFlightsScraper

class EasyJetScraper(GoogleFlightsScraper):
    CARRIER_CODES = ["U2"]
```

**Without subclassing:**

```python
from fares_scraper.base import GoogleFlightsScraper

async with GoogleFlightsScraper(carrier_codes=["U2"]) as scraper:
    fares = await scraper.search_one_way_fares(
        origin="FCO",
        from_date=date(2026, 3, 1),
        destinations=["CDG"]
    )
```

> **Note:** `GoogleFlightsScraper` returns prices in USD. `get_destination_codes()` and `get_available_dates()` are not available via Google Flights — provide destinations and date ranges explicitly, or override those methods in your subclass.

### Option B: Airline-specific API

For deeper integration (more data, native currency, seats left, etc.):

1. Create a new directory in `fares_scraper/airlines/` (e.g., `fares_scraper/airlines/easyjet/`).
2. Implement a subclass of `BaseScraper`.
3. Define your airline-specific URLs and payload generators.
4. Implement methods for fetching airports, destinations, and fares.
5. Use `self._execute_requests_concurrently` to handle multiple requests in parallel.

## Example Usage

```python
import asyncio
from datetime import date
from fares_scraper.airlines import RyanairScraper, WizzAirScraper
from fares_scraper.base import GoogleFlightsScraper, ScraperSettings

async def main():
    config = ScraperSettings(timeout=30, pool_size=10)

    # Ryanair via native API
    async with RyanairScraper(config=config) as scraper:
        fares = await scraper.search_one_way_fares(
            origin="BGY",
            from_date=date(2026, 3, 1),
            destinations=["STN"]
        )
        for fare in fares:
            print(f"{fare.dep_time}: {fare.fare} {fare.currency}")

    # Any airline via Google Flights
    async with GoogleFlightsScraper(config=config, carrier_codes=["IB"]) as scraper:
        fares = await scraper.search_one_way_fares(
            origin="MAD",
            from_date=date(2026, 3, 1),
            destinations=["BCN", "LIS"]
        )
        for fare in fares:
            print(f"{fare.dep_time}: {fare.fare} {fare.currency}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Features

- **Asynchronous**: Built on `aiohttp` and `asyncio` for maximum performance.
- **Concurrency Control**: Semaphore-limited concurrent requests with automatic retry and exponential backoff.
- **Proxy Rotation**: Automatically rotates proxies from a configurable pool.
- **Google Flights Default**: Any airline can be scraped via Google Flights with just a carrier code — no API reverse engineering required.
- **Modular**: Clean separation between core framework (`base/`), airline implementations (`airlines/`), and shared utilities (`utils/`).
- **Pydantic Models**: Type-safe fare and airport models with automatic validation, supporting distinct operating and marketing flight numbers, and generating unique flight/fare keys.
- **Env Config**: `ScraperSettings` loads from environment variables (`SCRAPER_TIMEOUT`, `SCRAPER_PROXIES`, etc.).
