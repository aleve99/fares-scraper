import unittest

from fares_scraper.airlines.vueling.calendar_parse import (
    CalendarPricesResponse,
    parse_calendar_price_item,
)


class TestVuelingCalendarParse(unittest.TestCase):
    def test_v1_direct_item(self) -> None:
        item = (
            "EUR;2023-05-05T11:58;11~"
            "VY;3907;PMI;30/05/2023 5:40:00;BCN;30/05/2023 6:35:00;BA;27.99;5;31.99"
        )
        price, cur, segs = parse_calendar_price_item(item)
        self.assertEqual(cur, "EUR")
        self.assertAlmostEqual(price, 27.99)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].origin, "PMI")
        self.assertEqual(segs[0].destination, "BCN")
        self.assertEqual(segs[0].flight_number, 3907)
        self.assertEqual(segs[0].seats, 5)

    def test_v2_connection_item(self) -> None:
        item = (
            "EUR;2023-11-10T09:34;85.64~"
            "VY;6103;FCO;10/11/2023 19:05:00;BCN;10/11/2023 20:55:00;BA;5;OOWVYCLB^"
            "VY;1896;BCN;11/11/2023 6:30:00;DUS;11/11/2023 8:45:00;BA;9;QOWVYCLB"
        )
        price, cur, segs = parse_calendar_price_item(item)
        self.assertEqual(cur, "EUR")
        self.assertAlmostEqual(price, 85.64)
        self.assertEqual(len(segs), 2)

    def test_calendar_prices_response_model(self) -> None:
        raw = {
            "IsSuccessful": True,
            "Result": [
                {
                    "Carrier": "VY",
                    "FlightDate": 20230530,
                    "Items": [
                        "EUR;2023-05-05T11:58;11~VY;3907;PMI;30/05/2023 5:40:00;BCN;30/05/2023 6:35:00;BA;27.99;5;31.99"
                    ],
                }
            ],
            "Errors": None,
        }
        m = CalendarPricesResponse.model_validate(raw)
        self.assertTrue(m.IsSuccessful)
        self.assertIsNotNone(m.Result)
        assert m.Result is not None
        self.assertEqual(m.Result[0].FlightDate, 20230530)


if __name__ == "__main__":
    unittest.main()
