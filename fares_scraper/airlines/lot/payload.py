from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class LotSearchPayload:
    """Payload for POST /air-bounds and POST /air-calendars."""
    origin: str
    destination: str
    departureDate: str          # "YYYY-MM-DD"
    returnDate: Optional[str]   # None for one-way
    adults: int = 1
    children: int = 0
    infants: int = 0
    cabinClass: str = "ECONOMY"  # "ECONOMY" | "BUSINESS"
    market: str = "it"
    language: str = "it"
    currency: str = "EUR"
    promoCode: Optional[str] = None

    def to_air_bounds_dict(self) -> dict:
        d = {
            "tripType": "R" if self.returnDate else "O",
            "origin": self.origin,
            "destination": self.destination,
            "departureDate": self.departureDate,
            "adults": self.adults,
            "children": self.children,
            "infants": self.infants,
            "cabin": self.cabinClass,
            "market": self.market,
            "language": self.language,
            "currency": self.currency,
        }
        if self.returnDate:
            d["returnDate"] = self.returnDate
        if self.promoCode:
            d["promoCode"] = self.promoCode
        return d

    def to_air_calendars_dict(self) -> dict:
        return self.to_air_bounds_dict()
