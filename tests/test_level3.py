import bz2
import struct
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cave_portable import level3, model, mrms
from cave_portable.data import DataError


def synthetic_cc():
    packet = struct.pack(">HHHhhHH", 16, 0, 4, 0, 0, 1000, 1)
    packet += struct.pack(">HHH", 4, 0, 3600) + bytes((0, 200, 220, 240))
    block = struct.pack(">hhIH", -1, 1, 16 + len(packet), 1)
    block += struct.pack(">hI", -1, len(packet)) + packet
    compressed = bz2.compress(block)
    pdb = bytearray(102)
    struct.pack_into(">h", pdb, 0, -1)
    struct.pack_into(">ii", pdb, 2, 42894, -85545)
    struct.pack_into(">h", pdb, 12, 161)
    struct.pack_into(">h", pdb, 40, 5)
    struct.pack_into(">ff", pdb, 42, 300.0, -60.5)
    struct.pack_into(">H", pdb, 54, 2)
    when = datetime(2026, 11, 10, tzinfo=timezone.utc)
    julian = (when - datetime(1970, 1, 1, tzinfo=timezone.utc)).days + 1
    message = struct.pack(">HHIIHHH", 161, julian, 60, 120 + len(compressed), 369, 0, 3)
    return b"SDUS83 KGRR 100000\r\r\nN0CGRR\r\r\n" + message + pdb + compressed


class Level3Tests(unittest.TestCase):
    def test_decodes_numeric_cc_and_rejects_wrong_product(self):
        sample = synthetic_cc()
        field = level3.decode(sample, "GRR", "N0C")
        self.assertEqual((field.site, field.product, len(field.radials)), ("GRR", "N0C", 1))
        self.assertEqual(field.time, datetime(2026, 11, 10, 0, 1, tzinfo=timezone.utc))
        self.assertAlmostEqual(field.value_at(42.894 + 0.3 / 111.32, -85.545), (200 + 60.5) / 300, places=3)
        with self.assertRaises(DataError):
            level3.decode(sample, "GRR", "N0B")
        with self.assertRaises(DataError):
            level3.decode(sample[:150], "GRR", "N0C")

    @patch.object(level3, "_day_keys")
    def test_recent_keys_exclude_future_and_stale_scans(self, listing):
        listing.return_value = ["GRR_N0C_2026_11_10_00_01_00",
                                "GRR_N0C_2026_11_10_00_05_00",
                                "GRR_N0C_2026_11_10_01_00_00"]
        now = datetime(2026, 11, 10, 0, 10, tzinfo=timezone.utc)
        self.assertEqual(level3.recent_keys("GRR", "N0C", now),
                         ["GRR_N0C_2026_11_10_00_05_00", "GRR_N0C_2026_11_10_00_01_00"])

    @patch.object(model, "_fetch")
    def test_gfs_catalog_has_explicit_run_paths(self, fetch):
        fetch.return_value = (b'<catalog><dataset urlPath="grib/NCEP/GFS/Global_0p25deg/'
                              b'GFS_Global_0p25deg_20261109_1200.grib2"/>'
                              b'<dataset urlPath="grib/NCEP/GFS/Global_0p25deg/'
                              b'GFS_Global_0p25deg_20261109_1800.grib2"/></catalog>')
        runs = model._runs(999999)
        self.assertEqual([item[0].hour for item in runs], [18, 12])

    def test_mrms_labels_estimate_and_missing_values(self):
        time = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertIn("no valid MESH estimate", mrms.HailReadout(time, None, None).summary("KLAN"))
        self.assertIn("Algorithmic hail estimate", mrms.HailReadout(time, 25.4, 50.8).summary("KLAN"))


if __name__ == "__main__":
    unittest.main()
