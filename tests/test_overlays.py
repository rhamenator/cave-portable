import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PIL import Image

from cave_portable import overlays
from cave_portable.data import Observation


class OverlayTests(unittest.TestCase):
    def test_state_feed_keeps_winter_advisory_and_filters_cancelled(self):
        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=2)).isoformat()
        payload = {"features": [
            {"properties": {"event": "Winter Weather Advisory", "status": "Actual",
                            "expires": future}, "geometry": None},
            {"properties": {"event": "Tornado Warning", "status": "Actual",
                            "messageType": "Cancel", "expires": future}, "geometry": None},
        ]}
        rows = overlays._alert_rows(payload, now)
        self.assertEqual([(row[0], row[1]) for row in rows],
                         [("advisory", "Winter Weather Advisory")])

    def test_canadian_point_keeps_michigan_border_warning_context(self):
        now = datetime.now(timezone.utc)
        warning = ("warning", "Tornado Warning", [[(-83.4, 42.2), (-83.0, 42.2), (-83.0, 42.6)]],
                   now - timedelta(minutes=5), now - timedelta(minutes=5), now + timedelta(minutes=20))
        with (patch.object(overlays, "_radar_state", return_value="MI"),
              patch.object(overlays, "_state_alerts", return_value=[warning]),
              patch.object(overlays, "_local_alerts") as local,
              patch.object(overlays, "_nearby_observation", side_effect=overlays.data.DataError("none"))):
            _picture, note = overlays.draw(Image.new("RGB", (200, 100)), "-84,42,-82,43",
                                           (42.31, -83.03), include_spc=False,
                                           radar_point=(42.70, -83.47), include_local_alerts=False)
        local.assert_not_called()
        self.assertIn("NWS MI border context: 1 polygon", note)
        self.assertIn("Tornado Warning", note)

    def test_map_discloses_live_layer_times_on_older_scan(self):
        now = datetime.now(timezone.utc)
        observation = Observation("KLAN", "Lansing", now.strftime("%d %b %H:%M UTC"),
                                  20, "SW 10 kt", "10", "VFR", "", lat=42.78, lon=-84.59)
        with (patch.object(overlays, "_spc_outlook", return_value=[
                ("Slight", [[(-85, 42), (-84, 42), (-84, 43)]],
                 now - timedelta(hours=1), now - timedelta(hours=2), now + timedelta(hours=2))]),
              patch.object(overlays, "_local_alerts", return_value=[
                  ("warning", "Severe Thunderstorm Warning", [[(-85, 42), (-84, 42), (-84, 43)]],
                   now - timedelta(minutes=8), now - timedelta(minutes=8), now + timedelta(minutes=20))]),
              patch.object(overlays, "_nearby_observation", return_value=observation)):
            picture, note = overlays.draw(Image.new("RGB", (200, 100)), "-86,41,-83,44",
                                           (42.78, -84.59), scan_time=now - timedelta(minutes=10))
        self.assertEqual(picture.size, (200, 100))
        self.assertIn("not archived at radar scan time", note)
        self.assertIn("issued", note)
        self.assertIn("valid", note)
        self.assertIn("KLAN observation", note)


if __name__ == "__main__":
    unittest.main()
