import unittest
from datetime import timedelta
from unittest.mock import patch

from cave_portable.data import DataError
from scripts.noaa_cohort_replay import run_case


CASE = {"id": "sample", "state": "AR", "event": "Sample event",
        "reference_utc": "2023-03-31T19:18Z", "reference_kind": "surveyed onset",
        "as_of_utc": "2023-03-31T18:00Z", "station": "LIT",
        "radar_site": "LZK", "radar_as_of_utc": "2023-03-31T19:20Z",
        "source": "https://www.weather.gov/lzk/svr0323ayr.htm"}


class CohortReplayTests(unittest.TestCase):
    def test_comparison_is_same_station_seven_days_earlier(self):
        with patch("scripts.noaa_cohort_replay.station_summary", side_effect=lambda station, time: {"station": station, "as_of": time}) as summary:
            result = run_case(CASE)
        self.assertEqual(summary.call_count, 2)
        self.assertEqual(result["event_day"]["station"], result["seven_day_comparison"]["station"])
        self.assertEqual(result["event_day"]["as_of"] - result["seven_day_comparison"]["as_of"], timedelta(days=7))

    def test_radar_decoder_failure_is_reported(self):
        with patch("scripts.noaa_cohort_replay.station_summary", return_value={"status": "no_observations"}), \
             patch("scripts.noaa_cohort_replay.archived_field", side_effect=DataError("unsupported")):
            result = run_case(CASE, radar=True)
        self.assertEqual(result["radar_cc"]["status"], "unavailable_or_unsupported")

    def test_cutoff_must_precede_event_reference(self):
        case = dict(CASE, as_of_utc="2023-03-31T19:18Z")
        with self.assertRaises(ValueError):
            run_case(case)


if __name__ == "__main__":
    unittest.main()
