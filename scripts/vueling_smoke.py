#!/usr/bin/env python3
"""Optional manual smoke test for ``VuelingScraper``.

Environment (all optional except proxies recommended from blocked networks):

- ``SCRAPER_PROXIES`` — comma-separated proxy URLs (same as other scrapers).
- ``SCRAPER_VUELING_BEARER_TOKEN`` — partner FlightCalendar bearer token (required
  for fare search and calendar route dates).
- ``SCRAPER_TIMEOUT``, ``SCRAPER_POOL_SIZE``, … — standard scraper settings.

Example::

    SCRAPER_PROXIES=http://127.0.0.1:8888 \\
    SCRAPER_VUELING_BEARER_TOKEN=*** \\
    python scripts/vueling_smoke.py BCN
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

from fares_scraper.airlines.vueling import VuelingScraper
from fares_scraper.base.config import ScraperSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vueling_smoke")


async def run(origin: str) -> None:
    cfg = ScraperSettings()
    async with VuelingScraper(cfg) as scraper:
        dests = await scraper.get_destination_codes(origin)
        logger.info("Destinations from %s: %s …", origin, dests[:15])
        if dests:
            sample = dests[0]
            dates = await scraper.get_available_dates(origin, sample)
            logger.info("Sample available dates %s-%s: %s", origin, sample, dates[:12])

        if cfg.vueling_bearer_token:
            d0 = date.today() + timedelta(days=14)
            d1 = d0 + timedelta(days=5)
            ow = await scraper.search_one_way_fares(origin, d0, d1, destinations=dests[:3])
            logger.info("One-way sample count: %s", len(ow))
            if ow:
                logger.info("First fare: %s", ow[0].model_dump())


def main() -> None:
    p = argparse.ArgumentParser(description="Vueling scraper smoke test")
    p.add_argument("origin", nargs="?", default="BCN", help="Origin IATA (default BCN)")
    args = p.parse_args()
    try:
        asyncio.run(run(args.origin.upper()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
