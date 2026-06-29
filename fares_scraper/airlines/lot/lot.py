from __future__ import annotations

import os
import logging
from typing import Dict, List, Optional, Tuple, Iterable
from datetime import date, timedelta

import aiohttp
from yarl import URL

from ...base.scrapers.base_scraper import AiohttpScraper
from ...base.config import settings, ScraperSettings
from ...base.types.common import Airport, OneWayFare, RoundTripFare
from ...base.exceptions import ScraperError

from .models import (
    LotPriceBoxesResponse,
    LotCalendarResponse,
    LotAirBoundsResponse,
)
from .payload import LotSearchPayload

logger = logging.getLogger("lot_scraper")


class LotScraper(AiohttpScraper):
    """
    Scraper for LOT Polish Airlines (lot.com).

    Authentication flow
    -------------------
    LOT's backend uses two layers of protection:

    1. **Akamai Bot Manager** - solved by passing a fresh ``aws-waf-token``
       cookie (set via the environment variable ``LOT_AWS_WAF_TOKEN``).

    2. **Angular XSRF** - the ``__HOST-XSRF-TOKEN`` cookie (and matching
       ``X-XSRF-TOKEN`` request header) is only issued when the *booking
       search page* is loaded, NOT the homepage.

    The warm-up therefore performs **two sequential GETs**:
      Step 1 - homepage  -> establishes Akamai session cookies
      Step 2 - /it/it/booking-new/search  -> triggers XSRF token issuance

    The XSRF token is then extracted from either the cookie jar or, as a
    fallback, the raw ``Set-Cookie`` response header (aiohttp can silently
    drop ``__HOST-`` prefixed cookies due to strict RFC 6265bis enforcement).
    """

    BASE_URL = "https://www.lot.com"
    HOME_PATH = "/it/it"
    BOOKING_SEARCH_PATH = "/it/it/booking-new/search"

    MARKETS_URL = f"{BASE_URL}/it/it/api/markets.json"
    AIRPORTS_URL = f"{BASE_URL}/it/it/api/lowfarecalendarairports.json"
    AIR_BOUNDS_URL = f"{BASE_URL}/api/ndc/v2/air-bounds"
    AIR_CALENDARS_URL = f"{BASE_URL}/api/ndc/v2/air-calendars"

    CARRIER_CODES = ["LO"]
    DEFAULT_MARKET = "it"
    DEFAULT_LANGUAGE = "it"
    DEFAULT_CURRENCY = "EUR"

    # All possible XSRF cookie name variants to probe
    XSRF_COOKIE_NAMES = [
        "__HOST-XSRF-TOKEN",
        "__Host-XSRF-TOKEN",
        "XSRF-TOKEN",
        "xsrf-token",
    ]

    def __init__(
        self,
        market: str = DEFAULT_MARKET,
        language: str = DEFAULT_LANGUAGE,
        currency: str = DEFAULT_CURRENCY,
        config: ScraperSettings = settings,
        aws_waf_token: Optional[str] = None,
    ):
        self.market = market
        self.language = language
        self.currency = currency
        self._aws_waf_token = aws_waf_token or os.environ.get("LOT_AWS_WAF_TOKEN", "")
        self._xsrf_token: Optional[str] = None
        self._routes: Dict[str, List[str]] = {}  # origin -> [destination, ...]

        default_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": f"{language}-IT,{language};q=0.9,en;q=0.8",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/{market}/{language}/",
            "channel": "WEB",
            "language": language,
            "market": market,
        }

        # Pass warm_up_url=None to disable the base SessionManager's single-step
        # warm-up — we manage it manually in _warm_up() with two steps.
        super().__init__(
            config=config,
            base_url=self.BASE_URL,
            warm_up_url=None,
            default_headers=default_headers,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _seed_waf_token(self, session: aiohttp.ClientSession) -> None:
        """Inject the aws-waf-token into the session cookie jar before warm-up."""
        if self._aws_waf_token:
            session.cookie_jar.update_cookies(
                {"aws-waf-token": self._aws_waf_token},
                URL(self.BASE_URL),
            )
            logger.info("Seeded aws-waf-token from environment")

    def _extract_xsrf_from_jar(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[str]:
        """Try to read the XSRF token from the session cookie jar."""
        cookies = session.cookie_jar.filter_cookies(URL(url))
        for name in self.XSRF_COOKIE_NAMES:
            if name in cookies:
                return cookies[name].value
        return None

    @staticmethod
    def _extract_xsrf_from_headers(response: aiohttp.ClientResponse) -> Optional[str]:
        """
        Fallback: parse the XSRF token directly from raw Set-Cookie headers.

        aiohttp silently drops ``__HOST-`` prefixed cookies from its jar
        due to strict RFC 6265bis enforcement (the prefix requires Secure +
        no Domain attribute, which aiohttp's CookieJar validates strictly).
        Reading the raw header bypasses that filter.
        """
        for header_value in response.headers.getall("Set-Cookie", []):
            parts = header_value.split(";")
            if not parts:
                continue
            kv = parts[0].strip()
            for name in ["__HOST-XSRF-TOKEN", "__Host-XSRF-TOKEN", "XSRF-TOKEN"]:
                if kv.upper().startswith(name.upper() + "="):
                    return kv.split("=", 1)[1]
        return None

    async def _warm_up(self) -> None:
        """
        Two-step warm-up:
          Step 1 - GET homepage -> Akamai cookies (_abck, ak_bmsc, bm_sz)
          Step 2 - GET booking search page -> __HOST-XSRF-TOKEN issuance
        """
        session = await self.sm.get_session()
        self._seed_waf_token(session)

        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        home_url = f"{self.BASE_URL}{self.HOME_PATH}"
        search_url = f"{self.BASE_URL}{self.BOOKING_SEARCH_PATH}"
        html_accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

        # --- Step 1: homepage ---
        logger.info(f"Warming up session via {home_url}")
        try:
            async with session.get(
                home_url,
                timeout=timeout,
                headers={"Accept": html_accept},
            ) as resp:
                resp.raise_for_status()
                logger.info(
                    f"Cookies after homepage warm-up: "
                    f"{list({c.key for c in session.cookie_jar})}"
                )
        except Exception as e:
            logger.warning(f"Homepage warm-up failed (continuing anyway): {e}")

        # --- Step 2: booking search page ---
        logger.info(f"Warming up XSRF via {search_url}")
        try:
            async with session.get(
                search_url,
                timeout=timeout,
                headers={
                    "Accept": html_accept,
                    "Referer": home_url,
                },
            ) as resp:
                resp.raise_for_status()

                # Primary: cookie jar
                token = self._extract_xsrf_from_jar(session, search_url)

                # Fallback: raw Set-Cookie headers (handles __HOST- prefix quirk)
                if not token:
                    token = self._extract_xsrf_from_headers(resp)

                if token:
                    self._xsrf_token = token
                    logger.info("XSRF token acquired successfully")
                else:
                    all_cookies = {c.key: c.value for c in session.cookie_jar}
                    logger.error(
                        f"No XSRF token found after two-step warm-up "
                        f"-- cookies: {all_cookies}"
                    )

                # Cache warm-up cookies for stateless requests
                warmed_cookies = session.cookie_jar.filter_cookies(URL(search_url))
                self.sm._warm_up_cookies = {k: v.value for k, v in warmed_cookies.items()}

        except Exception as e:
            logger.warning(f"Booking search warm-up failed: {e}")

    def _api_headers(self) -> Dict[str, str]:
        """Headers required for all JSON API calls."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": (
                f"{self.BASE_URL}/{self.market}/{self.language}/booking-new/search"
            ),
            "channel": "WEB",
            "language": self.language,
            "market": self.market,
            "action": "search",
            "step": "1",
        }
        if self._xsrf_token:
            headers["X-XSRF-TOKEN"] = self._xsrf_token
        return headers

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    async def update_active_airports(self) -> None:
        """Two-step warm-up + fetch route map from /lowfarecalendarairports.json."""
        await self._warm_up()

        try:
            resp = await self.get(self.AIRPORTS_URL, headers=self._api_headers())
            data = await resp.json(content_type=None)
            parsed = LotPriceBoxesResponse.model_validate(data)
        except Exception as e:
            logger.error(f"Failed to fetch LOT airports: {e}")
            return

        airports: Dict[str, Airport] = {}
        routes: Dict[str, set] = {}

        for pb in parsed.priceBoxes:
            # Index only Economy one-way entries to build the route map
            if pb.cabinClass != "E" or pb.tripType != "O":
                continue

            for iata, name in [
                (pb.originAirportIATA, pb.originAirportName),
                (pb.destinationAirportIATA, pb.destinationAirportName),
            ]:
                if iata not in airports:
                    airports[iata] = Airport(
                        iata_code=iata,
                        name=name,
                        country_code=None,
                        city=None,
                    )

            routes.setdefault(pb.originAirportIATA, set()).add(
                pb.destinationAirportIATA
            )

        self.active_airports = tuple(airports.values())
        self._routes = {orig: list(dests) for orig, dests in routes.items()}
        logger.info(
            f"LOT: {len(self.active_airports)} airports, "
            f"{sum(len(v) for v in self._routes.values())} routes indexed"
        )

    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        return tuple(self._routes.get(origin.upper(), []))

    async def get_available_dates(
        self, origin: str, destination: str
    ) -> Tuple[str, ...]:
        """
        LOT does not expose a dedicated date-availability endpoint.
        Delegates to the calendar fares endpoint for a rolling window.
        """
        payload = LotSearchPayload(
            origin=origin.upper(),
            destination=destination.upper(),
            departureDate=date.today().isoformat(),
            returnDate=None,
            market=self.market,
            language=self.language,
            currency=self.currency,
        )
        try:
            resp = await self.post(
                self.AIR_CALENDARS_URL,
                json=payload.to_air_calendars_dict(),
                headers=self._api_headers(),
            )
            data = await resp.json(content_type=None)
            parsed = LotCalendarResponse.model_validate(data)
            return tuple(
                f.departureDate
                for f in parsed.fares
                if f.available and f.price is not None
            )
        except Exception as e:
            logger.warning(
                f"get_available_dates failed for {origin}->{destination}: {e}"
            )
            return tuple()

    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = [],
    ) -> List[OneWayFare]:
        dest_list = list(destinations) or await self.get_destination_codes(origin)
        if not dest_list:
            return []
        to_date = to_date or from_date
        tasks = [
            self._fetch_one_way(origin, dest, from_date, to_date)
            for dest in dest_list
        ]
        results = await self.run_concurrently(tasks)
        fares: List[OneWayFare] = []
        for r in results.results:
            if isinstance(r, list):
                fares.extend(r)
        return fares

    async def search_round_trip_fares(
        self,
        origin: str,
        min_days: int,
        max_days: int,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = [],
    ) -> List[RoundTripFare]:
        dest_list = list(destinations) or await self.get_destination_codes(origin)
        if not dest_list:
            return []
        to_date = to_date or from_date
        tasks = [
            self._fetch_round_trip(origin, dest, min_days, max_days, from_date, to_date)
            for dest in dest_list
        ]
        results = await self.run_concurrently(tasks)
        fares: List[RoundTripFare] = []
        for r in results.results:
            if isinstance(r, list):
                fares.extend(r)
        return fares

    # ------------------------------------------------------------------
    # Private fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_one_way(
        self,
        origin: str,
        destination: str,
        from_date: date,
        to_date: date,
    ) -> List[OneWayFare]:
        fares: List[OneWayFare] = []
        current = from_date
        while current <= to_date:
            payload = LotSearchPayload(
                origin=origin.upper(),
                destination=destination.upper(),
                departureDate=current.isoformat(),
                returnDate=None,
                market=self.market,
                language=self.language,
                currency=self.currency,
            )
            try:
                resp = await self.post(
                    self.AIR_BOUNDS_URL,
                    json=payload.to_air_bounds_dict(),
                    headers=self._api_headers(),
                )
                data = await resp.json(content_type=None)
                parsed = LotAirBoundsResponse.model_validate(data)
                for bound in parsed.outboundFlights:
                    if not bound.itinerary.segments:
                        continue
                    first_seg = bound.itinerary.segments[0]
                    last_seg = bound.itinerary.segments[-1]
                    fares.append(
                        OneWayFare(
                            origin=first_seg.origin,
                            destination=last_seg.destination,
                            departure_date=first_seg.departureDateTime[:10],
                            departure_time=first_seg.departureDateTime[11:16],
                            arrival_time=last_seg.arrivalDateTime[11:16],
                            flight_number=self.parse_flight_number(
                                first_seg.flightNumber, first_seg.carrierCode
                            ),
                            carrier_code=first_seg.carrierCode,
                            price=bound.totalPrice,
                            currency=bound.currency,
                            cabin_class=bound.cabinClass,
                            fare_family=bound.fareFamily,
                        )
                    )
            except Exception as e:
                logger.warning(
                    f"one-way fetch failed {origin}->{destination} on {current}: {e}"
                )
            current += timedelta(days=1)
        return fares

    async def _fetch_round_trip(
        self,
        origin: str,
        destination: str,
        min_days: int,
        max_days: int,
        from_date: date,
        to_date: date,
    ) -> List[RoundTripFare]:
        fares: List[RoundTripFare] = []
        current = from_date
        while current <= to_date:
            for stay in range(min_days, max_days + 1):
                return_date = current + timedelta(days=stay)
                payload = LotSearchPayload(
                    origin=origin.upper(),
                    destination=destination.upper(),
                    departureDate=current.isoformat(),
                    returnDate=return_date.isoformat(),
                    market=self.market,
                    language=self.language,
                    currency=self.currency,
                )
                try:
                    resp = await self.post(
                        self.AIR_BOUNDS_URL,
                        json=payload.to_air_bounds_dict(),
                        headers=self._api_headers(),
                    )
                    data = await resp.json(content_type=None)
                    parsed = LotAirBoundsResponse.model_validate(data)
                    for out in parsed.outboundFlights:
                        for inb in parsed.inboundFlights:
                            if not out.itinerary.segments or not inb.itinerary.segments:
                                continue
                            out_first = out.itinerary.segments[0]
                            out_last = out.itinerary.segments[-1]
                            inb_first = inb.itinerary.segments[0]
                            inb_last = inb.itinerary.segments[-1]
                            fares.append(
                                RoundTripFare(
                                    origin=out_first.origin,
                                    destination=out_last.destination,
                                    outbound_departure_date=out_first.departureDateTime[:10],
                                    outbound_departure_time=out_first.departureDateTime[11:16],
                                    outbound_arrival_time=out_last.arrivalDateTime[11:16],
                                    outbound_flight_number=self.parse_flight_number(
                                        out_first.flightNumber, out_first.carrierCode
                                    ),
                                    outbound_carrier_code=out_first.carrierCode,
                                    inbound_departure_date=inb_first.departureDateTime[:10],
                                    inbound_departure_time=inb_first.departureDateTime[11:16],
                                    inbound_arrival_time=inb_last.arrivalDateTime[11:16],
                                    inbound_flight_number=self.parse_flight_number(
                                        inb_first.flightNumber, inb_first.carrierCode
                                    ),
                                    inbound_carrier_code=inb_first.carrierCode,
                                    total_price=out.totalPrice + inb.totalPrice,
                                    currency=out.currency,
                                    cabin_class=out.cabinClass,
                                )
                            )
                except Exception as e:
                    logger.warning(
                        f"round-trip fetch failed {origin}->{destination} "
                        f"dep={current} ret={return_date}: {e}"
                    )
            current += timedelta(days=1)
        return fares
