from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

class GFSortBy(Enum):
    BEST = 1
    PRICE = 2
    DEPARTURE = 3
    ARRIVAL = 4
    DURATION = 5
    EMISSIONS = 6

class GFTripType(Enum):
    ROUND_TRIP = 1
    ONE_WAY = 2

class GFSeatClass(Enum):
    ECONOMY = 1
    PREMIUM_ECONOMY = 2
    BUSINESS = 3
    FIRST = 4

class GFMaxStops(Enum):
    ANY = 0
    NON_STOP = 1
    ONE_STOP_OR_FEWER = 2
    TWO_OR_FEWER_STOPS = 3

class GFFlightRequest(BaseModel):
    origins: List[str]
    destinations: List[str]
    date: str
    adults: int = 1
    children: int = 0
    infants_in_seat: int = 0
    infants_on_lap: int = 0
    trip_type: GFTripType = GFTripType.ONE_WAY
    seat_class: GFSeatClass = GFSeatClass.ECONOMY
    max_price: Optional[int] = None
    time_restrictions: Optional[list] = None
    max_stops: GFMaxStops = GFMaxStops.NON_STOP
    airlines: Optional[List[str]] = None
    max_flight_duration: Optional[int] = None
    layover_airports: Optional[list] = None
    max_layover_duration: Optional[int] = None
    sort_by: GFSortBy = GFSortBy.PRICE

    def encode(self) -> list:
        return [
            [], # [0] Always empty
            [
                None, # [0] Unknown
                None, # [1] Unknown
                self.trip_type.value, # [2] Trip type: 2=One-way, 1=Round-trip
                None, # [3] Unknown
                [],   # [4] Unknown
                self.seat_class.value, # [5] Seat class: 1=Economy, 2=Premium Economy, 3=Business, 4=First Class
                [self.adults, self.children, self.infants_on_lap, self.infants_in_seat], # [6] Passengers
                [None, self.max_price] if self.max_price else None, # [7] Max price constraint
                None, # [8] Unknown
                None, # [9] Unknown
                None, # [10] Unknown
                None, # [11] Unknown
                None, # [12] Unknown
                [     # [13] Flight Segments Array
                    [
                        [[[o, 0] for o in self.origins]], # [0] Origins
                        [[[d, 0] for d in self.destinations]], # [1] Destinations
                        self.time_restrictions, # [2] Time restrictions [earliest_dep, latest_dep, earliest_arr, latest_arr]
                        self.max_stops.value, # [3] Stops limit (1=Non-stop, 2=1 stop max, 3=2 stops max)
                        self.airlines,  # [4] Allowed airlines, e.g. ["FR", "U2"]
                        None,      # [5] Unknown
                        self.date,      # [6] Travel Date
                        [self.max_flight_duration] if self.max_flight_duration else None, # [7] Max flight duration [hours]
                        None,      # [8] Selected flights (for round-trip return flight matching)
                        self.layover_airports, # [9] Allowed/Restricted layover airports
                        None,      # [10] Unknown
                        None,      # [11] Unknown
                        self.max_layover_duration, # [12] Max layover duration [hours]
                        None,      # [13] Emissions data
                        3          # [14] Constant
                    ]
                ],
                None, # [14] Unknown
                None, # [15] Unknown
                None, # [16] Unknown
                1     # [17] Constant
            ],
            self.sort_by.value, # [2] Sort logic (1=BEST, 2=PRICE, etc.)
            0, # [3] Constant
            0, # [4] Constant
            1  # [5] Constant
        ]

    @classmethod
    def decode(cls, encoded: list) -> 'GFFlightRequest':
        trip_type = GFTripType(encoded[1][2])
        seat_class = GFSeatClass(encoded[1][5])
        passengers = encoded[1][6]
        adults, children, infants_on_lap, infants_in_seat = passengers[0], passengers[1], passengers[2], passengers[3]
        max_price_constraint = encoded[1][7]
        max_price = max_price_constraint[1] if max_price_constraint else None

        segments = encoded[1][13][0]
        origins = [o[0][0] for o in segments[0]]
        destinations = [d[0][0] for d in segments[1]]
        time_restrictions = segments[2]
        max_stops = GFMaxStops(segments[3])
        airlines = segments[4]
        date_str = segments[6]
        max_flight_duration_data = segments[7]
        max_flight_duration = max_flight_duration_data[0] if max_flight_duration_data else None
        layover_airports = segments[9]
        max_layover_duration = segments[12]

        sort_by = GFSortBy(encoded[2])

        return cls(
            origins=origins,
            destinations=destinations,
            date=date_str,
            adults=adults,
            children=children,
            infants_in_seat=infants_in_seat,
            infants_on_lap=infants_on_lap,
            trip_type=trip_type,
            seat_class=seat_class,
            max_price=max_price,
            time_restrictions=time_restrictions,
            max_stops=max_stops,
            airlines=airlines,
            max_flight_duration=max_flight_duration,
            layover_airports=layover_airports,
            max_layover_duration=max_layover_duration,
            sort_by=sort_by
        )
