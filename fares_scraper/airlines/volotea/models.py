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

    model_config = {"extra": "ignore"}

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

    @field_validator("CarrierCode", "BookingClass", mode="before")
    @classmethod
    def _optional_str_fields(cls, v: object) -> str:
        return "" if v is None else str(v)

    def is_connection_itinerary(self) -> bool:
        """True when API attaches segment list (via FCO etc.); direct offers use ``null``."""
        return self.ConnectionInformation is not None

    @classmethod
    def parse_schedule_datetime(cls, raw: str) -> datetime:
        """Parse ``YYYYMMDDHHmm`` from Departure / Arrival."""
        return datetime.strptime(raw, VOL_SCHEDULE_DT_FMT)

    def price(self) -> Optional[Tuple[float, str]]:
        """Prefer ``FareType`` ``R``; else cheapest ``PriceWithFee`` among rows with a currency (e.g. ``AE`` when ``R`` is missing)."""
        if not self.Prices:
            return None
        for p in self.Prices:
            if p.FareType == "R" and p.Currency:
                return p.PriceWithFee, p.Currency
        priced = [p for p in self.Prices if p.Currency]
        if not priced:
            return None
        best = min(priced, key=lambda x: x.PriceWithFee)
        return best.PriceWithFee, best.Currency


class VoloteaMarketEntry(BaseModel):
    Price: float = 0.0
    Enabled: bool = False
    FlightType: str = ""
    IsConnectionMarket: bool = False
    OperatingCarrier: str = ""

    model_config = {"extra": "ignore"}


def _flight_dict_for_parse(row: Dict[str, Any]) -> Dict[str, Any]:
    """Drop price rows missing ``FareBasis``/``Currency`` (e.g. ``AZ`` on connections) before validation."""
    raw_prices = row.get("Prices")
    if not isinstance(raw_prices, list):
        return {**row, "Prices": []}
    kept: List[Dict[str, Any]] = []
    for p in raw_prices:
        if not isinstance(p, dict):
            continue
        if p.get("FareBasis") is None or p.get("Currency") is None:
            continue
        kept.append(p)
    return {**row, "Prices": kept}


def parse_schedule_payload(data: Dict[str, Any]) -> Dict[str, List[VoloteaScheduleFlight]]:
    """Parse top-level schedule JSON { 'ORIG-DEST': [ {...}, ... ], ... }."""
    out: Dict[str, List[VoloteaScheduleFlight]] = {}
    for key, rows in data.items():
        if not isinstance(rows, list):
            continue
        out[key] = []
        for row in rows:
            if isinstance(row, dict):
                out[key].append(VoloteaScheduleFlight.model_validate(_flight_dict_for_parse(row)))
    return out
