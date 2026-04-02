import logging
import json
import asyncio
import time as time_module

from typing import Optional, List, Dict, Iterable, Tuple
from datetime import date, datetime, timedelta
from pydantic import ValidationError

from .base_scraper import BaseScraper
from ..config import settings, ScraperSettings
from ..types.common import (
    OneWayFare,
    RoundTripFare,
)
from ..types.google_flights import (
    GFSortBy,
    GFTripType,
    GFSeatClass,
    GFMaxStops,
    GFFlightRequest,
)

logger = logging.getLogger("scraper.google_flights")


class GoogleFlightsScraper(BaseScraper):
    """
    Concrete BaseScraper that uses Google Flights as the data source.

    Provides default implementations of all abstract methods, enabling any airline
    to get a working scraper by simply specifying carrier code(s).

    Usage as a subclass::

        class EasyJetScraper(GoogleFlightsScraper):
            CARRIER_CODES = ["U2"]

    Usage without subclassing::

        async with GoogleFlightsScraper(carrier_codes=["U2"]) as scraper:
            fares = await scraper.search_one_way_fares(...)

    Notes:
        - Prices are in USD (US locale).
        - Only direct flights (max_stops=0) to match the framework's per-flight model.
        - ``get_destination_codes()`` and ``get_available_dates()`` are not available
          via Google Flights and raise ``NotImplementedError``. Provide destinations
          explicitly in search methods.
    """

    CARRIER_CODES: List[str] = []

    # Google Flights RPC endpoint and tokens
    GF_URL = (
        "https://www.google.com/_/FlightsFrontendUi/data/"
        "travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    )
    GF_AT_TOKEN: str = ""
    GF_F_SID: str = ""
    GF_BL: str = ""
    GF_COOKIES: Dict[str, str] = {} # typically {"SOCS": "..."}

    # Static Google RPC params (infrastructure-level, unlikely to change)
    GF_HL = "en"
    GF_GL = "US"
    GF_SOC_APP = "162"
    GF_SOC_PLATFORM = "1"
    GF_SOC_DEVICE = "1"
    GF_RT = "c"

    def __init__(
        self,
        config: ScraperSettings = settings,
        carrier_codes: Optional[List[str]] = None,
        gf_at_token: Optional[str] = None,
        gf_f_sid: Optional[str] = None,
        gf_bl: Optional[str] = None,
        gf_cookies: Optional[Dict[str, str]] = None,
    ):
        super().__init__(
            config=config,
            base_url=None,
            warm_up_url=None,
            default_headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Accept": "*/*",
            },
        )
        if carrier_codes is not None:
            self.CARRIER_CODES = carrier_codes
        if gf_at_token is not None:
            self.GF_AT_TOKEN = gf_at_token
        if gf_f_sid is not None:
            self.GF_F_SID = gf_f_sid
        if gf_bl is not None:
            self.GF_BL = gf_bl
        if gf_cookies is not None:
            self.GF_COOKIES = gf_cookies

    # --- Abstract method implementations ---

    async def update_active_airports(self) -> None:
        """No-op. Google Flights doesn't require airline-specific airport initialization."""
        pass

    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        """Not available via Google Flights.

        Override in subclass with a hardcoded route list if needed.
        """
        raise NotImplementedError(
            "Google Flights does not expose per-airline route maps. "
            "Provide destinations explicitly or override this method."
        )

    async def get_available_dates(self, origin: str, destination: str) -> Tuple[str, ...]:
        """Not available via Google Flights.

        Override in subclass with your own logic if needed.
        """
        raise NotImplementedError(
            "Google Flights does not expose per-airline available dates. "
            "Provide a date range explicitly or override this method."
        )

    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = [],
    ) -> List[OneWayFare]:
        """Search for one-way fares using Google Flights.

        Destinations must be provided explicitly since Google Flights cannot
        resolve airline-specific route maps.
        """
        dest_list = list(destinations)
        if not dest_list:
            raise ValueError(
                "destinations must be provided for Google Flights-based scrapers "
                "(get_destination_codes is not available)."
            )

        if not to_date:
            to_date = from_date + timedelta(days=1)

        # Build one task per day
        dates: List[str] = []
        current = from_date
        while current <= to_date:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        airlines = self.CARRIER_CODES or None

        # One request per (day, destination) to avoid Google Flights result truncation.
        # GF caps results per request; bundling destinations loses data.
        tasks = [
            self._search_day([origin], [dest], d, airlines=airlines)
            for d in dates
            for dest in dest_list
        ]

        logger.info(
            f"Searching Google Flights: {origin} -> {len(dest_list)} dest(s) | "
            f"{len(dates)} days | {len(tasks)} requests | carriers={airlines}"
        )
        results = await self.run_concurrently(tasks)

        fares: List[OneWayFare] = []
        for res in results.results:
            if isinstance(res, Exception):
                logger.warning(f"Google Flights day-search failed: {res}")
                continue
            if isinstance(res, list):
                fares.extend(res)

        logger.info(
            f"Google Flights search complete in {results.execution_time:.2f}s, "
            f"found {len(fares)} fares."
        )
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
        """Search for round-trip fares by combining two one-way Google Flights searches."""
        dest_list = list(destinations)
        if not dest_list:
            raise ValueError(
                "destinations must be provided for Google Flights-based scrapers."
            )

        if not to_date:
            to_date = from_date + timedelta(days=30)

        # 1. Fetch outbound fares
        outbound_fares = await self.search_one_way_fares(
            origin=origin,
            from_date=from_date,
            to_date=to_date,
            destinations=dest_list,
        )

        if not outbound_fares:
            return []

        # 2. Fetch return fares for each unique destination concurrently.
        #    Uses asyncio.gather directly (not run_concurrently) to avoid
        #    holding semaphore slots at the outer level while the inner
        #    search_one_way_fares calls also compete for the semaphore.
        unique_dests = list(set(f.destination for f in outbound_fares))
        return_from = from_date + timedelta(days=min_days)
        return_to = to_date + timedelta(days=max_days)

        return_lists = await asyncio.gather(
            *(
                self.search_one_way_fares(
                    origin=dest,
                    from_date=return_from,
                    to_date=return_to,
                    destinations=[origin],
                )
                for dest in unique_dests
            ),
            return_exceptions=True,
        )

        return_fares_by_dest: dict[str, List[OneWayFare]] = {}
        for dest, res in zip(unique_dests, return_lists):
            if isinstance(res, list):
                return_fares_by_dest[dest] = res
            elif isinstance(res, Exception):
                logger.warning(f"Return fare search failed for {dest}: {res}")

        # 3. Combine into round-trip fares based on stay constraints
        round_trips: List[RoundTripFare] = []
        for out in outbound_fares:
            for ret in return_fares_by_dest.get(out.destination, []):
                stay = (ret.dep_time.date() - out.dep_time.date()).days
                if min_days <= stay <= max_days:
                    round_trips.append(RoundTripFare(outbound=out, inbound=ret))

        logger.info(f"Computed {len(round_trips)} round-trip fares.")
        return round_trips

    # --- Google Flights internals ---

    async def _search_day(
        self,
        origins: List[str],
        destinations: List[str],
        date_str: str,
        airlines: Optional[List[str]] = None,
        max_stops: GFMaxStops = GFMaxStops.NON_STOP,
        max_price: Optional[int] = None,
        time_restrictions: Optional[list] = None,
        max_flight_duration: Optional[int] = None,
        layover_airports: Optional[list] = None,
        max_layover_duration: Optional[int] = None,
    ) -> List[OneWayFare]:
        """Searches Google Flights for a single day and returns parsed OneWayFare objects."""
        query_params = {
            "f.sid": self.GF_F_SID,
            "bl": self.GF_BL,
            "hl": self.GF_HL,
            "gl": self.GF_GL,
            "soc-app": self.GF_SOC_APP,
            "soc-platform": self.GF_SOC_PLATFORM,
            "soc-device": self.GF_SOC_DEVICE,
            "_reqid": str(int(time_module.time() * 1000) % 1000000),
            "rt": self.GF_RT,
        }

        form_data = self._build_gf_payload(
            origins=origins,
            destinations=destinations,
            date_str=date_str,
            airlines=airlines,
            max_stops=max_stops,
            max_price=max_price,
            time_restrictions=time_restrictions,
            max_flight_duration=max_flight_duration,
            layover_airports=layover_airports,
            max_layover_duration=max_layover_duration,
        )

        for attempt in range(3):
            async with await self.post(
                self.GF_URL,
                params=query_params,
                data=form_data,
                cookies=self.GF_COOKIES,
            ) as response:
                if response.status == 200:
                    text = await response.text()
                    return self._parse_gf_response(text, date_str)
                elif response.status == 429:
                    wait = (attempt + 1) * 2
                    logger.warning(f"Rate limited for {date_str}, retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                else:
                    logger.error(f"Error {response.status} for {date_str}")
                    break
        return []

    @classmethod
    def _build_gf_payload(
        cls,
        origins: List[str],
        destinations: List[str],
        date_str: str,
        airlines: Optional[List[str]] = None,
        max_stops: GFMaxStops = GFMaxStops.NON_STOP,
        adults: int = 1,
        children: int = 0,
        infants_in_seat: int = 0,
        infants_on_lap: int = 0,
        trip_type: GFTripType = GFTripType.ONE_WAY,
        seat_class: GFSeatClass = GFSeatClass.ECONOMY,
        max_price: Optional[int] = None,
        time_restrictions: Optional[list] = None,
        max_flight_duration: Optional[int] = None,
        layover_airports: Optional[list] = None,
        max_layover_duration: Optional[int] = None,
    ) -> dict:
        """Builds the Google Flights RPC form-encoded payload using GFFlightRequest."""
        
        request_obj = GFFlightRequest(
            origins=origins,
            destinations=destinations,
            date=date_str,
            adults=adults,
            children=children,
            infants_in_seat=infants_in_seat,
            infants_on_lap=infants_on_lap,
            trip_type=trip_type,
            seat_class=seat_class,
            max_price=max_price,
            time_restrictions=time_restrictions,
            max_stops=max_stops,
            airlines=airlines,
            max_flight_duration=max_flight_duration,
            layover_airports=layover_airports,
            max_layover_duration=max_layover_duration,
            sort_by=GFSortBy.PRICE,
        )

        inner_req = request_obj.encode()

        return {
            "f.req": json.dumps([None, json.dumps(inner_req)]),
            "at": cls.GF_AT_TOKEN,
        }

    @staticmethod
    def _parse_gf_response(text: str, date_str: str) -> List[OneWayFare]:
        """Parses a Google Flights RPC response into OneWayFare objects."""
        if text.startswith(")]}'"):
            text = text[4:].strip()

        fares: List[OneWayFare] = []
        for chunk in text.split("\n"):
            if "wrb.fr" not in chunk:
                continue

            try:
                data = json.loads(chunk)
            except json.JSONDecodeError:
                continue

            if not (isinstance(data, list) and len(data) > 0 and data[0][0] == "wrb.fr"):
                continue

            try:
                if data[0][2] is None:
                    continue
                inner_data = json.loads(data[0][2])
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

            if not inner_data:
                continue

            # Parse both best (2) and other (3) flights
            flights_results = [
                item
                for i in [2, 3]
                if len(inner_data) > i and isinstance(inner_data[i], list) and len(inner_data[i]) > 0
                for item in inner_data[i][0]
            ]

            for flight in flights_results:
                try:
                    flight_data = flight[0]
                    price_data = flight[1]

                    price = 0.0
                    try:
                        if price_data and price_data[0]:
                            price = price_data[0][-1]
                    except (IndexError, TypeError):
                        pass

                    for segment in flight_data[2]:
                        dep_iata = segment[3]
                        arr_iata = segment[6]

                        # Safe time parsing: handle [hour] vs [hour, minute] and None
                        dep_h = segment[8][0] if segment[8][0] is not None else 0
                        dep_m = (segment[8][1] if len(segment[8]) > 1 else 0) or 0
                        arr_h = segment[10][0] if segment[10][0] is not None else 0
                        arr_m = (segment[10][1] if len(segment[10]) > 1 else 0) or 0

                        flight_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        dep_dt = datetime(
                            flight_date.year, flight_date.month, flight_date.day,
                            dep_h, dep_m,
                        )

                        # Handle overnight flights
                        if (arr_h, arr_m) < (dep_h, dep_m):
                            arr_date = flight_date + timedelta(days=1)
                        else:
                            arr_date = flight_date
                        
                        arr_dt = datetime(
                            arr_date.year, arr_date.month, arr_date.day,
                            arr_h, arr_m,
                        )

                        # Operating carrier is typically at index 22
                        operating_carrier_code = segment[22][0]
                        operating_flight_num = (
                            int(segment[22][1]) if segment[22][1] is not None else 0
                        )

                        # By default, marketing is same as operating
                        marketing_carrier_code = operating_carrier_code
                        marketing_flight_num = operating_flight_num

                        # Check for codeshare marketing carrier at index 15
                        if len(segment) > 15 and segment[15] and len(segment[15]) > 0:
                            marketing_carrier_code = segment[15][0][0]
                            try:
                                marketing_flight_num = (
                                    int(segment[15][0][1]) if segment[15][0][1] is not None else 0
                                )
                            except (ValueError, TypeError):
                                marketing_flight_num = 0

                        fares.append(
                            OneWayFare(
                                dep_time=dep_dt,
                                arr_time=arr_dt,
                                origin=dep_iata,
                                destination=arr_iata,
                                fare=price,
                                currency="USD",
                                operating_flight_number=operating_flight_num,
                                marketing_flight_number=marketing_flight_num,
                                operating_carrier=operating_carrier_code,
                                marketing_carrier=marketing_carrier_code,
                            )
                        )

                except (IndexError, TypeError, KeyError, ValueError, ValidationError) as e:
                    logger.warning(
                        f"Failed to parse Google Flights entry for {date_str}: {e}"
                    )
                    continue

        return fares
