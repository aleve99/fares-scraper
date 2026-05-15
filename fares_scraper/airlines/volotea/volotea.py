import logging
import aiohttp
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from pydantic import ValidationError

from ...base.scrapers.base_scraper import AiohttpScraper
from ...base.types import Airport, OneWayFare, RoundTripFare
from ...base.config import settings, ScraperSettings
from .models import VoloteaScheduleFlight, parse_schedule_payload

logger = logging.getLogger("scraper.volotea")

_JSON_CDN_DIST = "https://json.volotea.com/dist"
STATIONS_URL = f"{_JSON_CDN_DIST}/stations/stations.json"


class VoloteaScraper(AiohttpScraper):
    OPERATING_CARRIER = "V7"
    JSON_CDN_DIST = _JSON_CDN_DIST

    @classmethod
    def _schedule_url(cls, origin: str, destination: str) -> str:
        """Static filename uses sorted IATA codes; JSON inside still keys each direction (O-D)."""
        a, b = sorted([origin.upper(), destination.upper()])
        return f"{cls.JSON_CDN_DIST}/schedule/{a}-{b}_schedule.json"

    @classmethod
    def _parse_schedule_datetime(cls, raw: str) -> datetime:
        return VoloteaScheduleFlight.parse_schedule_datetime(raw)

    def __init__(self, config: ScraperSettings = settings):
        super().__init__(
            config=config,
            base_url="https://json.volotea.com",
            warm_up_url="https://www.volotea.com",
        )
        self._stations: Dict[str, Any] = {}
        self._enabled_codes: frozenset = frozenset()

    async def _get_json_or_404(self, url: str) -> Optional[Any]:
        """Single GET without BaseScraper retry loop; returns None on 404."""
        session = await self.sm.get_session(stateless=True)
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        proxy = self.sm.get_next_proxy()

        try:
            async with session.get(url, timeout=timeout, proxy=proxy) as response:
                if response.status == 404:
                    return None

                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def _load_stations(self) -> Dict[str, Any]:
        if self._stations:
            return self._stations

        async with await self.get(STATIONS_URL, stateless=True) as res:
            data = await res.json()

        if not isinstance(data, dict):
            raise ValueError("stations.json must be a JSON object")

        self._stations = data
        self._enabled_codes = frozenset(
            code
            for code, row in data.items()
            if isinstance(row, dict) and row.get("Enabled")
        )

        return self._stations

    def _is_direct_market(self, origin: str, dest: str) -> bool:
        """Enabled direct market operated by Volotea (Markets.OperatingCarrier == V7)."""
        origin_u, dest_u = origin.upper(), dest.upper()
        if origin_u == dest_u:
            return False

        row = self._stations.get(origin_u)
        if not isinstance(row, dict):
            return False

        markets = row.get("Markets")
        if not isinstance(markets, dict):
            return False

        mrow = None
        for k, v in markets.items():
            if k.upper() == dest_u:
                mrow = v
                break

        if not isinstance(mrow, dict) or not mrow.get("Enabled"):
            return False
        if dest_u not in self._enabled_codes:
            return False
        if dest_u not in self._stations:
            return False

        if mrow.get("IsConnectionMarket", False):
            return False

        # Stations Markets use OperatingCarrier (V7 = Volotea metal); exclude codeshares e.g. A3.
        if mrow.get("OperatingCarrier") != self.OPERATING_CARRIER:
            return False

        return True

    async def update_active_airports(self) -> None:
        logger.info("Updating Volotea active airports from stations.json...")
        data = await self._load_stations()

        airports: List[Airport] = []
        for code in sorted(self._enabled_codes):
            row = data.get(code)
            if not isinstance(row, dict):
                continue

            culture = row.get("Culture")
            name = None
            if isinstance(culture, dict):
                en = culture.get("en-US")
                if isinstance(en, dict):
                    n = en.get("Name") or en.get("FullName")
                    name = str(n) if n else None

            lat = row.get("Lat")
            lng = row.get("Long")

            airports.append(
                Airport(
                    iata_code=code,
                    lat=float(lat) if lat is not None else None,
                    lng=float(lng) if lng is not None else None,
                    name=name,
                )
            )

        self.active_airports = tuple(airports)
        logger.info(f"Volotea active airports: {len(self.active_airports)}.")

    async def get_destination_codes(self, origin: str) -> tuple[str, ...]:
        await self._load_stations()
        origin = origin.upper()

        if origin not in self._stations:
            return tuple()

        row = self._stations[origin]
        if not isinstance(row, dict):
            return tuple()

        markets = row.get("Markets")
        if not isinstance(markets, dict):
            return tuple()

        dests: List[str] = []
        for dest_code_raw in markets:
            dest_code = dest_code_raw.upper()
            if self._is_direct_market(origin, dest_code):
                dests.append(dest_code)

        return tuple(sorted(set(dests)))

    async def _fetch_schedule(
        self, origin: str, destination: str
    ) -> Optional[Dict[str, List[VoloteaScheduleFlight]]]:
        url = self._schedule_url(origin, destination)
        raw = await self._get_json_or_404(url)

        if raw is None or not isinstance(raw, dict):
            return None

        return parse_schedule_payload(raw)

    def _leg_key(self, origin: str, destination: str) -> str:
        return f"{origin.upper()}-{destination.upper()}"

    async def get_available_dates(self, origin: str, destination: str) -> tuple[str, ...]:
        await self._load_stations()
        origin, destination = origin.upper(), destination.upper()

        sched = await self._fetch_schedule(origin, destination)
        if not sched:
            return tuple()

        key = self._leg_key(origin, destination)
        flights = sched.get(key)
        if not flights:
            return tuple()

        dates_set = set()
        for f in flights:
            if f.is_connection_itinerary():
                continue
            if (f.CarrierCode or "").strip() != self.OPERATING_CARRIER:
                continue
            try:
                dt = self._parse_schedule_datetime(f.Departure)
                dates_set.add(dt.date().isoformat())
            except (ValueError, TypeError):
                continue

        return tuple(sorted(dates_set))

    def _flight_to_one_way(
        self,
        flight: VoloteaScheduleFlight,
        origin: str,
        destination: str,
    ) -> Optional[OneWayFare]:
        try:
            dep = self._parse_schedule_datetime(flight.Departure)
            arr = self._parse_schedule_datetime(flight.Arrival)
        except (ValueError, TypeError):
            return None

        if (flight.CarrierCode or "").strip() != self.OPERATING_CARRIER:
            return None

        if flight.is_connection_itinerary():
            return None

        priced = flight.price()
        if priced is None:
            return None
        fare, currency = priced
        carrier = flight.CarrierCode or self.OPERATING_CARRIER
        raw_fn = f"{carrier}{flight.FlightNumber}".replace(" ", "")
        fn = self.parse_flight_number(raw_fn, carrier)
        seats = flight.AvailableSeats if flight.AvailableSeats >= 0 else -1

        try:
            return OneWayFare(
                dep_time=dep,
                arr_time=arr,
                origin=origin.upper(),
                destination=destination.upper(),
                fare=fare,
                currency=currency,
                left=seats,
                operating_flight_number=fn,
                marketing_flight_number=fn,
                operating_carrier=carrier,
                marketing_carrier=carrier,
            )
        except (ValueError, ValidationError):
            logger.warning(f"Skipping fare {origin}-{destination} at {dep}: missing flight identification.")
            return None

    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = [],
    ) -> List[OneWayFare]:
        await self._load_stations()

        if not to_date:
            to_date = from_date + timedelta(days=1)

        if destinations:
            dest_list = [d for d in destinations if self._is_direct_market(origin, d)]
        else:
            dest_list = list(await self.get_destination_codes(origin))
        if not dest_list:
            return []

        tasks = [self._fetch_schedule(origin, d) for d in dest_list]
        results = await self.run_concurrently(tasks)

        fares: List[OneWayFare] = []
        for dest, sched in zip(dest_list, results.results):
            if isinstance(sched, Exception) or sched is None:
                if isinstance(sched, Exception):
                    logger.warning(f"Schedule fetch failed for {origin}-{dest}: {sched}")
                continue

            key = self._leg_key(origin, dest)
            flights = sched.get(key)
            if not flights:
                continue

            for flight in flights:
                try:
                    dep_dt = self._parse_schedule_datetime(flight.Departure)
                except (ValueError, TypeError):
                    continue

                dep_d = dep_dt.date()
                if from_date <= dep_d <= to_date:
                    ow = self._flight_to_one_way(flight, origin, dest)
                    if ow:
                        fares.append(ow)

        logger.info(
            f"Volotea one-way {origin}: {len(fares)} fares in {results.execution_time:.2f}s."
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
        await self._load_stations()

        if not to_date:
            to_date = from_date + timedelta(days=30)

        if destinations:
            dest_list = [d for d in destinations if self._is_direct_market(origin, d)]
        else:
            dest_list = list(await self.get_destination_codes(origin))
        if not dest_list:
            return []

        tasks = [self._fetch_schedule(origin, d) for d in dest_list]
        results = await self.run_concurrently(tasks)

        round_trips: List[RoundTripFare] = []
        for dest, sched in zip(dest_list, results.results):
            if isinstance(sched, Exception) or sched is None:
                if isinstance(sched, Exception):
                    logger.warning(f"Schedule fetch failed for {origin}-{dest}: {sched}")
                continue

            out_key = self._leg_key(origin, dest)
            in_key = self._leg_key(dest, origin)

            outbound = sched.get(out_key) or []
            inbound = sched.get(in_key) or []
            if not outbound or not inbound:
                continue

            for out_f in outbound:
                try:
                    out_dep = self._parse_schedule_datetime(out_f.Departure)
                except (ValueError, TypeError):
                    continue

                out_d = out_dep.date()
                if not (from_date <= out_d <= to_date):
                    continue

                for in_f in inbound:
                    try:
                        in_dep = self._parse_schedule_datetime(in_f.Departure)
                    except (ValueError, TypeError):
                        continue

                    in_d = in_dep.date()
                    if not (from_date <= in_d <= to_date):
                        continue

                    stay = (in_d - out_d).days
                    if min_days <= stay <= max_days:
                        out_ow = self._flight_to_one_way(out_f, origin, dest)
                        in_ow = self._flight_to_one_way(in_f, dest, origin)
                        if out_ow and in_ow:
                            round_trips.append(RoundTripFare(outbound=out_ow, inbound=in_ow))

        logger.info(f"Volotea round-trip {origin}: {len(round_trips)} combinations.")
        return round_trips
