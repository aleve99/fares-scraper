"""
Integration smoke test against EasyJet API (live network).

Run: python -m pytest tests/test_easyjet_smoke.py -v
"""

import asyncio
from datetime import date, timedelta

import pytest

from fares_scraper.airlines.easyjet import EasyJetScraper
from fares_scraper.base.config import ScraperSettings


@pytest.mark.asyncio
async def test_easyjet_destinations_and_one_way_lin_fra():
    # Use a proxy if available, otherwise it might fail due to Akamai
    cfg = ScraperSettings()
    
    async with EasyJetScraper(config=cfg) as s:
        dests = await s.get_destination_codes("LIN")
        assert "FRA" in dests

        dates = await s.get_available_dates("LIN", "FRA")
        assert len(dates) > 0

        # Find a date that is available
        target_date = date.fromisoformat(dates[0])

        ow = await s.search_one_way_fares(
            "LIN",
            target_date,
            target_date + timedelta(days=2),
            destinations=["FRA"],
        )
        assert len(ow) >= 1
        assert ow[0].origin == "LIN"
        assert ow[0].destination == "FRA"
        assert ow[0].fare > 0
        assert ow[0].operating_carrier == "U2"


@pytest.mark.asyncio
async def test_easyjet_round_trip_lin_fra():
    cfg = ScraperSettings()
    
    async with EasyJetScraper(config=cfg) as s:
        dates = await s.get_available_dates("LIN", "FRA")
        assert len(dates) > 0
        
        target_date = date.fromisoformat(dates[0])
        
        rt = await s.search_round_trip_fares(
            "LIN",
            min_days=2,
            max_days=7,
            from_date=target_date,
            to_date=target_date + timedelta(days=7),
            destinations=["FRA"],
        )
        assert len(rt) >= 1
        assert rt[0].outbound.origin == "LIN"
        assert rt[0].outbound.destination == "FRA"
        assert rt[0].inbound.origin == "FRA"
        assert rt[0].inbound.destination == "LIN"
