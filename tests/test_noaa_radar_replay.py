import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from cave_portable.data import DataError
from scripts.noaa_radar_replay import archived_field, candidate_keys


class RadarReplayTests(unittest.TestCase):
    def test_archive_keys_do_not_exceed_cutoff(self):
        keys = ["OAX_N0C_2024_04_26_20_27_00", "OAX_N0C_2024_04_26_20_29_21",
                "OAX_N0C_2024_04_26_20_31_00"]
        with patch("scripts.noaa_radar_replay._day_keys", return_value=keys):
            selected = candidate_keys("OAX", "N0C", datetime(2024, 4, 26, 20, 30, tzinfo=timezone.utc))
        self.assertEqual([key for key, _ in selected], keys[1::-1])

    def test_decoded_time_after_cutoff_is_skipped(self):
        as_of = datetime(2024, 4, 26, 20, 30, tzinfo=timezone.utc)
        keys = [("OAX_N0C_2024_04_26_20_29_21", datetime(2024, 4, 26, 20, 29, 21, tzinfo=timezone.utc)),
                ("OAX_N0C_2024_04_26_20_27_00", datetime(2024, 4, 26, 20, 27, tzinfo=timezone.utc))]
        decoded = [SimpleNamespace(time=datetime(2024, 4, 26, 20, 30, 7, tzinfo=timezone.utc)),
                   SimpleNamespace(time=datetime(2024, 4, 26, 20, 27, 40, tzinfo=timezone.utc))]
        with patch("scripts.noaa_radar_replay.candidate_keys", return_value=keys), \
             patch("scripts.noaa_radar_replay._fetch", return_value=b"data"), \
             patch("scripts.noaa_radar_replay.decode", side_effect=decoded):
            field, key, skipped = archived_field("OAX", "N0C", as_of)
        self.assertEqual(field.time, decoded[1].time)
        self.assertEqual(key, keys[1][0])
        self.assertEqual(skipped, 0)

    def test_unsupported_archive_product_is_counted_and_skipped(self):
        as_of = datetime(2024, 4, 26, 20, 30, tzinfo=timezone.utc)
        keys = [("OAX_N0C_2024_04_26_20_29_21", datetime(2024, 4, 26, 20, 29, 21, tzinfo=timezone.utc)),
                ("OAX_N0C_2024_04_26_20_27_00", datetime(2024, 4, 26, 20, 27, tzinfo=timezone.utc))]
        good = SimpleNamespace(time=datetime(2024, 4, 26, 20, 27, 40, tzinfo=timezone.utc))
        with patch("scripts.noaa_radar_replay.candidate_keys", return_value=keys), \
             patch("scripts.noaa_radar_replay._fetch", return_value=b"data"), \
             patch("scripts.noaa_radar_replay.decode", side_effect=[DataError("unsupported"), good]):
            field, key, skipped = archived_field("OAX", "N0C", as_of)
        self.assertEqual(field, good)
        self.assertEqual(key, keys[1][0])
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
