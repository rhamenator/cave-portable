"""Bounded, read-only requests to public NOAA weather services."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "CAVE-Portable/0.1 (https://github.com/rhamenator/cave-portable)"
STATIONS = (
    "KSEA", "KPDX", "KSFO", "KLAX", "KLAS", "KPHX", "KSLC", "KDEN",
    "KDFW", "KIAH", "KMSP", "KORD", "KDTW", "KATL", "KMIA", "KBOS",
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
class WeatherAlert:
    identifier: str
    event: str
    headline: str
    description: str
    severity: str


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
        if prop.get("severity") not in ("Severe", "Extreme") or prop.get("status") != "Actual":
            continue
        if prop.get("messageType") == "Cancel":
            continue
        result.append(WeatherAlert(
            identifier=str(prop.get("id") or feature.get("id") or "")[:300],
            event=str(prop.get("event") or "Alert")[:100],
            headline=str(prop.get("headline") or "")[:300],
            description=str(prop.get("description") or "")[:3000],
            severity=str(prop["severity"]),
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
        if str(prop.get("alert_type") or "").lower() != "warning":
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
                                       str(prop.get("risk_colour_en") or "Warning")[:30]))
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
