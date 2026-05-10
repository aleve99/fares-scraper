import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import ValidationError

from ...base.scrapers.base_scraper import BaseScraper
from ...base.config import ScraperSettings, settings
from ...base.types import Airport, OneWayFare, RoundTripFare
from .models import (
    collect_iso_dates_from_tree,
    extract_bearer_token,
    fc_success_payload,
    parse_fc_item_line,
    parse_market_destinations,
    parse_route_dates,
)

logger = logging.getLogger("scraper.vueling")


class VuelingScraper(BaseScraper):
    """
    Vueling fares via public JSON APIs used by vueling.com / tickets.vueling.com:

    - ``ams.vueling.com/asm/v1/Auth`` + Bearer for ``res/v1/Markets/ByOrigin/{origin}``.
    - ``apiw.vueling.com/api/v1/bestPrices`` (homepage widget; captured in urlscan).
    - ``apiw.vueling.com`` Flight Calendar REST paths (defaults align with developer FlightCalendar docs).

    Paths default to ``/api/v1/flightCalendarRoutes`` and ``/api/v1/flightCalendarPrices``;
    override via ``SCRAPER_VUELING_ROUTES_PATH`` / ``SCRAPER_VUELING_PRICES_PATH`` if Vueling renames them.
    """

    OPERATING_CARRIER = "VY"

    def __init__(self, config: ScraperSettings = settings):
        super().__init__(
            config=config,
            base_url=None,
            warm_up_url="https://www.vueling.com/en",
            default_headers={
                "Accept": "application/json",
                "Origin": "https://www.vueling.com",
                "Referer": "https://www.vueling.com/",
            },
        )
        self._ams_base = config.vueling_ams_base.rstrip("/")
        self._apiw_base = config.vueling_apiw_base.rstrip("/")
        self._profile_id = config.vueling_profile_id
        self._culture = config.vueling_culture
        self._routes_path = config.vueling_routes_path
        self._prices_path = config.vueling_prices_path
        self._seeds = tuple(
            x.strip().upper()
            for x in config.vueling_seed_origins.split(",")
            if x.strip()
        )

        self._bearer: Optional[str] = None
        self._auth_lock = asyncio.Lock()
        self._market_cache: Dict[str, Tuple[str, ...]] = {}

    # --- AMS auth ---

    async def _ensure_bearer(self) -> str:
        async with self._auth_lock:
            if self._bearer:
                return self._bearer

            url = f"{self._ams_base}/asm/v1/Auth"
            payload = {"profileId": self._profile_id}
            async with await self.post(url, json=payload) as res:
                data = await res.json()

            token = extract_bearer_token(data)
            if not token:
                logger.error(
                    "AMS Auth returned no bearer token (keys: %s)",
                    list(data.keys()) if isinstance(data, dict) else type(data),
                )
                raise ValueError("Vueling AMS Auth did not return a bearer token")

            self._bearer = token
            return self._bearer

    def _authorized_headers(self) -> Dict[str, str]:
        if not self._bearer:
            raise RuntimeError("Bearer token missing; call _ensure_bearer first.")
        return {"Authorization": f"Bearer {self._bearer}"}

    async def _authorized_get(self, url: str, params: Optional[Dict[str, Any]] = None):
        await self._ensure_bearer()
        return await self.get(url, params=params, headers=self._authorized_headers())

    # --- Markets (destinations + airport discovery) ---

    async def _markets_payload(self, origin: str) -> Any:
        origin = origin.upper()
        url = f"{self._ams_base}/res/v1/Markets/ByOrigin/{origin}"
        async with await self._authorized_get(url) as res:
            return await res.json()

    async def _destinations_for_origin(self, origin: str) -> Tuple[str, ...]:
        origin = origin.upper()
        if origin in self._market_cache:
            return self._market_cache[origin]

        raw = await self._markets_payload(origin)
        codes = parse_market_destinations(raw)
        self._market_cache[origin] = codes
        return codes

    # --- apiw Flight Calendar + bestPrices ---

    def _fc_params(self, start: date, end: date, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        num_days = (end - start).days + 1
        num_days = max(1, min(num_days, 31))
        p: Dict[str, Any] = {
            "startDate": start.strftime("%Y%m%d"),
            "numDays": num_days,
            "culture": self._culture,
        }
        if extra:
            p.update(extra)
        return p

    async def _flight_calendar_routes(
        self, start: date, end: date
    ) -> Tuple[bool, Any]:
        url = f"{self._apiw_base}{self._routes_path}"
        params = self._fc_params(start, end)
        await self._ensure_bearer()
        try:
            async with await self._authorized_get(url, params=params) as res:
                payload = await res.json()
        except Exception as e:
            logger.warning("flightCalendarRoutes request failed: %s", e)
            return False, None

        if not isinstance(payload, dict):
            return False, None
        ok, result = fc_success_payload(payload)
        return ok, result

    async def _flight_calendar_prices(
        self,
        start: date,
        end: date,
        *,
        product_class: str = "BA",
    ) -> Tuple[bool, Any]:
        url = f"{self._apiw_base}{self._prices_path}"
        params = self._fc_params(start, end, {"productClass": product_class})
        await self._ensure_bearer()
        try:
            async with await self._authorized_get(url, params=params) as res:
                payload = await res.json()
        except Exception as e:
            logger.warning("flightCalendarPrices request failed: %s", e)
            return False, None

        if not isinstance(payload, dict):
            return False, None
        ok, result = fc_success_payload(payload)
        return ok, result

    async def _best_prices_raw(
        self,
        origin: str,
        destinations: Iterable[str],
        *,
        months: int = 12,
        start: Optional[date] = None,
        currency: str = "EUR",
    ) -> Any:
        dest_list = sorted({d.upper() for d in destinations})
        if not dest_list:
            return None

        start = start or date.today()
        url = f"{self._apiw_base}/api/v1/bestPrices"
        params = {
            "originCode": origin.upper(),
            "destinationCodes": ",".join(dest_list),
            "months": months,
            "startDate": start.isoformat(),
            "currencyCode": currency,
        }
        await self._ensure_bearer()
        async with await self._authorized_get(url, params=params) as res:
            return await res.json()

    @staticmethod
    def _chunks_between(from_d: date, to_d: date) -> List[Tuple[date, date]]:
        chunks: List[Tuple[date, date]] = []
        cur = from_d
        while cur <= to_d:
            end = min(cur + timedelta(days=30), to_d)
            chunks.append((cur, end))
            cur = end + timedelta(days=1)
        return chunks

    async def update_active_airports(self) -> None:
        logger.info("Updating Vueling active airports via AMS Markets BFS...")
        seeds = self._seeds if self._seeds else ("BCN", "MAD")

        airports: Set[str] = set(seeds)
        visited: Set[str] = set()
        queue: List[str] = list(seeds)

        while queue:
            origin = queue.pop(0)
            if origin in visited:
                continue
            visited.add(origin)

            try:
                dests = await self._destinations_for_origin(origin)
            except Exception as e:
                logger.warning("Markets fetch failed for %s: %s", origin, e)
                continue

            for d in dests:
                airports.add(d)
                if d not in visited:
                    queue.append(d)

        self.active_airports = tuple(Airport(iata_code=c) for c in sorted(airports))
        logger.info("Vueling active airports: %s.", len(self.active_airports))

    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        return await self._destinations_for_origin(origin)

    async def get_available_dates(self, origin: str, destination: str) -> Tuple[str, ...]:
        origin_u, dest_u = origin.upper(), destination.upper()

        try:
            raw = await self._best_prices_raw(
                origin_u, [dest_u], months=12, start=date.today()
            )
            dates = collect_iso_dates_from_tree(raw)
            if dates:
                return tuple(dates)
        except Exception as e:
            logger.debug("bestPrices path for calendar failed: %s", e)

        collected: Set[str] = set()
        today = date.today()
        horizon_end = today + timedelta(days=365)
        for start, end in self._chunks_between(today, horizon_end):
            ok, rows = await self._flight_calendar_routes(start, end)
            if not ok or rows is None:
                continue
            collected.update(parse_route_dates(rows, origin_u, dest_u))

        return tuple(sorted(collected))

    def _rows_to_one_way(
        self,
        rows: Any,
        origin: str,
        destination: str,
        from_date: date,
        to_date: date,
    ) -> List[OneWayFare]:
        fares: List[OneWayFare] = []
        if not isinstance(rows, list):
            return fares

        origin_u, dest_u = origin.upper(), destination.upper()

        for row in rows:
            if not isinstance(row, dict):
                continue
            items = row.get("Items") or row.get("items") or []
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, str):
                    continue
                if "~" not in item:
                    continue
                body = item.split("~", 1)[1]
                if "^" in body:
                    continue

                parsed = parse_fc_item_line(
                    item, expected_origin=origin_u, expected_dest=dest_u
                )
                if not parsed:
                    continue
                dep, arr, carrier, fn, fare, currency, seats = parsed
                if carrier != self.OPERATING_CARRIER:
                    continue

                dep_d = dep.date()
                if not (from_date <= dep_d <= to_date):
                    continue

                raw_fn = f"{carrier}{fn}"
                try:
                    fares.append(
                        OneWayFare(
                            dep_time=dep,
                            arr_time=arr,
                            origin=origin_u,
                            destination=dest_u,
                            fare=fare,
                            currency=currency,
                            left=seats,
                            operating_flight_number=self.parse_flight_number(
                                raw_fn, carrier
                            ),
                            marketing_flight_number=self.parse_flight_number(
                                raw_fn, carrier
                            ),
                            operating_carrier=carrier,
                            marketing_carrier=carrier,
                        )
                    )
                except (ValueError, ValidationError) as e:
                    logger.debug("Skip fare row: %s", e)
                    continue

        return fares

    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = [],
    ) -> List[OneWayFare]:
        if not to_date:
            to_date = from_date + timedelta(days=30)

        dest_list = (
            [d.upper() for d in destinations]
            if destinations
            else list(await self.get_destination_codes(origin))
        )
        if not dest_list:
            return []

        route_windows = self._chunks_between(from_date, to_date)
        tasks = [
            self._flight_calendar_prices(win_start, win_end)
            for win_start, win_end in route_windows
        ]

        cr = await self.run_concurrently(tasks)

        fares: List[OneWayFare] = []
        for chunk in cr.results:
            if isinstance(chunk, Exception):
                logger.warning("flightCalendarPrices chunk failed: %s", chunk)

        for dest in dest_list:
            for chunk in cr.results:
                if isinstance(chunk, Exception):
                    continue
                ok, rows = chunk
                if not ok or rows is None:
                    continue
                fares.extend(
                    self._rows_to_one_way(rows, origin, dest, from_date, to_date)
                )

        logger.info(
            "Vueling one-way %s: %s fares in %.2fs.",
            origin,
            len(fares),
            cr.execution_time,
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
        if not to_date:
            to_date = from_date + timedelta(days=90)

        dest_list = (
            [d.upper() for d in destinations]
            if destinations
            else list(await self.get_destination_codes(origin))
        )
        if not dest_list:
            return []

        route_windows = self._chunks_between(from_date, to_date)
        tasks = [
            self._flight_calendar_prices(win_start, win_end)
            for win_start, win_end in route_windows
        ]

        cr = await self.run_concurrently(tasks)

        outbound_by_dest: Dict[str, List[OneWayFare]] = {d: [] for d in dest_list}
        inbound_by_dest: Dict[str, List[OneWayFare]] = {d: [] for d in dest_list}

        for dest in dest_list:
            for chunk in cr.results:
                if isinstance(chunk, Exception):
                    continue
                ok, rows = chunk
                if not ok or rows is None:
                    continue
                outbound_by_dest[dest].extend(
                    self._rows_to_one_way(rows, origin, dest, from_date, to_date)
                )
                inbound_by_dest[dest].extend(
                    self._rows_to_one_way(rows, dest, origin, from_date, to_date)
                )

        rt: List[RoundTripFare] = []
        for dest in dest_list:
            for ow in outbound_by_dest[dest]:
                out_day = ow.dep_time.date()
                for iw in inbound_by_dest[dest]:
                    in_day = iw.dep_time.date()
                    if in_day <= out_day:
                        continue
                    stay = (in_day - out_day).days
                    if min_days <= stay <= max_days:
                        rt.append(RoundTripFare(outbound=ow, inbound=iw))

        logger.info("Vueling round-trip %s: %s combinations.", origin, len(rt))
        return rt
