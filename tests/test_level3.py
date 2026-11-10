import bz2
import struct
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cave_portable import level3, model, mrms, overlays, radar
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


def synthetic_digital(product="N0G", number=154, minimum=-64, increment=1):
    packet = struct.pack(">HHHhhHH", 16, 0, 4, 0, 0, 1000, 1)
    packet += struct.pack(">HHH", 4, 0, 3600) + bytes((0, 2, 3, 4))
    block = struct.pack(">hhIH", -1, 1, 16 + len(packet), 1)
    block += struct.pack(">hI", -1, len(packet)) + packet
    compressed = bz2.compress(block)
    pdb = bytearray(102)
    struct.pack_into(">hii", pdb, 0, -1, 42894, -85545)
    struct.pack_into(">h", pdb, 12, number)
    struct.pack_into(">h", pdb, 40, 5)
    struct.pack_into(">hh", pdb, 42, minimum * 10, increment * 10)
    when = datetime(2026, 11, 10, tzinfo=timezone.utc)
    julian = (when - datetime(1970, 1, 1, tzinfo=timezone.utc)).days + 1
    message = struct.pack(">HHIIHHH", number, julian, 60, 120 + len(compressed), 369, 0, 3)
    return b"SDUS83 KGRR 100000\r\r\n" + product.encode() + b"GRR\r\r\n" + message + pdb + compressed


class Level3Tests(unittest.TestCase):
    def test_digital_velocity_and_reflectivity_start_at_code_two(self):
        for product, number, minimum in (("N0G", 154, -64), ("N2U", 99, -64), ("N0B", 153, -32)):
            with self.subTest(product=product):
                field = level3.decode(synthetic_digital(product, number, minimum), "GRR", product)
                self.assertEqual(field._value(2), minimum)
                self.assertEqual(field._value(3), minimum + 1)

    def test_tilt_product_codes(self):
        self.assertEqual(level3.product_for_tilt("Digital velocity", 0)[:2], ("N0G", 154))
        self.assertEqual(level3.product_for_tilt("Digital velocity", 3)[:2], ("N3U", 99))
        self.assertEqual(level3.product_for_tilt("Correlation coefficient (CC)", 2)[:2], ("N2C", 161))
        with self.assertRaises(DataError):
            level3.product_for_tilt("Digital velocity", 4)

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

    def test_wmo_office_can_differ_from_radar_site(self):
        sample = synthetic_cc().replace(b"KGRR", b"KJAN").replace(b"N0CGRR", b"N0CDGX")
        field = level3.decode(sample, "DGX", "N0C")
        self.assertEqual(field.site, "DGX")

    @patch.object(level3, "_day_keys")
    def test_recent_keys_exclude_future_and_stale_scans(self, listing):
        listing.return_value = ["GRR_N0C_2026_11_10_00_01_00",
                                "GRR_N0C_2026_11_10_00_05_00",
                                "GRR_N0C_2026_11_10_01_00_00"]
        now = datetime(2026, 11, 10, 0, 10, tzinfo=timezone.utc)
        self.assertEqual(level3.recent_keys("GRR", "N0C", now),
                         ["GRR_N0C_2026_11_10_00_05_00", "GRR_N0C_2026_11_10_00_01_00"])

    @patch.object(level3, "_fetch")
    @patch.object(level3, "recent_keys")
    def test_volume_match_rejects_unrelated_product_frame(self, listing, fetch):
        scan = datetime(2026, 11, 10, 0, 1, tzinfo=timezone.utc)
        listing.return_value = ["GRR_N0C_2026_11_10_00_06_00",
                                "GRR_N0C_2026_11_10_00_01_00"]
        fetch.return_value = synthetic_cc()
        field = level3.fetch_field_near("GRR", "N0C", scan, scan + timedelta(minutes=8))
        self.assertEqual(field.time, scan)
        self.assertIn("00_01_00", fetch.call_args.args[0])
        with self.assertRaises(DataError):
            level3.fetch_field_near("GRR", "N0C", scan - timedelta(minutes=4),
                                    scan + timedelta(minutes=8))

    @patch.object(overlays, "draw")
    @patch.object(level3, "render")
    @patch.object(level3, "fetch_field")
    def test_saved_point_drives_warning_query_even_when_radar_is_elsewhere(self, fetch, render, draw):
        from PIL import Image
        field = level3.decode(synthetic_digital("N0B", 153, -32), "GRR", "N0B")
        fetch.return_value = field
        render.return_value = Image.new("RGB", (200, 100))
        draw.side_effect = lambda image, *args, **kwargs: (image, "alerts checked")
        level3.field_map("GRR · Grand Rapids", "Digital reflectivity", radar.SITES,
                         alert_point=(42.7761, -84.5997))
        self.assertEqual(draw.call_args.args[2], (42.7761, -84.5997))
        level3.field_map("GRR · Grand Rapids", "Digital reflectivity", radar.SITES,
                         alert_point=(43.65, -79.38), include_us_alerts=False)
        self.assertFalse(draw.call_args.kwargs["include_local_alerts"])
        self.assertEqual(draw.call_args.kwargs["radar_point"], (field.latitude, field.longitude))

    def test_windsor_selects_detroit_radar_from_saved_point(self):
        self.assertEqual(radar.nearest_site(42.331, -82.976, radar.SITES), "DTX · Detroit")

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
