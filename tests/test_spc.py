import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cave_portable import spc
from cave_portable.data import DataError


class SpcTests(unittest.TestCase):
    NOW = datetime(2026, 11, 9, 21, tzinfo=timezone.utc)
    TIMING = {"issue": "202611091954", "valid": "202611092000", "expire": "202611101200"}

    @patch.object(spc, "_identify")
    @patch.object(spc, "_query")
    def test_point_guidance_uses_highest_intersecting_official_values(self, query, identify):
        query.return_value = [dict(self.TIMING, dn=2)]
        identify.return_value = {layer: [dict(self.TIMING, dn=value) for value in levels]
                                 for layer, levels in {1: [2, 4], 3: [2], 5: [5, 15], 7: []}.items()}
        guidance = spc.point_guidance(42.7761, -84.5997, self.NOW)
        self.assertEqual((guidance.category, guidance.tornado, guidance.hail, guidance.wind),
                         ("Slight", 2, 15, None))
        self.assertIn("Hail: 15%", guidance.summary("KLAN"))
        self.assertIn("Issued 09 Nov 19:54 UTC", guidance.summary("KLAN"))

    @patch.object(spc, "_query")
    def test_expired_outlook_is_not_described_as_no_risk(self, query):
        query.return_value = [dict(self.TIMING, dn=2)]
        with self.assertRaisesRegex(DataError, "outside its valid period"):
            spc.point_guidance(42.7761, -84.5997, datetime(2026, 11, 10, 13, tzinfo=timezone.utc))

    @patch.object(spc, "_identify")
    @patch.object(spc, "_query")
    def test_mismatched_hazard_issue_is_rejected(self, query, identify):
        query.return_value = [dict(self.TIMING, dn=2)]
        identify.return_value = {1: [dict(self.TIMING, dn=3)],
                                 3: [dict(self.TIMING, issue="202611091600", dn=2)], 5: [], 7: []}
        with self.assertRaisesRegex(DataError, "did not match"):
            spc.point_guidance(42.7761, -84.5997, self.NOW)


if __name__ == "__main__":
    unittest.main()
