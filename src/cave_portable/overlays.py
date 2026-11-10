"""Official alert and outlook geometries for the decoded radar workspace."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
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


@lru_cache(maxsize=32)
def _local_alerts(lat: float, lon: float, cache_slot: int):
    del cache_slot
    payload = data._json("https://api.weather.gov/alerts/active?" +
                         urlencode({"point": f"{lat:.4f},{lon:.4f}"}))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise data.DataError("NWS alert geometry was invalid")
    current = datetime.now(timezone.utc)
    result = []
    for item in payload["features"][:100]:
        if not isinstance(item, dict):
            continue
        props = item.get("properties", {})
        if not isinstance(props, dict):
            continue
        expires = _time(props.get("expires"))
        if expires is None or expires <= current:
            continue
        event = str(props.get("event", ""))[:90]
        kind = "warning" if "Warning" in event else "watch" if "Watch" in event else "other"
        if kind != "other":
            result.append((kind, event, _rings(item.get("geometry")),
                           _time(props.get("sent")), _time(props.get("effective")), expires))
    return result


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
         scan_time: datetime | None = None) -> tuple[Image.Image, str]:
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
    if include_alerts and point is not None:
        try:
            alerts = _local_alerts(round(point[0], 4), round(point[1], 4), int(now.timestamp()) // 300)
            for kind, _event, rings, _sent, _effective, _expires in alerts:
                paint(rings, "#e02238" if kind == "warning" else "#f1c128", 4)
            polygons = sum(bool(rings) for _kind, _event, rings, _sent, _effective, _expires in alerts)
            notes.append(f"NWS warnings/watches at selected location: {len(alerts)}, "
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
