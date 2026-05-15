from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import date, datetime

class EasyJetAirport(BaseModel):
    code: str
    name: str
    lat: float
    long: float
    dests: list[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}

class EasyJetCalendarDay(BaseModel):
    date: date
    price: float
    lowFare: bool = False
    model_config = {"extra": "ignore"}

class EasyJetAvailabilityResponse(BaseModel):
    startDate: date
    endDate: date
    departureFlights: Optional[list[EasyJetCalendarDay]] = None
    returnFlights: Optional[list[EasyJetCalendarDay]] = None
    model_config = {"extra": "ignore"}

class EasyJetFare(BaseModel):
    flightNumber: str
    departureAirport: str
    arrivalAirport: str
    arrivalCountry: Optional[str] = None
    outboundPrice: float
    returnPrice: Optional[float] = None
    departureDateTime: datetime
    arrivalDateTime: datetime
    serviceError: Optional[Any] = None
    model_config = {"extra": "ignore"}
