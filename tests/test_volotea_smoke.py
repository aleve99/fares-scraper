"""
Integration smoke test against Volotea JSON CDN (live network).

Run: python -m pytest tests/test_volotea_smoke.py -v
"""

import asyncio
from datetime import date

import pytest

from fares_scraper.airlines.volotea import VoloteaScraper


@pytest.mark.asyncio
async def test_volotea_destinations_and_one_way_ath_bes():
    async with VoloteaScraper() as s:
        dests = await s.get_destination_codes("ATH")
        assert "BES" in dests

        dates = await s.get_available_dates("ATH", "BES")
        assert len(dates) > 0

        ow = await s.search_one_way_fares(
            "ATH",
            date(2026, 4, 11),
            date(2026, 4, 11),
            destinations=["BES"],
        )
        assert len(ow) >= 1
        assert ow[0].origin == "ATH"
        assert ow[0].destination == "BES"
        assert ow[0].fare > 0


@pytest.mark.asyncio
async def test_volotea_cta_direct_markets_exclude_connection_sxb():
    """CTA→SXB is a connection market (e.g. via FCO); only direct Markets rows are used."""
    async with VoloteaScraper() as s:
        dests = await s.get_destination_codes("CTA")
        assert "SXB" not in dests

        ow = await s.search_one_way_fares(
            "CTA",
            date(2026, 6, 1),
            date(2026, 6, 7),
            destinations=["SXB"],
        )
        assert ow == []

        assert len(dests) >= 1
        ow_direct = await s.search_one_way_fares(
            "CTA",
            date(2026, 6, 1),
            date(2026, 6, 14),
            destinations=[dests[0]],
        )
        assert len(ow_direct) >= 1


@pytest.mark.asyncio
async def test_volotea_round_trip_ath_bes():
    async with VoloteaScraper() as s:
        rt = await s.search_round_trip_fares(
            "ATH",
            min_days=3,
            max_days=14,
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 30),
            destinations=["BES"],
        )
        assert len(rt) >= 1
        assert rt[0].outbound.origin == "ATH"
        assert rt[0].outbound.destination == "BES"
        assert rt[0].inbound.origin == "BES"
        assert rt[0].inbound.destination == "ATH"


def test_volotea_404_schedule_returns_none():
    """_get_json_or_404 must not retry on missing routes."""

    async def run():
        async with VoloteaScraper() as s:
            raw = await s._get_json_or_404(
                "https://json.volotea.com/dist/schedule/XXX-YYY_schedule.json"
            )
            assert raw is None

    asyncio.run(run())
