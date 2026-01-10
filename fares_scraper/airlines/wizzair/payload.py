from pydantic import Field
from datetime import date
from typing import List
from ...base.payload import BasePayload

class MapPayload(BasePayload):
    languageCode: str = "en-gb"

class FlightDatesPayload(BasePayload):
    departureStation: str
    arrivalStation: str
    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")

class DetailedFlightsPayload(BasePayload):
    date: date
    departureStationIata: str
    arrivalStationIata: str
    type: str = "airport"

# Populate by name already set in BasePayload
class TimetableFlightItem(BasePayload):
    departureStation: str
    arrivalStation: str
    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")

class TimetableV2Payload(BasePayload):
    flightList: List[TimetableFlightItem]
    priceType: str = "regular"
    adultCount: int = 1
    childCount: int = 0
    infantCount: int = 0
    macStationsAllowed: bool = False
