import json
import logging
import re
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import ValidationError

from ...base.config import ScraperSettings, settings
from ...base.scrapers.base_scraper import BaseScraper
from ...base.types import Airport, OneWayFare, RoundTripFare
from .calendar_parse import (
    CalendarPricesResponse,
    CalendarRoutesResponse,
    parse_calendar_price_item,
)
from .constants import DEFAULT_SEED_AIRPORTS, is_plausible_iata

logger = logging.getLogger("scraper.vueling")

ROUTES_PATH = "/api/Routes/GetRoutesWithPriceByOrigin"

_IATA_KEY_HINTS = frozenset(
    {
        "iatacode",
        "stationcode",
        "airportcode",
        "originiata",
        "destinationiata",
        "arrivalstation",
        "departurestation",
        "originstation",
        "destinationstation",
    }
)

_DATE_LIST_KEYS = frozenset(
    {
        "availableoutbounddates",
        "availabledates",
        "discountdates",
        "flightdates",
        "dates",
        "outbounddates",
        "inbounddates",
    }
)


def _route_leg_matches(tag: str, origin: str, destination: str) -> bool:
    """``VY;BCNMAD`` style tags from FlightCalendarRoutes."""
    origin, destination = origin.upper(), destination.upper()
    if ";" not in tag:
        return False
    _, r6 = tag.split(";", 1)
    r6 = r6.strip().upper()
    if len(r6) != 6 or not r6.isalpha():
        return False
    return r6[:3] == origin and r6[3:] == destination


def _parse_iso_date_list(values: Any) -> Set[str]:
    out: Set[str] = set()
    if not isinstance(values, list):
        return out
    for v in values:
        if isinstance(v, str):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})", v.strip())
            if m:
                out.add(m.group(1))
        elif isinstance(v, (int, float)):
            continue
    return out


class VuelingScraper(BaseScraper):
    """
    Vueling (VY) scraper backed by the public ``apiwww`` routes feed and the
    documented FlightCalendar JSON APIs (prices / routes) when a partner bearer
    token is configured.

    The consumer ``GetRoutesWithPriceByOrigin`` endpoint is used to discover the
    network graph (airports and destinations). Calendar calls follow Vueling's
    published FlightCalendar message structure (see developer portal).
    """

    CARRIER = "VY"

    def __init__(self, config: ScraperSettings = settings):
        self._culture = config.vueling_culture
        self._currency = config.vueling_currency
        self._product_class = config.vueling_product_class.upper()
        self._bearer = (config.vueling_bearer_token or "").strip() or None
        self._calendar_prices_path = config.vueling_calendar_prices_path
        self._calendar_routes_path = config.vueling_calendar_routes_path
        seeds = [s.strip().upper() for s in config.vueling_seed_airports if s.strip()]
        self._seed_airports: Tuple[str, ...] = tuple(seeds) if seeds else DEFAULT_SEED_AIRPORTS

        extra_headers: Dict[str, str] = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.vueling.com",
            "Referer": "https://www.vueling.com/en",
            "Accept-Language": f"{self._culture},en;q=0.9",
        }

        super().__init__(
            config=config,
            base_url="https://apiwww.vueling.com",
            warm_up_url="https://www.vueling.com/en",
            default_headers=extra_headers,
        )

    def _routes_params(self, origin: str) -> Dict[str, str]:
        return {
            "origin": origin.upper(),
            "culture": self._culture,
            "currency": self._currency,
        }

    def _calendar_auth_headers(self) -> Dict[str, str]:
        if not self._bearer:
            raise ValueError(
                "SCRAPER_VUELING_BEARER_TOKEN is required for FlightCalendar fare and "
                "some availability calls. Obtain a token via Vueling's partner API flow."
            )
        return {"Authorization": f"Bearer {self._bearer}"}

    async def _fetch_routes_json(self, origin: str) -> Any:
        params = self._routes_params(origin)
        async with await self.get(ROUTES_PATH, stateless=True, params=params) as res:
            text = await res.text()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Non-JSON routes payload for %s: %s", origin, text[:300])
            raise ValueError(f"Routes response for {origin} is not JSON: {e}") from e

    @staticmethod
    def _station_dict_to_airport(row: Dict[str, Any]) -> Optional[Airport]:
        code: Optional[str] = None
        for key in ("IataCode", "StationCode", "Code", "code"):
            raw = row.get(key)
            if isinstance(raw, str) and len(raw.strip()) == 3 and raw.strip().isalpha():
                code = raw.strip().upper()
                break
        if not code or not is_plausible_iata(code):
            return None

        lat = row.get("Latitude") or row.get("Lat") or row.get("latitude")
        lng = row.get("Longitude") or row.get("Long") or row.get("longitude") or row.get("lng")
        name = None
        for nk in ("Name", "FullName", "StationName", "Description"):
            n = row.get(nk)
            if isinstance(n, str) and n.strip():
                name = n.strip()
                break

        try:
            return Airport(
                iata_code=code,
                lat=float(lat) if lat is not None else None,
                lng=float(lng) if lng is not None else None,
                name=name,
            )
        except (TypeError, ValueError):
            return Airport(iata_code=code, name=name)

    def _parse_routes_payload(
        self, payload: Any, origin: str
    ) -> Tuple[Set[str], Dict[str, Airport], Set[str]]:
        """
        Returns ``(destinations, airports_meta_by_code, loose_dates_iso)``.
        """
        destinations: Set[str] = set()
        airports: Dict[str, Airport] = {}
        loose_dates: Set[str] = set()
        origin_u = origin.upper()

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                lk_map = {k.lower(): k for k in node}
                for dlk in _DATE_LIST_KEYS:
                    if dlk in lk_map:
                        loose_dates.update(_parse_iso_date_list(node[lk_map[dlk]]))

                for k, v in node.items():
                    kl = k.lower()
                    if kl in _IATA_KEY_HINTS and isinstance(v, str):
                        c = v.strip().upper()
                        if is_plausible_iata(c):
                            if c != origin_u:
                                destinations.add(c)
                            ap = self._station_dict_to_airport({"IataCode": c})
                            if ap:
                                airports.setdefault(c, ap)
                    if isinstance(v, dict) and kl.endswith("station"):
                        ap = self._station_dict_to_airport(v)
                        if ap:
                            airports.setdefault(ap.iata_code, ap)
                            if ap.iata_code != origin_u:
                                destinations.add(ap.iata_code)
                    if kl in _DATE_LIST_KEYS:
                        loose_dates.update(_parse_iso_date_list(v))

                    if isinstance(v, str) and ";" in v and len(v) <= 16:
                        parts = v.split(";")
                        if len(parts) == 2 and len(parts[1]) == 6 and parts[1].isalpha():
                            a, b = parts[1][:3].upper(), parts[1][3:].upper()
                            if is_plausible_iata(a) and is_plausible_iata(b):
                                if a == origin_u:
                                    destinations.add(b)
                                elif b == origin_u:
                                    destinations.add(a)

                    visit(v)

            elif isinstance(node, list):
                for x in node:
                    visit(x)

            elif isinstance(node, str):
                if ";" in node and len(node) <= 16:
                    parts = node.split(";")
                    if len(parts) == 2 and len(parts[1]) == 6 and parts[1].isalpha():
                        a, b = parts[1][:3].upper(), parts[1][3:].upper()
                        if is_plausible_iata(a) and is_plausible_iata(b):
                            if a == origin_u:
                                destinations.add(b)
                            elif b == origin_u:
                                destinations.add(a)

        visit(payload)

        destinations.discard(origin_u)
        destinations = {d for d in destinations if is_plausible_iata(d)}
        return destinations, airports, loose_dates

    async def update_active_airports(self) -> None:
        logger.info("Updating Vueling airports from route graph...")
        visited: Set[str] = set()
        queue: deque[str] = deque(self._seed_airports)
        merged: Dict[str, Airport] = {}

        expansions = 0
        max_expansions = min(500, max(80, 10 * len(self._seed_airports)))

        while queue and expansions < max_expansions:
            code = queue.popleft().upper()
            if code in visited or not is_plausible_iata(code):
                continue
            visited.add(code)
            expansions += 1

            try:
                payload = await self._fetch_routes_json(code)
            except Exception as e:
                logger.warning("Vueling routes request failed for %s: %s", code, e)
                continue

            dests, meta, _ = self._parse_routes_payload(payload, code)
            for iata, ap in meta.items():
                prev = merged.get(iata)
                if prev is None or (ap.name and not prev.name):
                    merged[iata] = ap
            for d in dests:
                merged.setdefault(d, Airport(iata_code=d))
                if d not in visited:
                    queue.append(d)

        for s in self._seed_airports:
            merged.setdefault(s.upper(), Airport(iata_code=s.upper()))

        self.active_airports = tuple(sorted(merged.values(), key=lambda a: a.iata_code))
        logger.info("Vueling active airports: %s.", len(self.active_airports))

    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        origin_u = origin.upper()
        try:
            payload = await self._fetch_routes_json(origin_u)
        except Exception as e:
            logger.warning("Vueling destinations fetch failed for %s: %s", origin_u, e)
            return tuple()

        dests, _, _ = self._parse_routes_payload(payload, origin_u)
        return tuple(sorted(dests))

    async def _dates_from_routes_matrix(
        self, origin: str, destination: str
    ) -> Set[str]:
        origin_u, dest_u = origin.upper(), destination.upper()
        try:
            payload = await self._fetch_routes_json(origin_u)
        except Exception:
            return set()

        _, _, loose = self._parse_routes_payload(payload, origin_u)
        blob = json.dumps(payload)
        if dest_u not in blob.upper():
            return set()
        return loose

    async def _dates_from_flight_calendar_routes(
        self, origin: str, destination: str
    ) -> Set[str]:
        headers = self._calendar_auth_headers()
        out: Set[str] = set()
        today = date.today()
        cursor = today
        end_scan = today + timedelta(days=365)

        while cursor <= end_scan:
            start_int = int(cursor.strftime("%Y%m%d"))
            params = {"startDate": str(start_int), "numDays": "31"}
            try:
                async with await self.get(
                    self._calendar_routes_path,
                    stateless=True,
                    params=params,
                    headers=headers,
                ) as res:
                    raw = await res.json()
            except Exception as e:
                logger.warning("FlightCalendarRoutes chunk failed at %s: %s", start_int, e)
                break

            try:
                parsed = CalendarRoutesResponse.model_validate(raw)
            except ValidationError as e:
                logger.warning("FlightCalendarRoutes parse error: %s", e)
                break

            if not parsed.IsSuccessful or not parsed.Result:
                break

            for day in parsed.Result:
                ymd = str(day.Date)
                if len(ymd) != 8:
                    continue
                try:
                    d_iso = datetime.strptime(ymd, "%Y%m%d").date().isoformat()
                except ValueError:
                    continue
                for tag in day.Routes:
                    if _route_leg_matches(tag, origin, destination):
                        out.add(d_iso)

            cursor += timedelta(days=31)

        return out

    async def get_available_dates(self, origin: str, destination: str) -> Tuple[str, ...]:
        origin_u, dest_u = origin.upper(), destination.upper()

        dates: Set[str] = set()
        dates.update(await self._dates_from_routes_matrix(origin_u, dest_u))

        if self._bearer:
            dates.update(await self._dates_from_flight_calendar_routes(origin_u, dest_u))

        return tuple(sorted(dates))

    def _item_to_one_way_for_destinations(
        self,
        item: str,
        expect_origin: str,
        dest_allow: Set[str],
    ) -> Optional[OneWayFare]:
        try:
            price, currency, segments = parse_calendar_price_item(item)
        except (ValueError, TypeError, IndexError) as e:
            logger.debug("Skip calendar item: %s (%s)", item[:120], e)
            return None

        if len(segments) != 1:
            return None

        seg = segments[0]
        if seg.carrier != self.CARRIER:
            return None
        if seg.origin != expect_origin or seg.destination not in dest_allow:
            return None

        fn = self.parse_flight_number(str(seg.flight_number), self.CARRIER)
        try:
            return OneWayFare(
                dep_time=seg.dep,
                arr_time=seg.arr,
                origin=expect_origin,
                destination=seg.destination,
                fare=float(price),
                currency=currency,
                left=seg.seats,
                operating_flight_number=fn,
                marketing_flight_number=fn,
                operating_carrier=self.CARRIER,
                marketing_carrier=self.CARRIER,
            )
        except (ValueError, ValidationError) as e:
            logger.debug("OneWayFare validation failed: %s", e)
            return None

    def _item_to_one_way(
        self,
        item: str,
        expect_origin: str,
        expect_dest: str,
    ) -> Optional[OneWayFare]:
        return self._item_to_one_way_for_destinations(item, expect_origin, {expect_dest})

    async def _calendar_price_chunk(
        self, start: date, num_days: int
    ) -> List[CalendarPricesResponse]:
        if num_days < 1:
            return []
        headers = self._calendar_auth_headers()
        params = {
            "startDate": start.strftime("%Y%m%d"),
            "numDays": str(min(31, num_days)),
            "productClass": self._product_class,
        }
        async with await self.get(
            self._calendar_prices_path,
            stateless=True,
            params=params,
            headers=headers,
        ) as res:
            raw = await res.json()
        try:
            return [CalendarPricesResponse.model_validate(raw)]
        except ValidationError as e:
            logger.warning("FlightCalendarPrices parse error: %s", e)
            return []

    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = [],
    ) -> List[OneWayFare]:
        if not self._bearer:
            logger.info("Vueling search_one_way_fares skipped: no SCRAPER_VUELING_BEARER_TOKEN.")
            return []

        if not to_date:
            to_date = from_date + timedelta(days=1)

        origin_u = origin.upper()
        if destinations:
            dest_list = [d.upper() for d in destinations]
        else:
            dest_list = list(await self.get_destination_codes(origin_u))

        if not dest_list:
            return []

        chunk_starts: List[date] = []
        cur = from_date
        while cur <= to_date:
            chunk_starts.append(cur)
            cur += timedelta(days=31)

        chunk_tasks = [self._calendar_price_chunk(s, 31) for s in chunk_starts]
        chunk_results = await self.run_concurrently(chunk_tasks)

        fares: List[OneWayFare] = []
        dest_allow = set(dest_list)
        for pack in chunk_results.results:
            if isinstance(pack, Exception):
                logger.warning("Calendar chunk failed: %s", pack)
                continue
            if not isinstance(pack, list):
                continue
            for parsed in pack:
                if not parsed.IsSuccessful or not parsed.Result:
                    continue
                for day in parsed.Result:
                    try:
                        day_d = datetime.strptime(str(day.FlightDate), "%Y%m%d").date()
                    except ValueError:
                        continue
                    if not (from_date <= day_d <= to_date):
                        continue
                    for item in day.Items:
                        ow = self._item_to_one_way_for_destinations(
                            item, origin_u, dest_allow
                        )
                        if ow:
                            fares.append(ow)

        logger.info("Vueling one-way %s: %s fares.", origin_u, len(fares))
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
        if not self._bearer:
            logger.info("Vueling search_round_trip_fares skipped: no SCRAPER_VUELING_BEARER_TOKEN.")
            return []

        if not to_date:
            to_date = from_date + timedelta(days=30)

        horizon_end = to_date + timedelta(days=max(365, max_days + 31))

        outbound = await self.search_one_way_fares(
            origin, from_date, to_date, destinations=destinations
        )
        if not outbound:
            return []

        dest_set = {ow.destination for ow in outbound}
        inbound_tasks = [
            self.search_one_way_fares(
                d, from_date, horizon_end, destinations=[origin.upper()]
            )
            for d in sorted(dest_set)
        ]
        inbound_pack = await self.run_concurrently(inbound_tasks)
        inbound_by_dest: Dict[str, List[OneWayFare]] = {}
        for dest, result in zip(sorted(dest_set), inbound_pack.results):
            if isinstance(result, Exception):
                logger.warning("Inbound search failed for %s: %s", dest, result)
                continue
            if isinstance(result, list):
                inbound_by_dest[dest] = result

        rt: List[RoundTripFare] = []
        for ow_out in outbound:
            dest = ow_out.destination
            outs_date = ow_out.dep_time.date()
            for ow_in in inbound_by_dest.get(dest, []):
                if ow_in.origin != dest or ow_in.destination != origin.upper():
                    continue
                in_date = ow_in.dep_time.date()
                if in_date < outs_date:
                    continue
                stay = (in_date - outs_date).days
                if min_days <= stay <= max_days:
                    try:
                        rt.append(RoundTripFare(outbound=ow_out, inbound=ow_in))
                    except ValidationError:
                        continue

        logger.info("Vueling round-trip %s: %s combinations.", origin.upper(), len(rt))
        return rt
