# Fares Scraper Framework

A modular, asynchronous framework for scraping airline fares, based on a high-performance Ryanair scraper.

## Structure

- `fares_scraper/`: Main package directory.
    - `base/`: Core components independent of any specific airline.
        - `base_scraper.py`: `BaseScraper` class handling async sessions and retries.
        - `session_manager.py`: Manages `aiohttp` sessions and proxy rotation.
        - `payload.py`: `BasePayload` class for API request data.
        - `types.py`: Common dataclasses.
    - `airlines/`: Airline-specific implementations.
        - `ryanair/`: Implementation for Ryanair.
    - `utils/`: Shared utilities.
- `pyproject.toml`: Modern packaging configuration.
- `requirements.txt`: Package dependencies for pip.

## Installation

You can install the framework in editable mode for development:

```bash
pip install -e .
```

## How to add a new airline

1. Create a new directory in `fares_scraper/airlines/` (e.g., `fares_scraper/airlines/easyjet/`).
2. Implement a subclass of `BaseScraper`.
3. Define your airline-specific URLs and payload generators.
4. Implement methods for fetching airports, destinations, and fares.
5. Use `self._execute_requests_concurrently` to handle multiple requests in parallel.

## Example Usage

```python
import asyncio
from datetime import date
from fares_scraper.airlines.ryanair.ryanair import RyanairScraper

async def main():
    async with RyanairScraper() as scraper:
        fares = await scraper.search_one_way_fares(
            origin="BGY",
            from_date=date(2026, 3, 1),
            destinations=["STN"]
        )
        for fare in fares:
            print(f"{fare.dep_time}: {fare.fare} {fare.currency}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Features

- **Asynchronous**: Built on `aiohttp` and `asyncio` for maximum performance.
- **Concurrency Control**: Uses semaphores to limit the number of simultaneous connections.
- **Proxy Rotation**: Automatically rotates proxies from a pool for each request.
- **Modular**: Clean separation between core logic and airline-specific APIs.
```
