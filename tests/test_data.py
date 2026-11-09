import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cave_portable import data


class DataTests(unittest.TestCase):
    def test_station_validation_blocks_url_injection(self):
        self.assertEqual(data.validate_station(" kdtw "), "KDTW")
        for invalid in ("", "DTW", "KDTW&x=1", "../a", "éAAA"):
            with self.assertRaises(data.DataError):
                data.validate_station(invalid)

    @patch.object(data, "_fetch")
    def test_metar_normalization(self, fetch):
        fetch.return_value = json.dumps([{"icaoId": "KDTW", "name": "Detroit", "reportTime": "2026-11-09T17:00:00Z", "temp": 11.1, "wdir": 260, "wspd": 7, "fltCat": "VFR", "rawOb": "METAR KDTW"}]).encode()
        row = data.metars(("KDTW",))[0]
        self.assertEqual(row.station, "KDTW")
        self.assertEqual(row.observed, "09 Nov 17:00 UTC")
        self.assertEqual(row.wind, "260° 7 kt")

    @patch.object(data, "_fetch")
    def test_alerts_limit(self, fetch):
        fetch.return_value = json.dumps({"features": [{"properties": {"event": "Test", "headline": "Headline", "description": "Detail"}}]}).encode()
        self.assertEqual(data.alerts("mi"), [("Test", "Headline", "Detail")])
        with self.assertRaises(data.DataError):
            data.alerts("MI&x")

    def test_images_are_allowlisted(self):
        with self.assertRaises(data.DataError):
            data.image("https://example.com/image.png")

    @patch.object(data, "_fetch_with_time")
    def test_stale_image_is_rejected(self, fetch):
        fetch.return_value = (b"GIF89a" + b"\0" * 20, datetime.now(timezone.utc) - timedelta(hours=2))
        with self.assertRaisesRegex(data.DataError, "stale"):
            data.image_record(data.RADAR_URL)


if __name__ == "__main__":
    unittest.main()
