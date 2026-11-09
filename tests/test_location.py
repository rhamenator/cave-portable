import unittest
from unittest.mock import patch

from cave_portable import data, location


class LocationTests(unittest.TestCase):
    def test_postal_required_and_normalized(self):
        self.assertEqual(location.validate_postal("us", "48201"), ("US", "48201"))
        self.assertEqual(location.validate_postal("ca", "k1a0b1"), ("CA", "K1A 0B1"))
        for country, code in (("US", ""), ("CA", "K1A"), ("US", "K1A0B1"), ("CA", "00000"), ("FR", "75001")):
            with self.assertRaises(data.DataError):
                location.validate_postal(country, code)

    @patch.object(data, "_json")
    def test_canadian_geocode_uses_fsa_but_retains_full_code(self, fetch):
        fetch.return_value = {"places": [{"place name": "Ottawa", "state abbreviation": "ON", "latitude": "45.42", "longitude": "-75.70"}]}
        place = location.resolve("CA", "K1A 0B1")
        self.assertEqual(place.code, "K1A 0B1")
        self.assertTrue(place.approximate)
        self.assertEqual(fetch.call_args.args[0], "https://api.zippopotam.us/ca/K1A")

    @patch.object(data, "_json")
    def test_us_street_refines_zip_coordinate(self, fetch):
        fetch.side_effect = [
            {"places": [{"place name": "Washington", "state abbreviation": "DC", "latitude": "38.9", "longitude": "-77.0"}]},
            {"result": {"addressMatches": [{"addressComponents": {"zip": "20500"}, "coordinates": {"x": -77.035, "y": 38.899}}]}},
        ]
        place = location.resolve("US", "20500", "1600 Pennsylvania Ave NW")
        self.assertEqual((place.lat, place.lon), (38.899, -77.035))
        self.assertIn("street=1600+Pennsylvania", fetch.call_args.args[0])

    @patch.object(data, "_json")
    def test_canadian_street_requires_nearby_matching_house(self, fetch):
        fetch.side_effect = [
            {"places": [{"place name": "Ottawa", "state abbreviation": "ON", "latitude": "45.42", "longitude": "-75.70"}]},
            [{"key": "locate", "name": "111 Wellington Street, Ottawa", "category": "Street", "lat": 45.423, "lng": -75.699}],
        ]
        self.assertEqual(location.resolve("CA", "K1A 0B1", "111 Wellington St").street, "111 Wellington St")


if __name__ == "__main__":
    unittest.main()
