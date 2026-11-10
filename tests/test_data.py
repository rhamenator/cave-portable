import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cave_portable import data


class DataTests(unittest.TestCase):
    @patch.object(data, "_json")
    def test_station_trend_uses_report_times_and_rejects_stale_history(self, fetch):
        now = datetime(2026, 11, 10, 4, tzinfo=timezone.utc)
        fetch.return_value = [
            {"icaoId": "KLAN", "reportTime": "2026-11-10T00:00:00Z", "altim": 1018, "dewp": 7},
            {"icaoId": "KLAN", "reportTime": "2026-11-10T03:00:00Z", "altim": 1015, "dewp": 8},
            {"icaoId": "KGRR", "reportTime": "2026-11-10T03:30:00Z", "altim": 980, "dewp": 15},
        ]
        trend = data.station_trend("KLAN", now)
        self.assertEqual(trend.report_count, 2)
        self.assertEqual(trend.altimeter_change_hpa_per_hour, -1)
        self.assertIn("not a severe-weather forecast", trend.summary())
        with self.assertRaisesRegex(data.DataError, "insufficient"):
            data.station_trend("KLAN", now + timedelta(hours=2))

    def test_station_validation_blocks_url_injection(self):
        self.assertEqual(data.validate_station(" kdtw "), "KDTW")
        for invalid in ("", "DTW", "KDTW&x=1", "../a", "éAAA"):
            with self.assertRaises(data.DataError):
                data.validate_station(invalid)

    @patch.object(data, "_fetch")
    def test_metar_normalization(self, fetch):
        fetch.return_value = json.dumps([{"icaoId": "KDTW", "name": "Detroit", "reportTime": "2026-11-09T17:00:00Z", "temp": 11.1, "wdir": 260, "wspd": 7, "fltCat": "VFR", "rawOb": "METAR KDTW"}]).encode()
        row = data.metars(("KDTW",))[0]
        self.assertEqual(row.station, "KDTW")
        self.assertEqual(row.observed, "09 Nov 17:00 UTC")
        self.assertEqual(row.wind, "260° 7 kt")

    @patch.object(data, "_fetch")
    def test_alerts_limit(self, fetch):
        fetch.return_value = json.dumps({"features": [{"properties": {"event": "Test", "headline": "Headline", "description": "Detail"}}]}).encode()
        self.assertEqual(data.alerts("mi"), [("Test", "Headline", "Detail")])
        with self.assertRaises(data.DataError):
            data.alerts("MI&x")

    def test_images_are_allowlisted(self):
        with self.assertRaises(data.DataError):
            data.image("https://example.com/image.png")

    @patch.object(data, "_fetch")
    def test_point_alerts_select_actual_severe_alerts(self, fetch):
        fetch.return_value = json.dumps({"features": [
            {"id": "a", "properties": {"status": "Actual", "severity": "Severe", "event": "Severe Thunderstorm Warning", "headline": "Warning", "description": "Details"}},
            {"id": "b", "properties": {"status": "Actual", "severity": "Minor", "event": "Advisory"}},
            {"id": "c", "properties": {"status": "Test", "severity": "Extreme", "event": "Test"}},
            {"id": "d", "properties": {"status": "Actual", "severity": "Moderate", "event": "Tornado Watch"}},
        ]}).encode()
        alerts = data.point_alerts(42.23, -83.33)
        self.assertEqual([(item.identifier, item.level) for item in alerts],
                         [("a", "warning"), ("b", "advisory"), ("d", "watch")])

    @patch.object(data, "_json")
    def test_winter_grid_reports_period_peak_and_source_time(self, fetch):
        now = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
        point = {"properties": {"forecastGridData": "https://api.weather.gov/gridpoints/GRR/78,41"}}
        grid = {"properties": {
            "updateTime": "2026-11-10T05:00:00+00:00",
            "snowfallAmount": {"uom": "wmoUnit:mm", "values": [
                {"validTime": "2026-11-10T06:00:00+00:00/PT6H", "value": 25.4},
                {"validTime": "2026-11-10T12:00:00+00:00/PT6H", "value": 12.7}]},
            "iceAccumulation": {"uom": "wmoUnit:mm", "values": [
                {"validTime": "2026-11-10T06:00:00+00:00/PT6H", "value": 2.54}]},
            "windGust": {"uom": "wmoUnit:km_h-1", "values": [
                {"validTime": "2026-11-10T06:00:00+00:00/PT1H", "value": 64.3738}]},
        }}
        fetch.side_effect = [point, grid]
        summary = data.winter_forecast(42.7761, -84.5997, now)
        self.assertIn("snow 1.0 in", summary)
        self.assertIn("ice 0.1 in", summary)
        self.assertIn("gust 40 mph", summary)
        self.assertIn("not a 48 h total", summary)

    @patch.object(data, "_json")
    def test_winter_grid_metric_and_hybrid_units(self, fetch):
        now = datetime(2026, 11, 10, 6, tzinfo=timezone.utc)
        point = {"properties": {"forecastGridData": "https://api.weather.gov/gridpoints/GRR/78,41"}}
        grid = {"properties": {"updateTime": "2026-11-10T05:00:00+00:00",
            "snowfallAmount": {"uom": "wmoUnit:mm", "values": [{"validTime": "2026-11-10T06:00:00+00:00/PT6H", "value": 25.4}]},
            "windGust": {"uom": "wmoUnit:km_h-1", "values": [{"validTime": "2026-11-10T06:00:00+00:00/PT6H", "value": 64}]}}}
        fetch.side_effect = [point, grid, point, grid]
        self.assertIn("snow 2.5 cm", data.winter_forecast(42.77, -84.59, now, "Metric"))
        hybrid = data.winter_forecast(42.77, -84.59, now, "Hybrid")
        self.assertIn("snow 1.0 in", hybrid)
        self.assertIn("gust 64 km/h", hybrid)

    @patch.object(data, "_json")
    def test_nws_hourly_requests_source_units(self, fetch):
        point = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/GRR/78,41/forecast/hourly"}}
        now = datetime.now(timezone.utc)
        hourly = {"properties": {"updateTime": now.isoformat(), "periods": [{
            "startTime": now.isoformat(), "temperature": 7, "temperatureUnit": "C",
            "shortForecast": "Cloudy"}]}}
        fetch.side_effect = [point, hourly]
        self.assertIn("7°C", data.hourly_forecast(42.77, -84.59, "Metric"))
        self.assertTrue(fetch.call_args.args[0].endswith("?units=si"))

    @patch.object(data, "_json")
    def test_uk_hybrid_converts_nws_si_forecast_wind(self, fetch):
        now = datetime.now(timezone.utc)
        point = {"properties": {"forecast": "https://api.weather.gov/gridpoints/GRR/78,41/forecast"}}
        forecast = {"properties": {"updateTime": now.isoformat(), "periods": [{
            "name": "Today", "detailedForecast": "High near 7. Wind 10 to 15 km/h, gusting to 30 km/h."}]}}
        fetch.side_effect = [point, forecast]
        result = data.point_forecast(42.77, -84.59, "UK Hybrid")
        self.assertIn("6 to 9 mph", result)
        self.assertIn("19 mph", result)
        self.assertTrue(fetch.call_args.args[0].endswith("?units=si"))

    def test_winter_weather_codes_and_mixed_duration(self):
        now = datetime(2026, 11, 10, 6, tzinfo=timezone.utc)
        field = {"values": [{"validTime": "2026-11-10T05:00:00+00:00/P1DT13H",
                             "value": [{"weather": "freezing_rain"}, {"weather": "snow"}]}]}
        self.assertEqual(len(data._winter_types(field, now)), 2)
        peak = data._grid_peak({"values": [{"validTime": "2026-11-10T05:00:00+00:00/P1DT13H", "value": 25.4}]}, now)
        self.assertEqual(peak[0], 25.4)

    @patch.object(data, "_json")
    def test_canadian_city_forecast_keeps_issued_wording(self, fetch):
        now = datetime(2026, 11, 10, 6, tzinfo=timezone.utc)
        fetch.return_value = {"features": [{"geometry": {"coordinates": [-83.03, 42.31]},
            "properties": {"name": {"en": "Windsor"}, "forecastGroup": {
                "timestamp": {"en": "2026-11-10T02:00:00+00:00"},
                "forecasts": [{"period": {"textForecastName": {"en": "Tonight"}},
                               "textSummary": {"en": "Snow beginning overnight. Amount 5 cm."}}]}}}]}
        summary = data.canadian_winter_forecast(42.31, -83.03, now)
        self.assertIn("Windsor", summary)
        self.assertIn("Amount 5 cm", summary)
        self.assertIn("not a point accumulation estimate", summary)

    @patch.object(data, "_json")
    def test_canadian_alerts_filter_warning_and_expiry(self, fetch):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        fetch.return_value = {"features": [
            {"id": "a", "properties": {"alert_type": "warning", "status_en": "continued", "expiration_datetime": future, "alert_name_en": "Snowfall warning"}},
            {"id": "b", "properties": {"alert_type": "statement", "expiration_datetime": future}},
            {"id": "c", "properties": {"alert_type": "warning", "expiration_datetime": past}},
            {"id": "d", "properties": {"alert_type": "watch", "expiration_datetime": future, "alert_name_en": "Thunderstorm watch"}},
        ]}
        self.assertEqual([(x.identifier, x.level) for x in data.canadian_point_alerts(45.42, -75.70)],
                         [("a", "warning"), ("d", "watch")])

    @patch.object(data, "_json")
    def test_local_weather_rejects_stale_and_selects_nearest(self, fetch):
        now = datetime.now(timezone.utc)
        fetch.return_value = [
            {"icaoId": "OLD", "lat": 45.42, "lon": -75.70, "temp": 3, "reportTime": (now - timedelta(hours=4)).isoformat()},
            {"icaoId": "CYOW", "lat": 45.32, "lon": -75.67, "temp": 9, "reportTime": now.isoformat()},
            {"icaoId": "CYUL", "lat": 45.47, "lon": -73.74, "temp": 8, "reportTime": now.isoformat()},
        ]
        self.assertEqual(data.nearby_metar(45.42, -75.70).station, "CYOW")

    @patch.object(data, "_fetch_with_time")
    def test_stale_image_is_rejected(self, fetch):
        fetch.return_value = (b"GIF89a" + b"\0" * 20, datetime.now(timezone.utc) - timedelta(hours=2))
        with self.assertRaisesRegex(data.DataError, "stale"):
            data.image_record(data.RADAR_URL)

    @patch.object(data, "_json")
    def test_point_forecast_reads_current_nws_grid_and_rejects_foreign_url(self, fetch):
        fetch.side_effect = [
            {"properties": {"forecast": "https://api.weather.gov/gridpoints/GRR/78,41/forecast"}},
            {"properties": {"updateTime": datetime.now(timezone.utc).isoformat(),
                            "periods": [{"name": "Tonight", "detailedForecast": "Partly cloudy."}]}}
        ]
        self.assertIn("Tonight: Partly cloudy.", data.point_forecast(42.7761, -84.5997))
        fetch.reset_mock(side_effect=True)
        fetch.return_value = {"properties": {"forecast": "https://example.com/unsafe"}}
        with self.assertRaisesRegex(data.DataError, "URL was invalid"):
            data.point_forecast(42.7761, -84.5997)

    @patch.object(data, "_json")
    def test_hourly_forecast_is_readable_and_checks_grid_url(self, fetch):
        fetch.side_effect = [
            {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/GRR/78,41/forecast/hourly"}},
            {"properties": {"updateTime": datetime.now(timezone.utc).isoformat(), "periods": [
                {"startTime": "2026-11-09T19:00:00-05:00", "temperature": 41,
                 "temperatureUnit": "F", "shortForecast": "Cloudy",
                 "probabilityOfPrecipitation": {"value": 20}}]}}
        ]
        self.assertIn("7 PM: 41°F, Cloudy, 20% precip", data.hourly_forecast(42.7761, -84.5997))
        fetch.reset_mock(side_effect=True)
        fetch.return_value = {"properties": {"forecastHourly": "https://example.com/unsafe"}}
        with self.assertRaisesRegex(data.DataError, "URL was invalid"):
            data.hourly_forecast(42.7761, -84.5997)


if __name__ == "__main__":
    unittest.main()
