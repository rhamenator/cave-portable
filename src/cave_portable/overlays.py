"""Official alert and outlook geometries for the decoded radar workspace."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import re
from urllib.parse import urlencode

from PIL import Image, ImageDraw

from . import data, spc


def _rings(geometry: dict) -> list[list[tuple[float, float]]]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "Polygon":
        sources = geometry.get("coordinates", [])
    elif geometry.get("type") == "MultiPolygon":
        sources = [ring for polygon in geometry.get("coordinates", []) for ring in polygon]
    elif "rings" in geometry:
        sources = geometry["rings"]
    else:
        return []
    result = []
    for ring in sources[:30]:
        if not isinstance(ring, list) or len(ring) < 3 or len(ring) > 10000:
            continue
        try:
            points = [(float(point[0]), float(point[1])) for point in ring]
        except (TypeError, ValueError, IndexError):
            continue
        if all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in points):
            result.append(points)
    return result


def _time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _alert_rows(payload: dict, current: datetime):
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise data.DataError("NWS alert geometry was invalid")
    result = []
    for item in payload["features"][:300]:
        if not isinstance(item, dict) or not isinstance(item.get("properties"), dict):
            continue
        props = item["properties"]
        expires = _time(props.get("expires"))
        if (expires is None or expires <= current or props.get("status") != "Actual"
                or props.get("messageType") == "Cancel"):
            continue
        event = str(props.get("event", ""))[:90]
        kind = next((name for name in ("warning", "watch", "advisory")
                     if event.lower().endswith(name)), None)
        if kind:
            result.append((kind, event, _rings(item.get("geometry")),
                           _time(props.get("sent")), _time(props.get("effective")), expires))
    return result


@lru_cache(maxsize=32)
def _local_alerts(lat: float, lon: float, cache_slot: int):
    del cache_slot
    payload = data._json("https://api.weather.gov/alerts/active?" +
                         urlencode({"point": f"{lat:.4f},{lon:.4f}"}))
    return _alert_rows(payload, datetime.now(timezone.utc))


@lru_cache(maxsize=64)
def _radar_state(lat: float, lon: float):
    payload = data._json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    try:
        state = payload["properties"]["relativeLocation"]["properties"]["state"]
    except (KeyError, TypeError) as exc:
        raise data.DataError("Radar state was unavailable") from exc
    if not isinstance(state, str) or not re.fullmatch(r"[A-Z]{2}", state):
        raise data.DataError("Radar state was invalid")
    return state


@lru_cache(maxsize=64)
def _state_alerts(state: str, cache_slot: int):
    del cache_slot
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise data.DataError("Invalid US alert area")
    payload = data._json("https://api.weather.gov/alerts/active?" + urlencode({"area": state}))
    return _alert_rows(payload, datetime.now(timezone.utc))


@lru_cache(maxsize=32)
def _spc_outlook(bbox: str, cache_slot: int):
    del cache_slot
    west, south, east, north = (float(value) for value in bbox.split(","))
    params = {"where": "1=1", "outFields": "dn,issue,valid,expire", "returnGeometry": "true",
              "geometry": f"{west},{south},{east},{north}", "geometryType": "esriGeometryEnvelope",
              "inSR": "4326", "outSR": "4326", "spatialRel": "esriSpatialRelIntersects", "f": "json"}
    payload = data._json(f"{spc.SERVICE}/1/query?" + urlencode(params))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise data.DataError("SPC outlook geometry was invalid")
    current = datetime.now(timezone.utc)
    features = payload["features"]
    if not features:
        return []
    try:
        issue = max(spc._time(item["attributes"]["issue"]) for item in features)
    except (ValueError, KeyError, TypeError) as exc:
        raise data.DataError("SPC outlook issue time was unavailable") from exc
    result = []
    for item in features[:100]:
        attrs = item.get("attributes", {})
        try:
            if (spc._time(attrs["issue"]) != issue or spc._time(attrs["valid"]) > current
                    or spc._time(attrs["expire"]) <= current):
                continue
            category = spc.CATEGORIES.get(int(attrs["dn"]))
        except (KeyError, ValueError, TypeError):
            continue
        if category:
            result.append((category, _rings(item.get("geometry")), issue,
                           spc._time(attrs["valid"]), spc._time(attrs["expire"])))
    return result


@lru_cache(maxsize=32)
def _nearby_observation(lat: float, lon: float, cache_slot: int):
    del cache_slot
    return data.nearby_metar(lat, lon)


def draw(image: Image.Image, bbox: str, point: tuple[float, float] | None = None,
         include_spc: bool = True, include_alerts: bool = True,
         scan_time: datetime | None = None,
         radar_point: tuple[float, float] | None = None,
         include_local_alerts: bool = True) -> tuple[Image.Image, str]:
    """Paint source geometries and name missing overlays in the returned status."""
    west, south, east, north = (float(value) for value in bbox.split(","))
    output = image.copy().convert("RGB")
    painter = ImageDraw.Draw(output)
    now = datetime.now(timezone.utc)
    notes = []

    def paint(rings, color, width):
        for ring in rings:
            points = [((lon - west) / (east - west) * image.width,
                       (north - lat) / (north - south) * image.height) for lon, lat in ring]
            if len(points) >= 3:
                painter.line(points + [points[0]], fill=color, width=width, joint="curve")

    if include_spc:
        try:
            outlooks = _spc_outlook(bbox, int(now.timestamp()) // 300)
            colors = {"General thunderstorm": "#43a3c2", "Marginal": "#46ab5a",
                      "Slight": "#e8b536", "Enhanced": "#e48638", "Moderate": "#d64749", "High": "#ad4db5"}
            for category, rings, _issue, _valid, _expire in outlooks:
                paint(rings, colors[category], 3)
            if outlooks:
                _category, _rings_data, issue, valid, expire = outlooks[0]
                notes.append(f"SPC Day 1: {len(outlooks)} area(s), issued {issue:%H:%M} UTC, "
                             f"valid {valid:%d %b %H:%M}–{expire:%d %b %H:%M} UTC")
            else:
                notes.append("SPC Day 1: no current area in map")
        except data.DataError:
            notes.append("SPC overlay unavailable")
    if include_alerts and radar_point is not None:
        try:
            state = _radar_state(round(radar_point[0], 4), round(radar_point[1], 4))
            area_alerts = _state_alerts(state, int(now.timestamp()) // 300)
            visible = 0
            active_area_alerts = [row for row in area_alerts if row[5] > now]
            for kind, _event, rings, _sent, _effective, _expires in active_area_alerts:
                if not any(min(lon for lon, _lat in ring) <= east and max(lon for lon, _lat in ring) >= west
                           and min(lat for _lon, lat in ring) <= north and max(lat for _lon, lat in ring) >= south
                           for ring in rings):
                    continue
                visible += 1
                paint(rings, {"warning": "#e02238", "watch": "#f1c128", "advisory": "#7b6ac7"}[kind], 4)
            unmapped = sum(not rings for _kind, _event, rings, _sent, _effective, _expires in active_area_alerts)
            notes.append(f"NWS {state} border context: {visible} polygon(s) in map; "
                         f"{unmapped} state alert(s) lack polygons "
                         f"(checked {now:%H:%M} UTC; {state} only)")
            for kind, event, rings, sent, _effective, expires in active_area_alerts[:2]:
                if rings and visible:
                    notes.append(f"NWS {state} {event}: "
                                 + (f"issued {sent:%H:%M} UTC, " if sent else "")
                                 + f"expires {expires:%H:%M} UTC")
        except data.DataError:
            notes.append("NWS US border alert layer unavailable")
    if include_alerts and include_local_alerts and point is not None:
        try:
            alerts = [row for row in _local_alerts(round(point[0], 4), round(point[1], 4),
                                                  int(now.timestamp()) // 300) if row[5] > now]
            for kind, _event, rings, _sent, _effective, _expires in alerts:
                paint(rings, "#e02238" if kind == "warning" else "#f1c128", 4)
            polygons = sum(bool(rings) for _kind, _event, rings, _sent, _effective, _expires in alerts)
            notes.append(f"NWS alerts at selected US location: {len(alerts)}, "
                         f"{polygons} with polygons (checked {now:%H:%M} UTC)")
            for kind, event, _rings_data, sent, _effective, expires in alerts[:2]:
                notes.append(f"{event}: issued {sent:%H:%M} UTC, expires {expires:%H:%M} UTC"
                             if sent else f"{event}: expires {expires:%H:%M} UTC")
        except data.DataError:
            notes.append("NWS alert overlay unavailable")
    if point:
        lat, lon = point
        x = (lon - west) / (east - west) * image.width
        y = (north - lat) / (north - south) * image.height
        if 0 <= x < image.width and 0 <= y < image.height:
            painter.ellipse((x - 5, y - 5, x + 5, y + 5), fill="white", outline="black", width=2)
            painter.text((x + 8, y - 8), "Selected location", fill="black", stroke_width=2, stroke_fill="white")
        try:
            observation = _nearby_observation(round(lat, 3), round(lon, 3), int(now.timestamp()) // 300)
            notes.append(f"{observation.station} observation {observation.observed}: "
                         f"{observation.temp_c:.0f} °C, {observation.wind}")
            if observation.lat is not None and observation.lon is not None:
                ox = (observation.lon - west) / (east - west) * image.width
                oy = (north - observation.lat) / (north - south) * image.height
                if 0 <= ox < image.width and 0 <= oy < image.height:
                    painter.ellipse((ox - 4, oy - 4, ox + 4, oy + 4), fill="#f5f5f5", outline="#17253b", width=2)
                    painter.text((ox + 7, oy + 6), observation.station, fill="black",
                                 stroke_width=2, stroke_fill="white")
        except data.DataError:
            notes.append("Nearby airport observation unavailable")
    if scan_time is not None and now - scan_time > timedelta(minutes=2):
        notes.insert(0, "Overlays/observation are current, not archived at radar scan time")
    return output, " · ".join(notes)
