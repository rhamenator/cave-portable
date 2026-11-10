import unittest
from datetime import datetime, timezone

from scripts.outlook_replay import point_outlook


class OutlookReplayTests(unittest.TestCase):
    def test_never_uses_an_outlook_issued_after_as_of_time(self):
        geometry = {"type": "Polygon", "coordinates": [[(-100, 30), (-90, 30), (-90, 40), (-100, 40), (-100, 30)]]}
        base = {"TYPE": "C", "DAY": 1, "CYCLE": 16, "ISSUE": "202404261630", "EXPIRE": "202404271200"}
        rows = [(dict(base, PRODISS="202404261630", CATEGORY="CATEGORICAL", THRESHOLD="SLGT"), geometry),
                (dict(base, PRODISS="202404261955", CATEGORY="CATEGORICAL", THRESHOLD="ENH"), geometry)]
        as_of = datetime(2024, 4, 26, 17, tzinfo=timezone.utc)
        target = datetime(2024, 4, 26, 21, tzinfo=timezone.utc)
        result = point_outlook(rows, 35, -95, as_of, target)
        self.assertEqual(result["category"], "SLGT")
        self.assertEqual(result["issued_utc"], "2024-04-26T16:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
