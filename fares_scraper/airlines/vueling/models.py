"""
Parsers for Vueling Flight Calendar price lines (official developer docs:
FlightCalendar Message Structure + Deeplink).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

SEGMENT_DT_FMT = "%d/%m/%Y %H:%M:%S"


class FlightCalendarPriceRow(BaseModel):
    """One row from FlightCalendarPrices ``Result`` (PascalCase from .NET JSON)."""

    Carrier: str = ""
    Items: List[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "FlightCalendarPriceRow":
        items = row.get("Items") or row.get("items") or []
        if not isinstance(items, list):
            items = []
        carrier = row.get("Carrier") or row.get("carrier") or ""
        return cls(Carrier=str(carrier or ""), Items=[str(x) for x in items if x is not None])


def _split_fc_item(item: str) -> Tuple[List[str], List[str]]:
    if "~" not in item:
        return [], []
    gen, rest = item.split("~", 1)
    gen_parts = gen.split(";")
    first_seg = rest.split("^", 1)[0].split(";")
    return gen_parts, first_seg


def _segment_style(gen_parts: List[str], seg_parts: List[str]) -> str:
    """Heuristic: v2 segments have fare basis as last field; v1 ends with numeric next price."""
    if len(seg_parts) >= 10:
        return "v1"
    if len(seg_parts) >= 9 and seg_parts and re.match(r"^[A-Z0-9]{6,}$", seg_parts[-1]):
        return "v2"
    if len(gen_parts) >= 3 and gen_parts[2].replace(".", "").isdigit():
        # v2 trip price in general block (decimal)
        try:
            float(gen_parts[2])
            return "v2"
        except ValueError:
            pass
    return "v1"


def parse_fc_item_line(
    item: str,
    *,
    expected_origin: str,
    expected_dest: str,
) -> Optional[Tuple[datetime, datetime, str, int, float, str, int]]:
    """
    Parse a single Flight Calendar price item string into components for one direct segment.

    Returns:
        dep, arr, carrier, flight_number, fare, currency, seats_left (-1 if unknown)
    """
    gen_parts, seg_parts = _split_fc_item(item)
    if len(seg_parts) < 7:
        return None

    style = _segment_style(gen_parts, seg_parts)
    carrier = (seg_parts[0] or "").strip().upper()
    try:
        flight_number = int(str(seg_parts[1]).strip())
    except ValueError:
        return None

    dep_st = (seg_parts[2] or "").strip().upper()
    arr_st = (seg_parts[4] or "").strip().upper()
    if dep_st != expected_origin.upper() or arr_st != expected_dest.upper():
        return None

    try:
        dep = datetime.strptime(seg_parts[3].strip(), SEGMENT_DT_FMT)
        arr = datetime.strptime(seg_parts[5].strip(), SEGMENT_DT_FMT)
    except (ValueError, IndexError):
        return None

    currency = (gen_parts[0] or "EUR").strip().upper()

    if style == "v2":
        try:
            fare = float(gen_parts[2])
        except (ValueError, IndexError):
            return None
        try:
            seats = int(float(seg_parts[7]))
        except (ValueError, IndexError):
            seats = -1
    else:
        try:
            fare = float(seg_parts[7])
        except (ValueError, IndexError):
            return None
        try:
            seats = int(float(seg_parts[8]))
        except (ValueError, IndexError):
            seats = -1

    return dep, arr, carrier, flight_number, fare, currency, seats


def extract_bearer_token(payload: Any) -> Optional[str]:
    """Pull a JWT/Bearer string out of Auth JSON (shape varies)."""
    if isinstance(payload, str) and len(payload) > 40:
        return payload.strip()
    if isinstance(payload, dict):
        for key in (
            "accessToken",
            "token",
            "jwt",
            "access_token",
            "authToken",
            "Token",
            "AccessToken",
        ):
            val = payload.get(key)
            if isinstance(val, str) and len(val) > 20:
                return val.strip()
        for val in payload.values():
            t = extract_bearer_token(val)
            if t:
                return t
    return None


def fc_success_payload(payload: Dict[str, Any]) -> Tuple[bool, Any]:
    ok = payload.get("IsSuccessful")
    if ok is None:
        ok = payload.get("isSuccessful")
    result = payload.get("Result")
    if result is None:
        result = payload.get("result")
    if ok is False:
        return False, result
    return True, result


def normalize_route_code(route: str, origin: str, dest: str) -> bool:
    """Match ``VY;MADBCN`` style (carrier;origin+dest)."""
    route = route.strip().upper()
    o, d = origin.upper(), dest.upper()
    if ";" in route:
        _, body = route.split(";", 1)
        if len(body) == 6:
            return body[:3] == o and body[3:] == d
    if len(route) == 6:
        return route[:3] == o and route[3:] == d
    return False


def parse_route_dates(rows: Any, origin: str, dest: str) -> List[str]:
    """Collect yyyy-mm-dd strings from FlightCalendarRoutes ``Result`` rows."""
    out: List[str] = []
    if not isinstance(rows, list):
        return out

    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("Date") if row.get("Date") is not None else row.get("date")
        routes = row.get("Routes") or row.get("routes") or []
        if not isinstance(routes, list):
            continue

        hit = any(normalize_route_code(str(r), origin, dest) for r in routes)
        if not hit:
            continue

        if isinstance(raw_date, int):
            s = str(raw_date)
            if len(s) == 8:
                out.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
        elif isinstance(raw_date, str) and len(raw_date) == 8 and raw_date.isdigit():
            s = raw_date
            out.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")

    return sorted(set(out))


def collect_iso_dates_from_tree(obj: Any, bucket: Optional[Set[str]] = None) -> List[str]:
    """Fallback: grab ``YYYY-MM-DD`` substrings from nested JSON (e.g. ``bestPrices``)."""
    if bucket is None:
        bucket = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and len(v) >= 10:
                head = v[:10]
                try:
                    datetime.strptime(head, "%Y-%m-%d")
                    bucket.add(head)
                except ValueError:
                    pass
            collect_iso_dates_from_tree(v, bucket)
    elif isinstance(obj, list):
        for x in obj:
            collect_iso_dates_from_tree(x, bucket)
    return sorted(bucket)


def parse_market_destinations(payload: Any, _depth: int = 0) -> Tuple[str, ...]:
    """Extract IATA destination codes from AMS ``Markets/ByOrigin`` JSON."""
    found: Set[str] = set()
    if _depth > 18:
        return tuple()

    if isinstance(payload, list):
        for x in payload:
            for c in parse_market_destinations(x, _depth + 1):
                found.add(c)
    elif isinstance(payload, dict):
        for hint in (
            "destinationCode",
            "DestinationCode",
            "destination",
            "Destination",
            "code",
            "iataCode",
            "IataCode",
        ):
            v = payload.get(hint)
            if isinstance(v, str) and len(v) == 3 and v.isalpha():
                found.add(v.upper())
        nested = payload.get("destinationStation") or payload.get("DestinationStation")
        if nested is not None:
            for c in parse_market_destinations(nested, _depth + 1):
                found.add(c)
        for k, v in payload.items():
            if k in (
                "destinationCode",
                "DestinationCode",
                "destination",
                "Destination",
                "destinationStation",
                "DestinationStation",
            ):
                continue
            for c in parse_market_destinations(v, _depth + 1):
                found.add(c)

    return tuple(sorted(found))
