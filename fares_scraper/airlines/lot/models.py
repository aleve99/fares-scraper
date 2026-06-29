from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /markets.json
# ---------------------------------------------------------------------------

class LotCurrency(BaseModel):
    currencyName: str
    currencyShortName: str
    currencySymbol: str


class LotLanguage(BaseModel):
    name: str
    isoCode: str
    pagePath: str


class LotMarket(BaseModel):
    firstDayOfWeek: int
    shortDateFormat: str
    longDateFormat: str
    market: str
    marketName: str
    marketNameEn: str
    marketFlagIcon: str
    marketCurrency: LotCurrency
    languages: List[LotLanguage]
    defaultAirport: Optional[dict] = None
    hideInMarketList: bool = False
    showFeaturedAirports: bool = False
    popularAirports: List[str] = Field(default_factory=list)
    showFeaturedAirportsApp: bool = False
    popularAirportsApp: List[str] = Field(default_factory=list)


class LotMarketsResponse(BaseModel):
    markets: List[LotMarket]


# ---------------------------------------------------------------------------
# /lowfarecalendarairports.json  (price-box route map)
# ---------------------------------------------------------------------------

class LotPriceBox(BaseModel):
    originAirportIATA: str
    originAirportName: str
    destinationAirportIATA: str
    destinationAirportName: str
    cabinClass: str          # "E" = Economy, "C" = Business
    tripType: str            # "O" = one-way, "R" = round-trip


class LotPriceBoxesResponse(BaseModel):
    priceBoxes: List[LotPriceBox]


# ---------------------------------------------------------------------------
# /air-calendars  (low-fare calendar)
# ---------------------------------------------------------------------------

class LotCalendarFare(BaseModel):
    departureDate: str          # "YYYY-MM-DD"
    price: Optional[float] = None
    tax: Optional[float] = None
    currency: Optional[str] = None
    available: bool = True


class LotCalendarResponse(BaseModel):
    fares: List[LotCalendarFare] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /air-bounds  (itinerary search)
# ---------------------------------------------------------------------------

class LotSegment(BaseModel):
    origin: str
    destination: str
    departureDateTime: str
    arrivalDateTime: str
    flightNumber: str
    carrierCode: str
    duration: Optional[int] = None   # minutes


class LotItinerary(BaseModel):
    segments: List[LotSegment]
    totalDuration: Optional[int] = None


class LotFareBound(BaseModel):
    itinerary: LotItinerary
    totalPrice: float
    currency: str
    cabinClass: str
    fareFamily: Optional[str] = None
    seatsAvailable: Optional[int] = None


class LotAirBoundsResponse(BaseModel):
    outboundFlights: List[LotFareBound] = Field(default_factory=list)
    inboundFlights: List[LotFareBound] = Field(default_factory=list)
