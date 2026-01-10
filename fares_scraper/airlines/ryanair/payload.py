from datetime import date, time
from typing import Optional, List
from ...base.payload import BasePayload

class AvailabilityPayload(BasePayload):
    Origin: str
    Destination: str
    DateOut: date
    DateIn: date
    ADT: int = 1
    TEEN: int = 0
    CHD: int = 0
    INF: int = 0
    promoCode: str = "" 
    IncludeConnectingFlights: bool = False
    FlexDaysBeforeOut: int = 0
    FlexDaysOut: int = 0
    FlexDaysBeforeIn: int = 0
    FlexDaysIn: int = 0
    RoundTrip: bool = True
    ToUs: str = "AGREED"

class FarfndOneWayPayload(BasePayload):
    departureAirportIataCode: str = ""
    outboundDepartureDateFrom: Optional[date] = None
    outboundDepartureDateTo: Optional[date] = None
    arrivalAirportIataCodes: Optional[List[str]] = None
    outboundDepartureTimeFrom: Optional[time] = time(0,0)
    outboundDepartureTimeTo: Optional[time] = time(23,59)
    outboundDepartureDaysOfWeek: Optional[str] = None
    adultPaxCount: Optional[int] = 1
    market: Optional[str] = "it-it"
    promoCode: Optional[str] = "undefined"

class FarfndRoundTripPayload(BasePayload):
    departureAirportIataCode: str = ""
    outboundDepartureDateFrom: Optional[date] = None
    outboundDepartureDateTo: Optional[date] = None
    inboundDepartureDateFrom: Optional[date] = None
    inboundDepartureDateTo: Optional[date] = None
    arrivalAirportIataCodes: Optional[List[str]] = None
    durationFrom: Optional[int] = None
    durationTo: Optional[int] = None
    outboundDepartureTimeFrom: Optional[time] = time(0,0)
    outboundDepartureTimeTo: Optional[time] = time(23,59)
    inboundDepartureTimeFrom: Optional[time] = time(0,0)
    inboundDepartureTimeTo: Optional[time] = time(23,59)
    outboundDepartureDaysOfWeek: Optional[str] = None
    inboundDepartureDaysOfWeek: Optional[str] = None
    adultPaxCount: Optional[int] = 1
    market: Optional[str] = "it-it"
    promoCode: Optional[str] = "undefined"

def get_availabilty_payload(
        origin: str,
        destination: str,
        date_out: date,
        date_in: date,
        flex_days: int = 0,
        round_trip: bool = True
    ) -> AvailabilityPayload:

    return AvailabilityPayload(
        Origin=origin,
        Destination=destination,
        DateOut=date_out,
        DateIn=date_in,
        FlexDaysIn=flex_days,
        FlexDaysOut=flex_days,
        RoundTrip=round_trip
    )

def get_farfnd_one_way_payload(
        origin: str,
        destinations: List[str],
        date_from: date,
        date_to: date,
        time_from: time,
        time_to: time,
        market: str
    ) -> FarfndOneWayPayload:

    return FarfndOneWayPayload(
        departureAirportIataCode=origin,
        outboundDepartureDateFrom=date_from,
        outboundDepartureDateTo=date_to,
        outboundDepartureTimeFrom=time_from,
        outboundDepartureTimeTo=time_to,
        arrivalAirportIataCodes=destinations,
        market=market
    )
