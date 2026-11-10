import unittest
from datetime import datetime, timedelta, timezone

from scripts.mesonet_replay import read_mts, replay


def mts(rows):
    header = "101 ! (c) 2013 Oklahoma Climatological Survey and the Oklahoma Mesonet - synthetic test data\n5 2013 05 20 00 00 00\nSTID STNM TIME TAIR RELH PRES WSPD WMAX\n"
    return header + "\n".join(rows) + "\n"


class MesonetReplayTests(unittest.TestCase):
    def test_replay_excludes_future_and_reports_actual_anchor(self):
        rows = read_mts(mts([
            "NORM 1 840 25 60 980 5 8",   # 14:00 UTC
            "NORM 1 1020 27 65 978 7 10", # 17:00 UTC
            "NORM 1 1025 28 66 977 8 12",
            "NORM 1 1200 34 80 960 30 50", # future 20:00 UTC
        ]))
        result = replay(rows, datetime(2013, 5, 20, 17, 5, tzinfo=timezone.utc))
        self.assertEqual(result["latest_observation_utc"], "2013-05-20T17:05:00+00:00")
        self.assertEqual(result["anchor_utc"], "2013-05-20T14:00:00+00:00")
        self.assertEqual(result["readings"]["pres"], 977)
        self.assertEqual(result["changes_since_anchor"]["pres"], -3)
        self.assertEqual(result["observations_in_window"], 2)
        self.assertFalse(result["stale_at_as_of"])

    def test_missing_flags_and_sparse_anchor(self):
        rows = read_mts(mts([
            "NORM 1 800 25 60 980 5 8",
            "NORM 1 1020 27 -999 978 -996 10",
        ]))
        result = replay(rows, datetime(2013, 5, 20, 17, tzinfo=timezone.utc))
        self.assertIsNone(result["anchor_utc"])
        self.assertIsNone(result["readings"]["relh"])
        self.assertIsNone(result["readings"]["dewpoint_derived_c"])
        self.assertIsNone(result["changes_since_anchor"]["pres"])
        self.assertFalse(result["stale_at_as_of"])

    def test_rejects_malformed_count_and_duplicate_time(self):
        with self.assertRaises(ValueError):
            read_mts(mts(["NORM 1 840 25 60 980 5"]))
        with self.assertRaises(ValueError):
            read_mts(mts(["NORM 1 840 25 60 980 5 8", "NORM 1 840 25 60 980 5 8"]))

    def test_utc_day_and_as_of_are_required(self):
        rows = read_mts(mts(["NORM 1 1020 27 65 978 7 10"]))
        with self.assertRaises(ValueError):
            replay(rows, datetime(2013, 5, 21, 17, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            replay(rows, datetime(2013, 5, 20, 17, tzinfo=timezone.utc), timedelta(0))


if __name__ == "__main__":
    unittest.main()
