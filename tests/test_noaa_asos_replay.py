import unittest
from datetime import datetime, timedelta, timezone

from scripts.noaa_asos_replay import parse_csv, request_url, summarize


HEADER = "station,station_name,valid(UTC),tmpf,dwpf,sknt,gust_sknt,pres1\n"


class AsosReplayTests(unittest.TestCase):
    def test_as_of_excludes_future_and_uses_actual_anchor(self):
        rows = parse_csv(HEADER + """OMA,Omaha,2024-04-26 17:00,57,56,19,27,28.415
OMA,Omaha,2024-04-26 20:00,66,61,23,32,28.360
OMA,Omaha,2024-04-26 20:29,67,62,25,35,28.352
OMA,Omaha,2024-04-26 20:31,80,70,40,60,28.100
""", "OMA")
        result = summarize(rows, "OMA", datetime(2024, 4, 26, 20, 30, tzinfo=timezone.utc),
                           timedelta(hours=3, minutes=30))
        self.assertEqual(result["latest_observation_utc"], "2024-04-26T20:29:00+00:00")
        self.assertEqual(result["anchor_utc"], "2024-04-26T17:00:00+00:00")
        self.assertEqual(result["maxima_in_window"]["gust_sknt"], 35)
        self.assertEqual(result["changes_since_anchor"]["pres1"], -0.063)

    def test_missing_values_and_gap_are_visible(self):
        rows = parse_csv(HEADER + """LAN,Lansing,2023-08-25 00:00,70,60,8,M,29.1
LAN,Lansing,2023-08-25 00:30,M,61,10,15,M
""", "LAN")
        result = summarize(rows, "LAN", datetime(2023, 8, 25, 0, 30, tzinfo=timezone.utc),
                           timedelta(minutes=30))
        self.assertEqual(result["max_observed_gap_minutes"], 30)
        self.assertEqual(result["missing_value_counts"]["tmpf"], 1)
        self.assertIsNone(result["changes_since_anchor"]["pres1"])
        self.assertLess(result["coverage_fraction"], 0.1)

    def test_empty_archive_returns_explicit_gap(self):
        rows = parse_csv(HEADER, "OKC")
        result = summarize(rows, "OKC", datetime(2013, 5, 20, 17, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "no_observations")

    def test_rejects_wrong_station_and_injection(self):
        with self.assertRaises(ValueError):
            parse_csv(HEADER + "OKC,Oklahoma City,2013-05-20 17:00,70,60,8,10,29\n", "OMA")
        with self.assertRaises(ValueError):
            request_url("OMA&station=OKC", datetime(2024, 4, 26, tzinfo=timezone.utc),
                        datetime(2024, 4, 27, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
