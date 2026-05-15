import logging
import re
import json
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ...base.scrapers.base_scraper import CurlCffiScraper
from ...base.types import Airport, OneWayFare, RoundTripFare
from ...base.config import settings, ScraperSettings
from .models import EasyJetAirport, EasyJetAvailabilityResponse, EasyJetFare

logger = logging.getLogger("scraper.easyjet")

class EasyJetScraper(CurlCffiScraper):
    MARKETING_CARRIER = "U2"
    BASE_URL = "https://www.easyjet.com"
    ROUTEMAP_URL = "/en/routemap"
    AVAILABILITY_URL = "/homepage/api/availability"
    FARES_URL = "/api/routepricing/v3/searchfares/GetAllFaresByDate"
    DEFAULT_CURRENCY = "EUR"
    MAX_FARES_CHUNK_DAYS = 7

    _ROUTEMAP_RE = re.compile(
        r"new\s+RouteMap\.RouteMap\((\{.*?\})\);\s*\}\);\s*\};", re.S
    )

    def __init__(self, config: ScraperSettings = settings, currency: str = "EUR"):
        super().__init__(
            config=config,
            base_url=self.BASE_URL,
            warm_up_url=self.BASE_URL + "/en",
            default_headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": self.BASE_URL + "/en",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty"
            }
        )
        self._currency = currency
        self._routes: Dict[str, Tuple[str, ...]] = {}

    async def update_active_airports(self) -> None:
        logger.info("Updating EasyJet active airports from routemap...")
        async with await self.get(self.ROUTEMAP_URL) as res:
            html = await res.text()

        m = self._ROUTEMAP_RE.search(html)
        if not m:
            logger.error("Could not find RouteMap JSON in HTML")
            self.active_airports = tuple()
            return

        try:
            data = json.loads(m.group(1))
            airports_data = data.get("airports", [])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse RouteMap JSON: {e}")
            self.active_airports = tuple()
            return

        airports: List[Airport] = []
        routes: Dict[str, Tuple[str, ...]] = {}

        for a_dict in airports_data:
            try:
                a = EasyJetAirport.model_validate(a_dict)
                routes[a.code] = tuple(a.dests)
                airports.append(
                    Airport(
                        iata_code=a.code,
                        lat=a.lat,
                        lng=a.long,
                        name=a.name
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to parse airport data: {e}")

        self._routes = routes
        self.active_airports = tuple(airports)
        logger.info(f"EasyJet active airports: {len(self.active_airports)}.")

    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        if not self._routes:
            await self.update_active_airports()
        return self._routes.get(origin.upper(), tuple())

    async def get_available_dates(self, origin: str, destination: str) -> Tuple[str, ...]:
        params = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "currency": self._currency,
            "isReturn": False,
            "startDate": date.today().isoformat(),
            "endDate": (date.today() + timedelta(days=330)).isoformat(),
            "isWorldwide": False
        }
        
        try:
            async with await self.get(self.AVAILABILITY_URL, params=params) as res:
                data = await res.json()
                resp = EasyJetAvailabilityResponse.model_validate(data)
                
                if not resp.departureFlights:
                    return tuple()
                    
                dates = [d.date.isoformat() for d in resp.departureFlights]
                return tuple(sorted(dates))
        except Exception as e:
            logger.warning(f"Failed to fetch available dates for {origin}-{destination}: {e}")
            return tuple()

    def _iter_date_chunks(self, from_date: date, to_date: date, max_days: int = 7):
        current = from_date
        while current <= to_date:
            chunk_to = min(current + timedelta(days=max_days - 1), to_date)
            yield current, chunk_to
            current = chunk_to + timedelta(days=1)

    async def _fetch_fares(
        self, origin: str, destination: str, dfrom: date, dto: date
    ) -> List[EasyJetFare]:
        params = {
            "departureAirport": origin.upper(),
            "arrivalAirport": destination.upper(),
            "currency": self._currency,
            "departureDateFrom": dfrom.isoformat(),
            "departureDateTo": dto.isoformat()
        }
        
        try:
            async with await self.get(self.FARES_URL, params=params) as res:
                data = await res.json()
                
                if not isinstance(data, list):
                    logger.warning(f"Unexpected fares response for {origin}-{destination}: {type(data)}")
                    return []
                    
                fares = []
                for f_dict in data:
                    try:
                        fares.append(EasyJetFare.model_validate(f_dict))
                    except Exception as e:
                        logger.warning(f"Failed to parse fare data: {e}")
                return fares
        except Exception as e:
            logger.warning(f"Failed to fetch fares for {origin}-{destination} ({dfrom} to {dto}): {e}")
            return []

    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = []
    ) -> List[OneWayFare]:
        if not self._routes:
            await self.update_active_airports()

        if not to_date:
            to_date = from_date + timedelta(days=1)

        if destinations:
            dest_list = [d for d in destinations if d in self._routes.get(origin.upper(), tuple())]
        else:
            dest_list = list(await self.get_destination_codes(origin))
            
        if not dest_list:
            return []

        tasks = []
        for dest in dest_list:
            for chunk_from, chunk_to in self._iter_date_chunks(from_date, to_date, self.MAX_FARES_CHUNK_DAYS):
                tasks.append(self._fetch_fares(origin, dest, chunk_from, chunk_to))

        results = await self.run_concurrently(tasks)

        fares: List[OneWayFare] = []
        for res in results.results:
            if isinstance(res, Exception) or not res:
                continue

            for fare in res:
                if fare.serviceError is not None:
                    continue
                    
                dep_d = fare.departureDateTime.date()
                if from_date <= dep_d <= to_date:
                    fn = self.parse_flight_number(fare.flightNumber, self.MARKETING_CARRIER)
                    
                    try:
                        fares.append(
                            OneWayFare(
                                dep_time=fare.departureDateTime,
                                arr_time=fare.arrivalDateTime,
                                origin=fare.departureAirport,
                                destination=fare.arrivalAirport,
                                fare=fare.outboundPrice,
                                currency=self._currency,
                                operating_flight_number=fn,
                                marketing_flight_number=fn,
                                operating_carrier=self.MARKETING_CARRIER,
                                marketing_carrier=self.MARKETING_CARRIER,
                            )
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create OneWayFare: {e}")

        logger.info(f"EasyJet one-way {origin}: {len(fares)} fares in {results.execution_time:.2f}s.")
        return fares

    async def search_round_trip_fares(
        self,
        origin: str,
        min_days: int,
        max_days: int,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = []
    ) -> List[RoundTripFare]:
        if not self._routes:
            await self.update_active_airports()

        if not to_date:
            to_date = from_date + timedelta(days=30)

        if destinations:
            dest_list = [d for d in destinations if d in self._routes.get(origin.upper(), tuple())]
        else:
            dest_list = list(await self.get_destination_codes(origin))
            
        if not dest_list:
            return []

        # Fetch outbound and inbound fares
        outbound_tasks = []
        inbound_tasks = []
        
        for dest in dest_list:
            for chunk_from, chunk_to in self._iter_date_chunks(from_date, to_date, self.MAX_FARES_CHUNK_DAYS):
                outbound_tasks.append(self._fetch_fares(origin, dest, chunk_from, chunk_to))
                
            # For inbound, we need to check if the reverse route exists
            if origin in self._routes.get(dest, tuple()):
                for chunk_from, chunk_to in self._iter_date_chunks(from_date, to_date, self.MAX_FARES_CHUNK_DAYS):
                    inbound_tasks.append(self._fetch_fares(dest, origin, chunk_from, chunk_to))

        outbound_results = await self.run_concurrently(outbound_tasks)
        inbound_results = await self.run_concurrently(inbound_tasks)

        outbound_fares: Dict[str, List[OneWayFare]] = {d: [] for d in dest_list}
        inbound_fares: Dict[str, List[OneWayFare]] = {d: [] for d in dest_list}

        # Process outbound
        for res in outbound_results.results:
            if isinstance(res, Exception) or not res:
                continue
            for fare in res:
                if fare.serviceError is not None:
                    continue
                dep_d = fare.departureDateTime.date()
                if from_date <= dep_d <= to_date:
                    fn = self.parse_flight_number(fare.flightNumber, self.MARKETING_CARRIER)
                    dest = fare.arrivalAirport
                    if dest in outbound_fares:
                        outbound_fares[dest].append(
                            OneWayFare(
                                dep_time=fare.departureDateTime,
                                arr_time=fare.arrivalDateTime,
                                origin=fare.departureAirport,
                                destination=fare.arrivalAirport,
                                fare=fare.outboundPrice,
                                currency=self._currency,
                                operating_flight_number=fn,
                                marketing_flight_number=fn,
                                operating_carrier=self.MARKETING_CARRIER,
                                marketing_carrier=self.MARKETING_CARRIER,
                            )
                        )

        # Process inbound
        for res in inbound_results.results:
            if isinstance(res, Exception) or not res:
                continue
            for fare in res:
                if fare.serviceError is not None:
                    continue
                dep_d = fare.departureDateTime.date()
                if from_date <= dep_d <= to_date:
                    fn = self.parse_flight_number(fare.flightNumber, self.MARKETING_CARRIER)
                    dest = fare.departureAirport # The origin of the inbound is the destination of the round trip
                    if dest in inbound_fares:
                        inbound_fares[dest].append(
                            OneWayFare(
                                dep_time=fare.departureDateTime,
                                arr_time=fare.arrivalDateTime,
                                origin=fare.departureAirport,
                                destination=fare.arrivalAirport,
                                fare=fare.outboundPrice, # We use outboundPrice of the inbound flight
                                currency=self._currency,
                                operating_flight_number=fn,
                                marketing_flight_number=fn,
                                operating_carrier=self.MARKETING_CARRIER,
                                marketing_carrier=self.MARKETING_CARRIER,
                            )
                        )

        round_trips: List[RoundTripFare] = []
        for dest in dest_list:
            out_list = outbound_fares[dest]
            in_list = inbound_fares[dest]
            
            for out_f in out_list:
                out_d = out_f.dep_time.date()
                for in_f in in_list:
                    in_d = in_f.dep_time.date()
                    stay = (in_d - out_d).days
                    if min_days <= stay <= max_days:
                        round_trips.append(RoundTripFare(outbound=out_f, inbound=in_f))

        logger.info(f"EasyJet round-trip {origin}: {len(round_trips)} combinations.")
        return round_trips
