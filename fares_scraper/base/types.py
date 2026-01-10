from pydantic import BaseModel, computed_field
from typing import Optional, List, Any
from datetime import datetime
import xxhash

class Airport(BaseModel):
    iata_code: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    name: Optional[str] = None

class OneWayFare(BaseModel):
    dep_time: datetime
    arr_time: datetime
    origin: str
    destination: str
    fare: float
    currency: str
    left: int = -1
    flight_number: str = ""
    operating_carrier: str = ""
    marketing_carrier: str = ""

    @computed_field
    @property
    def flight_key(self) -> int:
        """
        Automatically generated unique identifier for the flight.
        Format: "{operating_carrier}|{flight_number}|{departure_time}"
        """
        text = f"{self.operating_carrier}|{self.flight_number}|{self.dep_time.isoformat()}"
        unsigned = xxhash.xxh64(text).intdigest()
        return unsigned if unsigned < 2**63 else unsigned - 2**64

    @computed_field
    @property
    def fare_key(self) -> int:
        """
        Automatically generated unique identifier for the specific fare.
        Format: "{marketing_carrier}|{operating_carrier}|{flight_number}|{departure_time}"
        """
        text = f"{self.marketing_carrier}|{self.operating_carrier}|{self.flight_number}|{self.dep_time.isoformat()}"
        unsigned = xxhash.xxh64(text).intdigest()
        return unsigned if unsigned < 2**63 else unsigned - 2**64

class RoundTripFare(BaseModel):
    outbound: OneWayFare
    inbound: OneWayFare
    
    @property
    def total_fare(self) -> float:
        return self.outbound.fare + self.inbound.fare
    
    @property
    def currency(self) -> str:
        return self.outbound.currency

class Schedule(BaseModel):
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    flight_number: str


class ConcurrentResults(BaseModel):
    results: List[Any]
    execution_time: float
