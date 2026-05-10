#!/usr/bin/env python3
"""
Manual smoke test for VuelingScraper.

Uses ``PROXY`` (see ``ScraperSettings.proxy``) when set, e.g.:

    PROXY=http://127.0.0.1:8080 python scripts/manual_vueling.py

Requires outbound network access to ams.vueling.com / apiw.vueling.com.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

from fares_scraper.airlines.vueling import VuelingScraper


async def _run(origin: str, dest: str | None) -> None:
    logging.basicConfig(level=logging.INFO)
    async with VuelingScraper() as v:
        await v.update_active_airports()
        print(f"active_airports (sample): {[a.iata_code for a in v.active_airports[:15]]}")
        dests = await v.get_destination_codes(origin)
        print(f"destinations from {origin} (first 20): {list(dests[:20])}")
        if dest:
            dates = await v.get_available_dates(origin, dest)
            print(f"available_dates {origin}->{dest} (first 15): {list(dates[:15])}")


def main() -> None:
    p = argparse.ArgumentParser(description="Vueling scraper manual test (honours PROXY env).")
    p.add_argument("--origin", default="BCN")
    p.add_argument("--destination", default=None, help="Optional pair for get_available_dates")
    args = p.parse_args()
    asyncio.run(_run(args.origin, args.destination))


if __name__ == "__main__":
    main()
