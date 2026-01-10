from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class RyanairFlightFare(BaseModel):
    amount: float
    count: Optional[int] = None
    type: Optional[str] = None

class RyanairRegularFare(BaseModel):
    fareKey: Optional[str] = None
    fareClass: Optional[str] = None
    fares: List[RyanairFlightFare]

class RyanairFlight(BaseModel):
    flightNumber: str
    time: List[datetime]
    regularFare: Optional[RyanairRegularFare] = None
    faresLeft: int = 0

class RyanairDay(BaseModel):
    dateOut: datetime
    flights: List[RyanairFlight]

class RyanairTrip(BaseModel):
    origin: str
    originName: Optional[str] = None
    destination: str
    destinationName: Optional[str] = None
    dates: List[RyanairDay]

class RyanairAvailabilityResponse(BaseModel):
    currency: str
    trips: List[RyanairTrip]

class RyanairAirportCoordinates(BaseModel):
    latitude: float
    longitude: float

class RyanairAirportResponse(BaseModel):
    code: str
    name: str
    coordinates: RyanairAirportCoordinates

class RyanairScheduleFlight(BaseModel):
    number: str
    carrierCode: str
    departureTime: str
    arrivalTime: str

class RyanairScheduleDay(BaseModel):
    day: int
    flights: List[RyanairScheduleFlight]

class RyanairScheduleResponse(BaseModel):
    month: int
    days: List[RyanairScheduleDay]

class RyanairFarfndPrice(BaseModel):
    value: float
    currencyCode: str

class RyanairFarfndAirport(BaseModel):
    iataCode: str
    name: str

class RyanairFarfndOutbound(BaseModel):
    departureDate: datetime
    arrivalDate: datetime
    price: RyanairFarfndPrice
    arrivalAirport: RyanairFarfndAirport
    flightNumber: str

class RyanairFarfndFare(BaseModel):
    outbound: RyanairFarfndOutbound

class RyanairFarfndResponse(BaseModel):
    fares: List[RyanairFarfndFare]
    total: int

