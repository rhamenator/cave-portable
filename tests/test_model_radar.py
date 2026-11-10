import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cave_portable import data, hrrr, model, radar
from cave_portable.data import DataError


class ForecastTests(unittest.TestCase):
    def test_regional_forecast_zoom_really_changes_extent(self):
        wide = [float(value) for value in model.regional_bbox(42.7761, -84.5997, 1).split(",")]
        close = [float(value) for value in model.regional_bbox(42.7761, -84.5997, 4).split(",")]
        self.assertAlmostEqual((wide[2] - wide[0]) / (close[2] - close[0]), 4)
    def test_gfs_valid_time_uses_next_utc_three_hour_slot(self):
        now = datetime(2026, 11, 9, 17, 50, tzinfo=timezone.utc)
        self.assertEqual(model.valid_time(24, now), datetime(2026, 11, 10, 18, tzinfo=timezone.utc))
        with self.assertRaises(DataError):
            model.valid_time(999, now)

    @patch.object(hrrr.data, "_json")
    @patch.object(hrrr.model, "_png")
    def test_hrrr_rejects_mismatched_and_past_forecasts(self, png, fetch):
        now = datetime(2026, 11, 9, 20, tzinfo=timezone.utc)
        fetch.return_value = {"model_init_utc": "2026-11-09T18:00:00Z", "model_forecast_utc": "2026-11-09T22:00:00Z"}
        with self.assertRaisesRegex(DataError, "did not match"):
            hrrr.reflectivity(3, now)
        fetch.return_value = {"model_init_utc": "2026-11-09T16:00:00Z", "model_forecast_utc": "2026-11-09T19:00:00Z"}
        with self.assertRaisesRegex(DataError, "already past"):
            hrrr.reflectivity(3, now)
        png.assert_not_called()


class RadarTests(unittest.TestCase):
    @patch.object(radar, "_json")
    def test_station_catalog_accepts_only_wsr88d(self, fetch):
        fetch.return_value = {"features": [
            {"properties": {"id": f"K{i:03d}", "name": f"Site {i}", "stationType": "WSR-88D"},
             "geometry": {"coordinates": [-83.0, 42.0]}} for i in range(101)
        ] + [{"properties": {"id": "XXXX", "name": "Other", "stationType": "TDWR"},
              "geometry": {"coordinates": [-83.0, 42.0]}}]}
        sites = radar.available_sites()
        self.assertEqual(len(sites), 101)
        self.assertNotIn("XXX · Other", sites)

    def test_zoom_changes_viewport(self):
        wide = [float(x) for x in radar._bbox("DTX · Detroit", zoom=1).split(",")]
        close = [float(x) for x in radar._bbox("DTX · Detroit", zoom=4).split(",")]
        self.assertAlmostEqual((wide[2] - wide[0]) / (close[2] - close[0]), 4, places=1)

    def test_klan_selects_grand_rapids_radar(self):
        sites = {"GRR · Grand Rapids": ("GRR", -85.54488, 42.89388, "KGRR"),
                 "DTX · Detroit": ("DTX", -83.47166, 42.69999, "KDTX")}
        self.assertEqual(radar.nearest_site(42.7761, -84.5997, sites), "GRR · Grand Rapids")
        self.assertIn("KLAN", data.STATIONS)

    def test_site_view_can_center_on_selected_airport(self):
        bounds = [float(value) for value in radar._bbox(
            "GRR · Grand Rapids", zoom=4, center=(42.7761, -84.5997)).split(",")]
        self.assertAlmostEqual((bounds[0] + bounds[2]) / 2, -84.5997, places=3)
        self.assertAlmostEqual((bounds[1] + bounds[3]) / 2, 42.7761, places=3)

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
