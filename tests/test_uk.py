import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import h5py
import numpy as np

from cave_portable import data, location, uk


class UKTests(unittest.TestCase):
    def test_full_postcode_required_and_normalized(self):
        self.assertEqual(location.validate_postal("UK", "sw1a2aa"), ("UK", "SW1A 2AA"))
        self.assertEqual(location.validate_postal("GB", "EC1A 1BB"), ("UK", "EC1A 1BB"))
        for invalid in ("SW1A", "SW1A 2A", "not a postcode"):
            with self.assertRaises(data.DataError):
                location.validate_postal("UK", invalid)

    def test_country_station_lists_and_matching(self):
        self.assertIn("EGLL", data.stations_for_country("UK"))
        self.assertIn("CYYZ", data.stations_for_country("CA"))
        self.assertNotIn("KDTW", data.stations_for_country("UK"))
        self.assertTrue(data.station_matches_country("EGLL", "UK"))
        self.assertFalse(data.station_matches_country("KDTW", "UK"))

    @patch("cave_portable.location.data._json")
    def test_postcode_lookup_and_street_rejection(self, fetch):
        fetch.return_value = {"result": {"latitude": 51.5, "longitude": -.12,
                                          "admin_district": "Westminster", "country": "England"}}
        point = location.resolve("UK", "SW1A 2AA")
        self.assertEqual((point.lat, point.lon, point.country), (51.5, -.12, "UK"))
        self.assertIn("postcode centroid", point.label)
        with self.assertRaises(data.DataError):
            location.resolve("UK", "SW1A 2AA", "10 Downing Street")

    def test_warning_polygon_time_and_colour(self):
        now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        polygon = {"type": "Polygon", "coordinates": [[[-1, 51], [0, 51], [0, 52], [-1, 52], [-1, 51]]]}
        props = {"GlobalID": "warn-1", "warninglevel": "RED", "weathertype": "WIND",
                 "warningheadline": "Damaging wind", "issuedDate": int((now-timedelta(hours=1)).timestamp()*1000),
                 "validfromdate": int((now-timedelta(minutes=5)).timestamp()*1000),
                 "validtodate": int((now+timedelta(hours=2)).timestamp()*1000)}
        with patch.object(uk, "warning_features", return_value=({"properties": props, "geometry": polygon},)):
            alerts = uk.point_alerts(51.5, -.5, now)
            self.assertEqual((len(alerts), alerts[0].level), (1, "warning"))
            self.assertEqual(uk.point_alerts(53, -.5, now), [])
            self.assertIn("issued 10 Nov 11:00 UTC", alerts[0].description)
            props["warninglevel"] = "YELLOW"
            self.assertEqual(uk.point_alerts(51.5, -.5, now)[0].level, "watch")
            props["validfromdate"] = int((now+timedelta(hours=1)).timestamp()*1000)
            self.assertEqual(uk.point_alerts(51.5, -.5, now)[0].level, "advisory")

    def test_decoded_rain_raster(self):
        output = io.BytesIO()
        with h5py.File(output, "w") as file:
            where = file.create_group("where")
            where.attrs["projdef"] = b"+proj=longlat +datum=WGS84 +no_defs"
            where.attrs["UL_lon"] = -1.
            where.attrs["UL_lat"] = 52.
            where.attrs["xscale"] = .01
            where.attrs["yscale"] = .01
            layer = file.create_group("dataset1/data1")
            what = layer.create_group("what")
            what.attrs["quantity"] = b"RATE"
            what.attrs["gain"] = 1.
            what.attrs["offset"] = 0.
            what.attrs["nodata"] = -1.
            layer.create_dataset("data", data=np.full((100, 100), 5., dtype="float32"))
        # WGS84 geographic coordinate scaling is intentionally simple in this fixture.
        overlay = uk._rain_overlay(output.getvalue(), "-0.9,51.1,-0.1,51.9")
        self.assertEqual(overlay.size, (960, 500))
        self.assertGreater(overlay.getpixel((480, 250))[3], 0)


if __name__ == "__main__":
    unittest.main()
