from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

VOL_SCHEDULE_DT_FMT = "%Y%m%d%H%M"


class VoloteaPriceRow(BaseModel):
    Price: float
    PriceWithFee: float
    FareType: str = ""
    FareBasis: str = ""
    Currency: str = "EUR"


class VoloteaScheduleFlight(BaseModel):
    Departure: str
    Arrival: str
    FlightNumber: str
    Terminal: str = ""
    Promo: Optional[bool] = None
    Prices: List[VoloteaPriceRow] = Field(default_factory=list)
    AvailableSeats: int = -1
    AvailableSeatsStatus: int = 0
    ConnectionInformation: Optional[Any] = None
    CarrierCode: str = ""
    BookingClass: str = ""
    OperatingCarrier: Optional[str] = None

    model_config = {"extra": "ignore"}

    @field_validator("FlightNumber", mode="before")
    @classmethod
    def _flight_number_str(cls, v: object) -> str:
        return str(v) if v is not None else ""

    @classmethod
    def parse_schedule_datetime(cls, raw: str) -> datetime:
        """Parse ``YYYYMMDDHHmm`` from Departure / Arrival."""
        return datetime.strptime(raw, VOL_SCHEDULE_DT_FMT)

    def price(self) -> Optional[Tuple[float, str]]:
        """FareType ``R`` = regular (no Volotea membership / promo tier); returns ``PriceWithFee`` and currency."""
        for p in self.Prices:
            if p.FareType == "R":
                return p.PriceWithFee, p.Currency
        return None


class VoloteaMarketEntry(BaseModel):
    Price: float = 0.0
    Enabled: bool = False
    FlightType: str = ""
    IsConnectionMarket: bool = False

    model_config = {"extra": "ignore"}


def parse_schedule_payload(data: Dict[str, Any]) -> Dict[str, List[VoloteaScheduleFlight]]:
    """Parse top-level schedule JSON { 'ORIG-DEST': [ {...}, ... ], ... }."""
    out: Dict[str, List[VoloteaScheduleFlight]] = {}
    for key, rows in data.items():
        if not isinstance(rows, list):
            continue
        out[key] = []
        for row in rows:
            if isinstance(row, dict):
                out[key].append(VoloteaScheduleFlight.model_validate(row))
    return out
