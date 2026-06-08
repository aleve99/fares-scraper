"""
Comparison tests: native airline scrapers vs Google Flights default implementation.

These are integration tests that hit real APIs. Run with:
    python -m pytest tests/test_comparison.py -v -s
"""

import pytest
import logging
from datetime import date, timedelta
from typing import List, Tuple, Set

from fares_scraper.base import ScraperSettings, GoogleFlightsScraper
from fares_scraper.airlines import RyanairScraper, WizzAirScraper
from fares_scraper.base.types import OneWayFare

logger = logging.getLogger("test.comparison")

# Search a short window starting a week out to ensure flights exist
SEARCH_FROM = date.today() + timedelta(days=7)
SEARCH_TO = SEARCH_FROM + timedelta(days=2)

TEST_CONFIG = ScraperSettings(
    timeout=30,
    pool_size=10,
    max_retries=3,
)


def compare_fares(
    native_fares: List[OneWayFare],
    gf_fares: List[OneWayFare],
    source_name: str,
) -> Tuple[int, Set, Set]:
    """Compare fares from a native scraper and Google Flights.

    Matches by (departure_date, flight_number). Returns:
        (matched_count, only_in_native_keys, only_in_gf_keys)
    """
    native_by_key = {}
    for f in native_fares:
        key = (f.dep_time, f.operating_flight_number)
        native_by_key[key] = f

    gf_by_key = {}
    for f in gf_fares:
        key = (f.dep_time, f.operating_flight_number)
        gf_by_key[key] = f

    matched = 0
    price_diffs: List[float] = []

    for key in native_by_key:
        if key in gf_by_key:
            matched += 1
            native_price = native_by_key[key].fare
            gf_price = gf_by_key[key].fare
            price_diffs.append(abs(native_price - gf_price))

    only_native = set(native_by_key.keys()) - set(gf_by_key.keys())
    only_gf = set(gf_by_key.keys()) - set(native_by_key.keys())

    # Print comparison summary
    print(f"\n{'='*60}")
    print(f"COMPARISON: {source_name} vs Google Flights")
    print(f"{'='*60}")
    print(f"  Date range: {SEARCH_FROM} -> {SEARCH_TO}")
    print(f"  {source_name} fares:     {len(native_fares)}")
    print(f"  Google Flights fares: {len(gf_fares)}")
    print(f"  Matched (by flight# + date): {matched}")
    print(f"  Only in {source_name}: {len(only_native)}")
    print(f"  Only in Google Flights: {len(only_gf)}")

    if price_diffs:
        avg_diff = sum(price_diffs) / len(price_diffs)
        max_diff = max(price_diffs)
        print(f"  Avg price diff (matched):  {avg_diff:.2f}")
        print(f"  Max price diff (matched):  {max_diff:.2f}")
        print(f"  NOTE: price diff is expected (different currencies / aggregation)")

    if only_native:
        print(f"\n  Flights only in {source_name}:")
        for d, fn in sorted(only_native)[:5]:
            f = native_by_key[(d, fn)]
            print(f"    {d} | {f.operating_carrier}{fn} | {f.fare} {f.currency}")
        if len(only_native) > 5:
            print(f"    ... and {len(only_native) - 5} more")

    if only_gf:
        print(f"\n  Flights only in Google Flights:")
        for d, fn in sorted(only_gf)[:5]:
            f = gf_by_key[(d, fn)]
            print(f"    {d} | {f.operating_carrier}{fn} | {f.fare} {f.currency}")
        if len(only_gf) > 5:
            print(f"    ... and {len(only_gf) - 5} more")

    print(f"{'='*60}\n")

    return matched, only_native, only_gf


@pytest.mark.asyncio
async def test_ryanair_vs_google_flights():
    """Compare Ryanair native scraper vs Google Flights for BGY -> STN."""
    origin = "BGY"
    destinations = ["STN"]
    # Include all Ryanair operator codes: FR, RK (UK), RR (BUZZ)
    ryanair_codes = ["FR", "RK", "RR"]

    # 1. Fetch from Ryanair native scraper
    async with RyanairScraper(config=TEST_CONFIG, USD=True) as ryanair:
        native_fares = await ryanair.search_one_way_fares(
            origin=origin,
            from_date=SEARCH_FROM,
            to_date=SEARCH_TO,
            destinations=destinations,
        )

    # 2. Fetch from Google Flights
    async with GoogleFlightsScraper(config=TEST_CONFIG, carrier_codes=ryanair_codes) as gf:
        gf_fares = await gf.search_one_way_fares(
            origin=origin,
            from_date=SEARCH_FROM,
            to_date=SEARCH_TO,
            destinations=destinations,
        )

    # 3. Compare
    matched, only_native, only_gf = compare_fares(native_fares, gf_fares, "Ryanair")

    # Both sources should find flights on this high-frequency route
    assert len(native_fares) > 0, "Ryanair should find fares on BGY -> STN"
    assert len(gf_fares) > 0, "Google Flights should find Ryanair fares on BGY -> STN"


@pytest.mark.asyncio
async def test_wizzair_vs_google_flights():
    """Compare WizzAir native scraper vs Google Flights for a known route."""
    origin = "FCO"
    destinations = ["TIA"]

    # WizzAir operates under multiple AOCs: W6 (Hungary), W4 (Malta), W9 (UK)
    wizzair_codes = ["W6", "W4", "W9"]

    # 1. Fetch from WizzAir native scraper
    async with WizzAirScraper(config=TEST_CONFIG) as wizzair:
        native_fares = await wizzair.search_one_way_fares(
            origin=origin,
            from_date=SEARCH_FROM,
            to_date=SEARCH_TO,
            destinations=destinations,
        )

    # Detect actual carrier codes used by native scraper
    native_carriers = set(f.operating_carrier for f in native_fares)
    print(f"\n  WizzAir native carrier codes on this route: {native_carriers}")

    # 2. Fetch from Google Flights using all WizzAir codes
    async with GoogleFlightsScraper(config=TEST_CONFIG, carrier_codes=wizzair_codes) as gf:
        gf_fares = await gf.search_one_way_fares(
            origin=origin,
            from_date=SEARCH_FROM,
            to_date=SEARCH_TO,
            destinations=destinations,
        )

    # 3. Compare
    matched, only_native, only_gf = compare_fares(native_fares, gf_fares, "WizzAir")

    # Both sources should find flights
    assert len(native_fares) > 0, "WizzAir should find fares on FCO -> TIA"
    assert len(gf_fares) > 0, "Google Flights should find WizzAir fares on FCO -> TIA"
