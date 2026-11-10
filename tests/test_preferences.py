import pathlib
import tempfile
import unittest
from unittest.mock import patch

from cave_portable import preferences


class PreferencesTests(unittest.TestCase):
    def test_settings_are_small_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "settings.json"
            with patch.object(preferences, "settings_path", return_value=path):
                preferences.save({"station": "kdtw", "country": "US", "postal_code": "48201", "monitor_enabled": True})
                self.assertEqual(preferences.load(), {"station": "KDTW", "country": "US", "postal_code": "48201", "street": "", "units": "Hybrid", "monitor_enabled": True})
                saved = preferences.load()
                saved["units"] = "Metric"
                preferences.save(saved)
                self.assertEqual(preferences.load()["units"], "Metric")
                saved["units"] = "UK Hybrid"
                preferences.save(saved)
                self.assertEqual(preferences.load()["units"], "UK Hybrid")

    def test_linux_autostart_is_opt_in_and_reversible(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "cave-portable.desktop"
            with patch.object(preferences.sys, "platform", "linux"), patch.object(preferences, "_startup_path", return_value=path):
                preferences.set_autostart(True)
                self.assertTrue(preferences.is_autostart_enabled())
                self.assertIn("Exec=", path.read_text())
                preferences.set_autostart(False)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
