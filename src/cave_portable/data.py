"""Bounded, read-only requests to public NOAA weather services."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import units

USER_AGENT = "CAVE-Portable/0.4.7 (https://github.com/rhamenator/cave-portable)"
STATIONS = (
    "KSEA", "KPDX", "KSFO", "KLAX", "KLAS", "KPHX", "KSLC", "KDEN",
    "KDFW", "KIAH", "KMSP", "KORD", "KDTW", "KLAN", "KATL", "KMIA", "KBOS",
    "KJFK", "KDCA", "KCLT", "KMCI", "KSTL", "KBNA", "KMSY", "KABQ",
)
RADAR_URL = "https://radar.weather.gov/ridge/standard/CONUS_0.gif"
SATELLITE = {
    "GOES East": "https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/GEOCOLOR/1250x750.jpg",
    "GOES West": "https://cdn.star.nesdis.noaa.gov/GOES18/ABI/CONUS/GEOCOLOR/1250x750.jpg",
}
OUTLOOK = {
    "Day 1": "https://www.spc.noaa.gov/products/outlook/day1otlk.png",
    "Day 2": "https://www.spc.noaa.gov/products/outlook/day2otlk.png",
    "Day 3": "https://www.spc.noaa.gov/products/outlook/day3otlk.png",
}
MLCAPE_URL = "https://www.spc.noaa.gov/exper/mesoanalysis/s11/mlcp/mlcp.gif"
MAX_JSON = 2_000_000
MAX_IMAGE = 5_000_000
SKY = {"SKC": "Clear", "CLR": "Clear", "FEW": "Mostly clear", "SCT": "Partly cloudy", "BKN": "Mostly cloudy", "OVC": "Overcast", "VV": "Low visibility"}


class DataError(Exception):
    """A weather service could not supply usable data."""


@dataclass(frozen=True)
class Observation:
    station: str
    name: str
    observed: str
    temp_c: float | None
    wind: str
    visibility: str
    flight_category: str
    raw: str
    conditions: str = "—"
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class StationTrend:
    station: str
    latest: datetime
    span_hours: float
    report_count: int
    altimeter_change_hpa_per_hour: float
    dewpoint_c: float | None

    def summary(self, mode: str = units.DEFAULT) -> str:
        direction = ("rising" if self.altimeter_change_hpa_per_hour > .2 else
                     "falling" if self.altimeter_change_hpa_per_hour < -.2 else "steady")
        dewpoint = (f" · dewpoint {units.temperature(self.dewpoint_c, mode)}" if self.dewpoint_c is not None else "")
        pressure = (f"{abs(self.altimeter_change_hpa_per_hour) * 0.02952998:.3f} inHg/h"
                    if mode == "US" else f"{abs(self.altimeter_change_hpa_per_hour):.1f} hPa/h")
        return (f"{self.station} · {self.span_hours:.1f} h altimeter {direction}"
                f" {pressure} ({self.report_count} reports){dewpoint}"
                f" · {self.latest:%H:%M UTC} · observation only, not a severe-weather forecast")


@dataclass(frozen=True)
class WeatherAlert:
    identifier: str
    event: str
    headline: str
    description: str
    severity: str
    level: str = "warning"


def _fetch(url: str, maximum: int, accept: str) -> bytes:
    return _fetch_with_time(url, maximum, accept)[0]


def _fetch_with_time(url: str, maximum: int, accept: str) -> tuple[bytes, datetime | None]:
    if not url.startswith("https://"):
        raise DataError("Only HTTPS weather sources are allowed")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, "Cache-Control": "no-cache", "Pragma": "no-cache"})
    try:
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise DataError(f"Weather service returned HTTP {response.status}")
            payload = response.read(maximum + 1)
            if len(payload) > maximum:
                raise DataError("Weather response exceeded its size limit")
            modified = response.headers.get("Last-Modified")
            try:
                updated = parsedate_to_datetime(modified).astimezone(timezone.utc) if modified else None
            except (TypeError, ValueError):
                updated = None
            return payload, updated
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DataError(f"Weather service unavailable: {exc}") from exc


def _json(url: str):
    try:
        return json.loads(_fetch(url, MAX_JSON, "application/json"))
    except (ValueError, UnicodeError) as exc:
        raise DataError("Weather service returned invalid JSON") from exc


def validate_station(station: str) -> str:
    station = station.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", station):
        raise DataError("Enter a four-character ICAO station code, such as KDTW")
    return station


def _conditions(row: dict) -> str:
    weather = str(row.get("wxString") or "").strip()
    if weather:
        codes = {"TS": "Thunderstorms", "SN": "Snow", "RA": "Rain", "DZ": "Drizzle", "FG": "Fog", "BR": "Mist", "HZ": "Haze"}
        for code, label in codes.items():
            if code in weather:
                return label
        return weather[:40]
    return SKY.get(str(row.get("cover") or ""), "Conditions unavailable")


def metars(stations: tuple[str, ...] = STATIONS) -> list[Observation]:
    ids = ",".join(validate_station(s) for s in stations)
    url = "https://aviationweather.gov/api/data/metar?" + urlencode({"ids": ids, "format": "json"})
    payload = _json(url)
    if not isinstance(payload, list):
        raise DataError("Unexpected METAR response")
    return _normalize_metars(payload)


def station_trend(station: str, now: datetime | None = None) -> StationTrend:
    """Describe recent airport observations using their actual report timestamps."""
    station = validate_station(station)
    url = "https://aviationweather.gov/api/data/metar?" + urlencode({"ids": station, "format": "json", "hours": 4})
    payload = _json(url)
    if not isinstance(payload, list) or len(payload) > 300:
        raise DataError("Station history was invalid or too large")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    readings = {}
    for row in payload:
        if not isinstance(row, dict) or row.get("icaoId") != station:
            continue
        try:
            timestamp = datetime.fromisoformat(str(row["reportTime"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            altimeter = float(row["altim"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-timedelta(minutes=5) <= current - timestamp <= timedelta(hours=4)
                and 870 <= altimeter <= 1080 and math.isfinite(altimeter)):
            continue
        dewpoint = row.get("dewp")
        if not isinstance(dewpoint, (int, float)) or not math.isfinite(dewpoint) or not -80 <= dewpoint <= 50:
            dewpoint = None
        readings[timestamp] = (altimeter, dewpoint)
    ordered = sorted(readings.items())
    if len(ordered) < 2 or current - ordered[-1][0] > timedelta(minutes=90):
        raise DataError("Recent station history is insufficient")
    latest_time, (latest_altimeter, latest_dewpoint) = ordered[-1]
    oldest_time, (oldest_altimeter, _) = ordered[0]
    hours = (latest_time - oldest_time).total_seconds() / 3600
    if hours < 1.5:
        raise DataError("Station history does not span enough time")
    return StationTrend(station, latest_time, hours, len(ordered),
                        (latest_altimeter - oldest_altimeter) / hours, latest_dewpoint)


def _normalize_metars(payload: list) -> list[Observation]:
    output = []
    for row in payload[:1000]:
        if not isinstance(row, dict):
            continue
        observed = row.get("reportTime") or ""
        if observed:
            try:
                observed = datetime.fromisoformat(observed.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%d %b %H:%M UTC")
            except ValueError:
                observed = "Unknown time"
        direction, speed = row.get("wdir"), row.get("wspd")
        wind = "—" if speed is None else f"{direction if direction is not None else 'VRB'}° {speed} kt"
        output.append(Observation(
            station=str(row.get("icaoId") or "")[:8], name=str(row.get("name") or "")[:90],
            observed=observed, temp_c=row.get("temp") if isinstance(row.get("temp"), (int, float)) else None,
            wind=wind, visibility=str(row.get("visib") or "—"),
            flight_category=str(row.get("fltCat") or "—"), raw=str(row.get("rawOb") or "")[:700],
            conditions=_conditions(row),
            lat=float(row["lat"]) if isinstance(row.get("lat"), (int, float)) else None,
            lon=float(row["lon"]) if isinstance(row.get("lon"), (int, float)) else None,
        ))
    return output


def nearby_metar(lat: float, lon: float) -> Observation:
    """Use the nearest reporting airport; never label it as a postal observation."""
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise DataError("Invalid weather location")
    box = f"{max(-90, lat-1.5):.3f},{max(-180, lon-1.5):.3f},{min(90, lat+1.5):.3f},{min(180, lon+1.5):.3f}"
    payload = _json("https://aviationweather.gov/api/data/metar?" + urlencode({"bbox": box, "format": "json"}))
    if not isinstance(payload, list):
        raise DataError("Unexpected nearby METAR response")
    recent = []
    now = datetime.now(timezone.utc)
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        try:
            observed = datetime.fromisoformat(str(raw["reportTime"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        age = (now - observed).total_seconds()
        if -300 <= age <= 2 * 3600:
            recent.append(raw)
    rows = [row for row in _normalize_metars(recent) if row.lat is not None and row.lon is not None and row.temp_c is not None]
    if not rows:
        raise DataError("No recent nearby airport observation available")
    return min(rows, key=lambda row: (row.lat-lat)**2 + ((row.lon-lon)*math.cos(math.radians(lat)))**2)


def taf(station: str) -> str:
    url = "https://aviationweather.gov/api/data/taf?" + urlencode({"ids": validate_station(station), "format": "json"})
    payload = _json(url)
    if not isinstance(payload, list):
        raise DataError("Unexpected TAF response")
    return str(payload[0].get("rawTAF") or "No forecast available")[:5000] if payload else "No forecast available"


def point_forecast(lat: float, lon: float, mode: str = "US") -> str:
    """Readable NWS point forecast from its current WFO grid mapping."""
    if not (math.isfinite(lat) and math.isfinite(lon) and 24 <= lat <= 50 and -126 <= lon <= -66):
        raise DataError("NWS point forecast covers the contiguous US")
    point = _json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    props = point.get("properties") if isinstance(point, dict) else None
    url = props.get("forecast") if isinstance(props, dict) else None
    if not isinstance(url, str) or not re.fullmatch(
        r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+/forecast", url):
        raise DataError("NWS forecast grid URL was invalid")
    forecast = _json(url + "?units=" + ("us" if mode == "US" else "si"))
    props = forecast.get("properties") if isinstance(forecast, dict) else None
    periods = props.get("periods") if isinstance(props, dict) else None
    if not isinstance(periods, list) or not periods:
        raise DataError("NWS point forecast was unavailable")
    try:
        updated = datetime.fromisoformat(str(props["updateTime"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("NWS point forecast time was invalid") from exc
    if datetime.now(timezone.utc) - updated > timedelta(hours=18):
        raise DataError("NWS point forecast is stale")
    lines = []
    for period in periods[:2]:
        if not isinstance(period, dict):
            continue
        name, detail = str(period.get("name") or "").strip(), str(period.get("detailedForecast") or "").strip()
        if name and detail:
            lines.append(f"{name}: {units.nws_wind_text(detail, mode)[:160]}")
    if not lines:
        raise DataError("NWS point forecast had no readable periods")
    display_units = {"US": "°F, mph", "Metric": "°C, km/h",
                     "Hybrid": "°C, km/h", "UK Hybrid": "°C, mph"}.get(mode, "source units")
    return f"NWS point forecast ({display_units}) · updated {updated:%d %b %H:%M UTC}\n" + "\n".join(lines)


def hourly_forecast(lat: float, lon: float, mode: str = "US") -> str:
    """Three readable local hours from the current NWS forecast grid."""
    if not (math.isfinite(lat) and math.isfinite(lon) and 24 <= lat <= 50 and -126 <= lon <= -66):
        raise DataError("NWS hourly forecast covers the contiguous US")
    point = _json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    props = point.get("properties") if isinstance(point, dict) else None
    url = props.get("forecastHourly") if isinstance(props, dict) else None
    if not isinstance(url, str) or not re.fullmatch(
        r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+/forecast/hourly", url):
        raise DataError("NWS hourly forecast grid URL was invalid")
    forecast = _json(url + "?units=" + ("us" if mode == "US" else "si"))
    props = forecast.get("properties") if isinstance(forecast, dict) else None
    periods = props.get("periods") if isinstance(props, dict) else None
    if not isinstance(periods, list) or not periods:
        raise DataError("NWS hourly forecast was unavailable")
    try:
        updated = datetime.fromisoformat(str(props["updateTime"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("NWS hourly forecast time was invalid") from exc
    if datetime.now(timezone.utc) - updated > timedelta(hours=18):
        raise DataError("NWS hourly forecast is stale")
    lines = []
    for period in periods[:3]:
        if not isinstance(period, dict):
            continue
        try:
            when = datetime.fromisoformat(str(period["startTime"]).replace("Z", "+00:00"))
            temperature = int(period["temperature"])
        except (KeyError, TypeError, ValueError):
            continue
        unit = str(period.get("temperatureUnit") or "")
        if unit not in ("F", "C"):
            continue
        condition = str(period.get("shortForecast") or "conditions unavailable")[:60]
        probability = period.get("probabilityOfPrecipitation")
        chance = probability.get("value") if isinstance(probability, dict) else None
        chance_text = f", {int(chance)}% precip" if isinstance(chance, (int, float)) and 0 <= chance <= 100 else ""
        lines.append(f"{when.strftime('%I %p').lstrip('0')}: {temperature}°{unit}, {condition}{chance_text}")
    if not lines:
        raise DataError("NWS hourly forecast had no usable periods")
    return f"Next hours · NWS updated {updated:%d %b %H:%M UTC}: " + " · ".join(lines)


def _grid_peak(field: dict, now: datetime, hours: int = 48):
    """Largest source forecast interval intersecting the window, not a total."""
    if not isinstance(field, dict) or not isinstance(field.get("values"), list):
        return None
    choices = []
    for entry in field["values"][:500]:
        if not isinstance(entry, dict) or not isinstance(entry.get("validTime"), str):
            continue
        interval = _grid_interval(entry["validTime"])
        if interval is None:
            continue
        start, end = interval
        value = entry.get("value")
        if (end <= now or start >= now + timedelta(hours=hours)
                or not isinstance(value, (int, float)) or not math.isfinite(value)):
            continue
        choices.append((float(value), start, end))
    return max(choices, key=lambda item: (item[0], item[1])) if choices else None


def _grid_interval(value: str):
    try:
        start_text, duration = value.split("/", 1)
        start = datetime.fromisoformat(start_text.replace("Z", "+00:00")).astimezone(timezone.utc)
        match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration)
        if match is None:
            return None
        span = timedelta(days=int(match[1] or 0), hours=int(match[2] or 0), minutes=int(match[3] or 0))
        return (start, start + span) if span > timedelta(0) else None
    except (ValueError, TypeError):
        return None


def _winter_types(field: dict, now: datetime):
    """NWS categorical weather types, with the earliest intersecting valid interval."""
    names = {"rain": "rain", "rain_showers": "rain showers", "snow": "snow",
             "snow_showers": "snow showers", "freezing_rain": "freezing rain",
             "freezing_drizzle": "freezing drizzle", "ice_pellets": "ice pellets"}
    found = {}
    for entry in (field.get("values", []) if isinstance(field, dict) else [])[:500]:
        interval = _grid_interval(entry.get("validTime", "")) if isinstance(entry, dict) else None
        if not interval or interval[1] <= now or interval[0] >= now + timedelta(hours=48):
            continue
        for condition in entry.get("value") or []:
            if not isinstance(condition, dict):
                continue
            name = names.get(str(condition.get("weather", "")).lower())
            if name and (name not in found or interval[0] < found[name]):
                found[name] = interval[0]
    return [f"{name} from {when:%d %b %H:%M} UTC" for name, when in sorted(found.items(), key=lambda x: x[1])]


def winter_forecast(lat: float, lon: float, now: datetime | None = None,
                    mode: str = "US") -> str:
    """Source-attributed snow, ice, and gust peaks in NWS forecast grid periods."""
    if not (math.isfinite(lat) and math.isfinite(lon) and 24 <= lat <= 50 and -126 <= lon <= -66):
        raise DataError("NWS winter forecast grid covers the contiguous US")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    point = _json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    props = point.get("properties") if isinstance(point, dict) else None
    url = props.get("forecastGridData") if isinstance(props, dict) else None
    if not isinstance(url, str) or not re.fullmatch(r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+", url):
        raise DataError("NWS forecast grid address was invalid")
    grid = _json(url)
    fields = grid.get("properties") if isinstance(grid, dict) else None
    if not isinstance(fields, dict):
        raise DataError("NWS forecast grid was invalid")
    try:
        updated = datetime.fromisoformat(str(fields["updateTime"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("NWS forecast grid update time was unavailable") from exc
    if updated > current + timedelta(minutes=5) or current - updated > timedelta(hours=18):
        raise DataError("NWS forecast grid is stale")
    specs = (("snowfallAmount", "snow", "wmoUnit:mm", units.snow),
             ("iceAccumulation", "ice", "wmoUnit:mm", units.ice),
             ("windGust", "gust", "wmoUnit:km_h-1", units.speed_kmh))
    parts = []
    for key, label, unit, formatter in specs:
        field = fields.get(key)
        if not isinstance(field, dict) or field.get("uom") != unit:
            continue
        peak = _grid_peak(field, current)
        if peak is not None:
            value, start, end = peak
            parts.append(f"{label} {formatter(value, mode)} "
                         f"({start:%d %b %H:%M}–{end:%d %b %H:%M} UTC)")
    types = _winter_types(fields.get("weather"), current)
    if types:
        parts.append("forecast precipitation type: " + ", ".join(types))
    if not parts:
        raise DataError("NWS forecast grid lacked usable winter periods")
    return (f"NWS winter ingredients, next 48 h · grid updated {updated:%d %b %H:%M UTC} · "
            + "; ".join(parts) + " · largest forecast interval, not a 48 h total")


def canadian_winter_forecast(lat: float, lon: float, now: datetime | None = None) -> str:
    """Nearby ECCC city forecast wording; no extrapolated accumulation at the saved point."""
    if not (math.isfinite(lat) and math.isfinite(lon) and 41 <= lat <= 84 and -142 <= lon <= -52):
        raise DataError("ECCC city forecast location was invalid")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    features = []
    for radius in (0.2, 0.8):
        bbox = f"{lon-radius:.3f},{lat-radius:.3f},{lon+radius:.3f},{lat+radius:.3f}"
        payload = _json("https://api.weather.gc.ca/collections/citypageweather-realtime/items?" +
                        urlencode({"bbox": bbox, "limit": 20, "f": "json"}))
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise DataError("ECCC city forecast response was invalid")
        features = payload["features"]
        if features:
            break
    choices = []
    for item in features:
        coordinates = item.get("geometry", {}).get("coordinates", []) if isinstance(item, dict) else []
        if len(coordinates) < 2:
            continue
        try:
            distance = (float(coordinates[1]) - lat) ** 2 + ((float(coordinates[0]) - lon) * math.cos(math.radians(lat))) ** 2
        except (TypeError, ValueError):
            continue
        choices.append((distance, item))
    if not choices:
        raise DataError("No nearby ECCC city forecast is available")
    _distance, item = min(choices, key=lambda pair: pair[0])
    props = item.get("properties", {})
    group = props.get("forecastGroup", {})
    try:
        issued = datetime.fromisoformat(str(group["timestamp"]["en"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("ECCC city forecast issue time is unavailable") from exc
    if issued > current + timedelta(minutes=5) or current - issued > timedelta(hours=30):
        raise DataError("ECCC city forecast is stale")
    name = str(props.get("name", {}).get("en") or "nearby city")[:70]
    lines = []
    for forecast in group.get("forecasts", [])[:4]:
        if not isinstance(forecast, dict):
            continue
        period = str(forecast.get("period", {}).get("textForecastName", {}).get("en") or "Period")[:35]
        summary = str(forecast.get("textSummary", {}).get("en") or "").strip()[:350]
        if summary:
            lines.append(f"{period}: {summary}")
    if not lines:
        raise DataError("ECCC city forecast had no usable periods")
    return (f"ECCC forecast for {name} · issued {issued:%d %b %H:%M UTC} · source wording (metric) · "
            + " · ".join(lines) + " · city forecast, not a point accumulation estimate")


def alerts(state: str) -> list[tuple[str, str, str]]:
    state = state.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise DataError("Enter a two-letter US state code, such as MI")
    payload = _json("https://api.weather.gov/alerts/active?" + urlencode({"area": state}))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise DataError("Unexpected alerts response")
    result = []
    for feature in payload["features"][:100]:
        prop = feature.get("properties", {}) if isinstance(feature, dict) else {}
        result.append((str(prop.get("event") or "Alert")[:100], str(prop.get("headline") or "")[:300], str(prop.get("description") or "")[:5000]))
    return result


def point_alerts(lat: float, lon: float) -> list[WeatherAlert]:
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise DataError("Invalid alert location")
    payload = _json("https://api.weather.gov/alerts/active?" + urlencode({"point": f"{lat:.4f},{lon:.4f}"}))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise DataError("Unexpected point alerts response")
    result = []
    for feature in payload["features"][:100]:
        if not isinstance(feature, dict):
            continue
        prop = feature.get("properties", {})
        if not isinstance(prop, dict):
            continue
        event = str(prop.get("event") or "")
        level = ("warning" if event.endswith("Warning") else "watch" if event.endswith("Watch")
                 else "advisory" if event.endswith("Advisory") else None)
        if level is None or prop.get("status") != "Actual":
            continue
        if prop.get("messageType") == "Cancel":
            continue
        result.append(WeatherAlert(
            identifier=str(prop.get("id") or feature.get("id") or "")[:300],
            event=str(prop.get("event") or "Alert")[:100],
            headline=str(prop.get("headline") or "")[:300],
            description=str(prop.get("description") or "")[:3000],
            severity=str(prop.get("severity") or "Unknown"),
            level=level,
        ))
    return [item for item in result if item.identifier]


def canadian_point_alerts(lat: float, lon: float) -> list[WeatherAlert]:
    """Active ECCC warnings intersecting a small box around an FSA centroid."""
    if not (math.isfinite(lat) and math.isfinite(lon) and 40 <= lat <= 85 and -142 <= lon <= -50):
        raise DataError("Invalid Canadian alert location")
    bbox = f"{lon-.001:.4f},{lat-.001:.4f},{lon+.001:.4f},{lat+.001:.4f}"
    payload = _json("https://api.weather.gc.ca/collections/weather-alerts/items?" + urlencode({"bbox": bbox, "limit": 100, "f": "json"}))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise DataError("Unexpected ECCC alert response")
    result = []
    now = datetime.now(timezone.utc)
    for feature in payload["features"][:100]:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            continue
        prop = feature["properties"]
        level = str(prop.get("alert_type") or "").lower()
        if level not in ("warning", "watch"):
            continue
        if str(prop.get("status_en") or "").lower() in ("cancelled", "ended", "expired", "test"):
            continue
        expiry = prop.get("expiration_datetime")
        try:
            if expiry and datetime.fromisoformat(str(expiry).replace("Z", "+00:00")) <= now:
                continue
        except ValueError:
            continue
        identifier = str(feature.get("id") or "")[:300]
        if identifier:
            result.append(WeatherAlert(identifier, str(prop.get("alert_name_en") or "Weather warning")[:100],
                                       str(prop.get("feature_name_en") or prop.get("alert_name_en") or "")[:300],
                                       str(prop.get("alert_text_en") or "")[:3000],
                                       str(prop.get("risk_colour_en") or level.title())[:30], level))
    return result


def image(url: str) -> bytes:
    return image_record(url)[0]


def image_record(url: str) -> tuple[bytes, datetime]:
    if url not in (RADAR_URL, MLCAPE_URL, *SATELLITE.values(), *OUTLOOK.values()):
        raise DataError("Unknown imagery source")
    data, updated = _fetch_with_time(url, MAX_IMAGE, "image/*")
    if not (data.startswith(b"GIF87a") or data.startswith(b"GIF89a") or data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")):
        raise DataError("Weather service returned an unexpected image")
    if updated is None:
        raise DataError("Imagery has no source update time; freshness cannot be verified")
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    max_age = 15 * 60 if url == RADAR_URL else 30 * 60 if url in SATELLITE.values() else 120 * 60 if url == MLCAPE_URL else 30 * 3600
    if age < -300 or age > max_age:
        raise DataError(f"Imagery is stale (source updated {updated:%d %b %H:%M UTC})")
    return data, updated
