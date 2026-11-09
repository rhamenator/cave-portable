import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cave_portable import model, radar
from cave_portable.data import DataError


class ForecastTests(unittest.TestCase):
    def test_gfs_valid_time_uses_next_utc_three_hour_slot(self):
        now = datetime(2026, 11, 9, 17, 50, tzinfo=timezone.utc)
        self.assertEqual(model.valid_time(24, now), datetime(2026, 11, 10, 18, tzinfo=timezone.utc))
        with self.assertRaises(DataError):
            model.valid_time(999, now)


class RadarTests(unittest.TestCase):
    @patch.object(radar, "_json")
    @patch.object(radar, "_png")
    def test_stale_scan_is_rejected_before_loading_image(self, png, json_fetch):
        json_fetch.return_value = {"meta": {"site": "DTX", "product": "N0S", "valid": "2023-03-16T13:33:50Z"}}
        with self.assertRaisesRegex(DataError, "stale"):
            radar.site_map("DTX · Detroit", "Storm-relative velocity", datetime(2026, 11, 9, tzinfo=timezone.utc))
        png.assert_not_called()

    def test_site_and_product_are_bounded(self):
        with self.assertRaises(DataError):
            radar.site_map("../../", "Storm-relative velocity")
        with self.assertRaises(DataError):
            radar.site_map("DTX · Detroit", "N0C")


if __name__ == "__main__":
    unittest.main()
