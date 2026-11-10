"""Keyless UK postcode-area warnings and decoded Met Office rain radar."""

from __future__ import annotations

import io
import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode
from xml.etree import ElementTree

import h5py
import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer

from . import data, model

RADAR_PRODUCT = "UK rain rate (Met Office)"
RADAR_BUCKET = "https://met-office-radar-obs-data.s3.eu-west-2.amazonaws.com"
WARNINGS = "https://services.arcgis.com/Lq3V5RFuTBC9I7kv/arcgis/rest/services/Met_Office_National_Severe_Weather_Warning_Service_Live/FeatureServer/0/query"
KEY = re.compile(r"radar/(\d{4})/(\d{2})/(\d{2})/(\d{12})_ODIM_ng_radar_rainrate_composite_1km_UK\.h5$")
COLORS = ((.1, (95, 194, 245, 130)), (.5, (38, 169, 105, 180)),
          (2, (245, 217, 57, 200)), (5, (242, 122, 43, 220)), (15, (204, 39, 74, 235)))


def bbox(lat: float, lon: float, zoom: int = 1, center: tuple[float, float] | None = None) -> str:
    if zoom not in (1, 2, 4, 8, 16) or not all(math.isfinite(v) for v in (lat, lon)):
        raise data.DataError("Invalid UK map location or zoom")
    y, x = center or (lat, lon)
    half_x, half_y = 5 / zoom, 3.1 / zoom
    return f"{x-half_x:.4f},{y-half_y:.4f},{x+half_x:.4f},{y+half_y:.4f}"


def _contains(ring: list, lat: float, lon: float) -> bool:
    inside = False
    for first, second in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = first[:2]
        x2, y2 = second[:2]
        if (y1 > lat) != (y2 > lat) and lon < (x2-x1) * (lat-y1) / (y2-y1) + x1:
            inside = not inside
    return inside


def _covers(geometry: dict, lat: float, lon: float) -> bool:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coordinates]
    elif kind == "MultiPolygon":
        polygons = coordinates
    else:
        return False
    try:
        return any(_contains(polygon[0], lat, lon) and not any(
            _contains(hole, lat, lon) for hole in polygon[1:]) for polygon in polygons)
    except (TypeError, IndexError, ValueError, ZeroDivisionError):
        return False


@lru_cache(maxsize=3)
def _warning_features(slot: int) -> tuple[dict, ...]:
    del slot
    url = WARNINGS + "?" + urlencode({"where": "1=1", "outFields":
        "GlobalID,weathertype,warninglevel,warningheadline,validfromdate,validtodate,issuedDate,whatToExpect",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson"})
    result = data._json(url)
    features = result.get("features") if isinstance(result, dict) else None
    if not isinstance(features, list) or len(features) > 1000:
        raise data.DataError("Met Office warning feed was invalid")
    return tuple(item for item in features if isinstance(item, dict))


def warning_features() -> tuple[dict, ...]:
    return _warning_features(int(datetime.now(timezone.utc).timestamp()) // 60)


def point_alerts(lat: float, lon: float, now: datetime | None = None) -> list[data.WeatherAlert]:
    current = now or datetime.now(timezone.utc)
    result = []
    for feature in warning_features():
        properties = feature.get("properties") or {}
        try:
            start = datetime.fromtimestamp(float(properties["validfromdate"]) / 1000, timezone.utc)
            end = datetime.fromtimestamp(float(properties["validtodate"]) / 1000, timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if current >= end or not _covers(feature.get("geometry") or {}, lat, lon):
            continue
        colour = str(properties.get("warninglevel") or "").upper()
        if colour not in ("YELLOW", "AMBER", "RED"):
            continue
        upcoming = current < start
        level = "advisory" if upcoming else "watch" if colour == "YELLOW" else "warning"
        event = str(properties.get("weathertype") or "Weather").title()
        headline = str(properties.get("warningheadline") or "Official UK weather warning")
        issued = properties.get("issuedDate")
        try:
            issued_text = datetime.fromtimestamp(float(issued) / 1000, timezone.utc).strftime("%d %b %H:%M UTC")
        except (TypeError, ValueError, OverflowError):
            issued_text = "unknown"
        description = (f"Met Office Weather Warnings · © Crown copyright {start.year}, Met Office · "
                       f"{colour} {event} warning · issued {issued_text} · "
                       f"valid {start:%d %b %H:%M}–{end:%d %b %H:%M} UTC. "
                       + str(properties.get("whatToExpect") or "") +
                       "\nTime delays are possible. For the latest warning, see https://weather.metoffice.gov.uk/warnings-and-advice/uk-warnings")[:2000]
        result.append(data.WeatherAlert(str(properties.get("GlobalID") or feature.get("id") or headline),
                                        event, f"{'UPCOMING ' if upcoming else ''}{colour}: {headline}", description, colour, level))
    return result


def _latest_key(now: datetime) -> tuple[str, datetime]:
    latest = None
    for day in (now, now - timedelta(days=1)):
        prefix = f"radar/{day:%Y/%m/%d}/"
        start = (now - timedelta(minutes=90)).strftime("%Y%m%d%H%M") if day.date() == now.date() else ""
        url = RADAR_BUCKET + "/?" + urlencode({"list-type": "2", "prefix": prefix,
                                                 "start-after": prefix + start, "max-keys": "100"})
        raw = data._fetch(url, 120_000, "application/xml")
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise data.DataError("UK radar catalog was invalid") from exc
        for node in root.iter():
            if not node.tag.endswith("}Key") or not node.text:
                continue
            match = KEY.fullmatch(node.text)
            if match:
                valid = datetime.strptime(match.group(4), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                if valid <= now and (latest is None or valid > latest[1]):
                    latest = (node.text, valid)
        if latest:
            break
    if latest is None or now - latest[1] > timedelta(minutes=40):
        raise data.DataError("No fresh UK radar scan (40-minute limit)")
    return latest


def _rain_overlay(raw: bytes, bounds: str) -> Image.Image:
    try:
        with h5py.File(io.BytesIO(raw), "r") as file:
            where = file["where"].attrs
            what = file["dataset1/data1/what"].attrs
            quantity = what["quantity"]
            if (quantity.decode("ascii") if isinstance(quantity, bytes) else str(quantity)) != "RATE":
                raise data.DataError("Unexpected UK radar quantity")
            values = file["dataset1/data1/data"][:]
            projection_value = where["projdef"]
            projection = (projection_value.decode("ascii") if isinstance(projection_value, bytes)
                          else str(projection_value))
            ul_lon, ul_lat = float(where["UL_lon"]), float(where["UL_lat"])
            xscale, yscale = float(where["xscale"]), float(where["yscale"])
            gain, offset = float(what["gain"]), float(what["offset"])
            nodata = float(what["nodata"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise data.DataError("UK radar file was invalid") from exc
    if values.ndim != 2 or values.size > 5_000_000 or xscale <= 0 or yscale <= 0:
        raise data.DataError("Unexpected UK radar grid")
    west, south, east, north = map(float, bounds.split(","))
    width, height = model.WIDTH, model.HEIGHT
    lon, lat = np.meshgrid(np.linspace(west, east, width), np.linspace(north, south, height))
    transform = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_user_input(projection), always_xy=True)
    x, y = transform.transform(lon, lat)
    ul_x, ul_y = transform.transform(ul_lon, ul_lat)
    col = np.floor((x-ul_x) / xscale).astype(np.int32)
    row = np.floor((ul_y-y) / yscale).astype(np.int32)
    valid = (row >= 0) & (col >= 0) & (row < values.shape[0]) & (col < values.shape[1])
    sampled = np.zeros((height, width), dtype=np.float32)
    sampled[valid] = values[row[valid], col[valid]]
    rate = sampled * gain + offset
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    for threshold, color in COLORS:
        pixels[valid & (sampled != nodata) & (rate >= threshold)] = color
    return Image.fromarray(pixels, "RGBA")


def radar_map(lat: float, lon: float, zoom: int = 1, center: tuple[float, float] | None = None,
              boundaries: bool = True) -> tuple[Image.Image, str]:
    bounds = bbox(lat, lon, zoom, center)
    now = datetime.now(timezone.utc)
    key, valid = _latest_key(now)
    raw = data._fetch(RADAR_BUCKET + "/" + key, 4_000_000, "application/x-hdf5")
    overlay = _rain_overlay(raw, bounds)
    try:
        picture = model._basemap(bounds).copy().convert("RGBA")
    except data.DataError:
        picture = Image.new("RGBA", (model.WIDTH, model.HEIGHT), "#e7eef1")
    picture.alpha_composite(overlay)
    draw = ImageDraw.Draw(picture)
    west, south, east, north = map(float, bounds.split(","))
    source = "warning areas unavailable"
    if boundaries:
        try:
            features = warning_features()
            for feature in features:
                geometry = feature.get("geometry") or {}
                properties = feature.get("properties") or {}
                colour = {"YELLOW": "#d0a800", "AMBER": "#e87925", "RED": "#c82c3e"}.get(
                    str(properties.get("warninglevel") or "").upper(), "#858585")
                polygons = ([geometry.get("coordinates")] if geometry.get("type") == "Polygon" else
                            geometry.get("coordinates") if geometry.get("type") == "MultiPolygon" else [])
                for polygon in polygons:
                    if not polygon:
                        continue
                    points = [((x-west)/(east-west)*model.WIDTH, (north-y)/(north-south)*model.HEIGHT)
                              for x, y, *_ in polygon[0]]
                    if len(points) >= 3:
                        draw.line(points + points[:1], fill=colour, width=3)
            issued = []
            for feature in features:
                try:
                    issued.append(datetime.fromtimestamp(float(feature["properties"]["issuedDate"]) / 1000,
                                                         timezone.utc))
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
            source = ("Met Office Weather Warnings outlined · latest issued " +
                      max(issued).strftime("%d %b %H:%M UTC") if issued else
                      "Met Office Weather Warnings outlined · issue time unavailable")
        except (data.DataError, TypeError, ValueError):
            pass
    px, py = (lon-west)/(east-west)*model.WIDTH, (north-lat)/(north-south)*model.HEIGHT
    draw.ellipse((px-5, py-5, px+5, py+5), fill="white", outline="black", width=2)
    for index, (threshold, color) in enumerate(COLORS):
        x = 12 + index*92
        draw.rectangle((x, 468, x+13, 481), fill=color)
        draw.text((x+18, 467), f"{threshold:g}+", fill="black")
    draw.text((12, 486), "Rain rate mm/h · © British Crown copyright 2024–2025, Met Office · CC BY-SA 4.0 · rendered by CAVE Portable", fill="black")
    return picture.convert("RGB"), (f"Met Office rain rate valid {valid:%d %b %H:%M UTC} "
                                   f"({int((now-valid).total_seconds()/60)} min old) · {source} · no velocity/CC")
