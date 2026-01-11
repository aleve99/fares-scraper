from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class WizzAirConnection(BaseModel):
    iata: str
    isDomestic: bool
    isNew: bool
    isConnected: bool

class WizzAirCity(BaseModel):
    iata: str
    mac: Optional[str] = None
    longitude: float
    latitude: float
    shortName: str
    countryName: str
    countryCode: str
    connections: List[WizzAirConnection]
    isFakeStation: bool = False

class WizzAirMapResponse(BaseModel):
    cities: List[WizzAirCity]

class WizzAirPrice(BaseModel):
    amount: float
    currencyCode: str

class WizzAirTimetableFlight(BaseModel):
    departureStation: str
    arrivalStation: str
    departureDate: datetime
    price: WizzAirPrice
    priceType: str

class WizzAirTimetableResponse(BaseModel):
    outboundFlights: List[WizzAirTimetableFlight]
    returnFlights: Optional[List[WizzAirTimetableFlight]] = None

class WizzAirFlightDatesResponse(BaseModel):
    flightDates: List[datetime]

class WizzAirDetailedFlight(BaseModel):
    departureStationIata: str
    departureDateTime: datetime
    arrivalStationIata: str
    arrivalDateTime: datetime
    flightNumber: str
    carrierCode: str
    opSuffix: str

class WizzAirDetailedFlightsResponse(BaseModel):
    flights: List[WizzAirDetailedFlight]
