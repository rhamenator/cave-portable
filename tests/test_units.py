import unittest

from cave_portable import units


class UnitTests(unittest.TestCase):
    def test_weather_display_profiles(self):
        self.assertEqual(units.temperature(0, "US"), "32.0 °F")
        self.assertEqual(units.temperature(0, "Metric"), "0.0 °C")
        self.assertEqual(units.wind("270° 10 kt", "US"), "270° 12 mph")
        self.assertEqual(units.wind("270° 10 kt", "Hybrid"), "270° 19 km/h")
        self.assertEqual(units.visibility("10", "Metric"), "16.1")
        self.assertEqual(units.snow(25.4, "US"), "1.0 in")
        self.assertEqual(units.snow(25.4, "Metric"), "2.5 cm")
        self.assertEqual(units.ice(2.54, "Hybrid"), "0.1 in")
        self.assertEqual(units.speed_kmh(64.3738, "Metric"), "64 km/h")


if __name__ == "__main__":
    unittest.main()
