"""
Integration smoke test against Wizz Air API (live network).

Run: ./venv/bin/python -m pytest tests/test_wizzair_smoke.py -v
"""

from datetime import date, timedelta

import pytest

from fares_scraper.airlines.wizzair import WizzAirScraper
from fares_scraper.base.config import ScraperSettings

WIZZ_CARRIERS = {"W6", "W4", "W9"}


@pytest.mark.asyncio
async def test_wizzair_smoke_fco_tia():
    cfg = ScraperSettings(timeout=30, pool_size=10, max_retries=3)
    from_date = date.today() + timedelta(days=7)
    to_date = from_date + timedelta(days=2)

    async with WizzAirScraper(config=cfg) as s:
        assert s.build_number
        assert s.build_number.count(".") == 2

        dests = await s.get_destination_codes("FCO")
        assert "TIA" in dests

        fares = await s.search_one_way_fares(
            "FCO",
            from_date,
            to_date,
            destinations=["TIA"],
        )

    assert len(fares) >= 1
    assert fares[0].origin == "FCO"
    assert fares[0].destination == "TIA"
    assert fares[0].fare > 0
    assert fares[0].operating_carrier in WIZZ_CARRIERS
