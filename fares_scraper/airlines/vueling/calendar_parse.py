"""Parse Vueling FlightCalendar price strings (v1 and v2 formats per developer docs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


def parse_vueling_dt(raw: str) -> datetime:
    """Parse ``dd/mm/yyyy H:MM:SS`` as used in FlightCalendar item strings."""
    parts = (raw or "").strip().split()
    if len(parts) != 2:
        raise ValueError(f"Bad Vueling datetime: {raw!r}")
    d_part, t_part = parts[0], parts[1]
    day_s, month_s, year_s = d_part.split("/")
    h_s, m_s, s_s = t_part.split(":")
    return datetime(
        int(year_s),
        int(month_s),
        int(day_s),
        int(h_s),
        int(m_s),
        int(s_s),
    )


@dataclass(frozen=True)
class ParsedSegment:
    carrier: str
    flight_number: int
    origin: str
    destination: str
    dep: datetime
    arr: datetime
    product_class: str
    seats: int
    segment_price: Optional[float]
    """Per-leg price in calendar v1; ``None`` in v2 (total on itinerary header)."""


def _parse_segment_fields(fields: List[str]) -> ParsedSegment:
    if len(fields) < 7:
        raise ValueError(f"Segment too short: {fields}")

    carrier = fields[0].strip().upper()
    flight_number = int(fields[1])
    origin = fields[2].strip().upper()
    dep = parse_vueling_dt(fields[3])
    destination = fields[4].strip().upper()
    arr = parse_vueling_dt(fields[5])
    product_class = fields[6].strip().upper()

    # v1: 0..9 (Carrier..NextPrice), v2: 0..8 (Carrier..LegFareBasis)
    if len(fields) >= 10:
        price = float(fields[7])
        seats = int(float(fields[8]))
        return ParsedSegment(
            carrier=carrier,
            flight_number=flight_number,
            origin=origin,
            destination=destination,
            dep=dep,
            arr=arr,
            product_class=product_class,
            seats=seats,
            segment_price=price,
        )

    if len(fields) >= 9:
        seats = int(float(fields[7]))
        return ParsedSegment(
            carrier=carrier,
            flight_number=flight_number,
            origin=origin,
            destination=destination,
            dep=dep,
            arr=arr,
            product_class=product_class,
            seats=seats,
            segment_price=None,
        )

    raise ValueError(f"Unexpected segment field count {len(fields)}: {fields}")


def parse_calendar_price_item(item: str) -> Tuple[float, str, List[ParsedSegment]]:
    """
    Returns ``(itinerary_price, currency, segments)``.
    Itinerary price is the trip total (v2 header field 2, or sum of v1 segment prices for direct legs).
    """
    if "~" not in item:
        raise ValueError(f"Malformed calendar item: {item!r}")
    general, rest = item.split("~", 1)
    g_parts = general.split(";")
    if len(g_parts) < 3:
        raise ValueError(f"Malformed general info: {general!r}")
    currency = g_parts[0].strip().upper()
    trip_or_conn = float(g_parts[2])

    raw_segments = [s for s in rest.split("^") if s]
    segments = [_parse_segment_fields(s.split(";")) for s in raw_segments]

    if len(segments) == 1 and segments[0].segment_price is not None:
        itinerary_price = segments[0].segment_price
    else:
        itinerary_price = trip_or_conn

    return itinerary_price, currency, segments


class CalendarRoutesDay(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Date: int
    Routes: List[str] = Field(default_factory=list)


class CalendarRoutesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    IsSuccessful: bool
    Result: Optional[List[CalendarRoutesDay]] = None
    Errors: Optional[list] = None


class CalendarPriceDay(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    Carrier: str
    FlightDate: int = Field(validation_alias=AliasChoices("FlightDate", "Flight Date"))
    Items: List[str] = Field(default_factory=list)


class CalendarPricesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    IsSuccessful: bool
    Result: Optional[List[CalendarPriceDay]] = None
    Errors: Optional[list] = None
