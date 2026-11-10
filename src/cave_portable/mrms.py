"""On-demand NOAA MRMS MESH readout near an explicit US location."""

from __future__ import annotations

import gzip
import io
import math
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from multiprocessing import get_context
from urllib.parse import quote, urlencode
from xml.etree import ElementTree
from PIL import Image, ImageDraw

from .data import DataError, _fetch
from . import units

BUCKET = "https://noaa-mrms-pds.s3.us-east-1.amazonaws.com/"
PREFIX = "CONUS/MESH_00.50/"
KEY = re.compile(r"^CONUS/MESH_00\.50/(\d{8})/MRMS_MESH_00\.50_(\d{8})-(\d{6})\.grib2\.gz$")
SWATH_PREFIX = "CONUS/MESH_Max_30min_00.50/"
SWATH_KEY = re.compile(r"^CONUS/MESH_Max_30min_00\.50/(\d{8})/MRMS_MESH_Max_30min_00\.50_(\d{8})-(\d{6})\.grib2\.gz$")


@lru_cache(maxsize=4)
def _latest_key(day: str, cache_slot: int) -> str | None:
    del cache_slot
    prefix = PREFIX + day + "/"
    raw = _fetch(BUCKET + "?" + urlencode({"list-type": "2", "prefix": prefix, "max-keys": "1000"}),
                 500_000, "application/xml")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise DataError("MRMS file listing was invalid") from exc
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    if root.findtext("s:IsTruncated", default="false", namespaces=ns) == "true":
        raise DataError("MRMS file listing was truncated")
    keys = [item.findtext("s:Key", namespaces=ns) for item in root.findall("s:Contents", ns)]
    return max((name for name in keys if name and KEY.fullmatch(name)), default=None)


@lru_cache(maxsize=4)
def _latest_swath_key(day: str, cache_slot: int) -> str | None:
    del cache_slot
    prefix = SWATH_PREFIX + day + "/"
    raw = _fetch(BUCKET + "?" + urlencode({"list-type": "2", "prefix": prefix, "max-keys": "1000"}),
                 500_000, "application/xml")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise DataError("MRMS hail swath listing was invalid") from exc
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    if root.findtext("s:IsTruncated", default="false", namespaces=ns) == "true":
        raise DataError("MRMS hail swath listing was truncated")
    keys = [item.findtext("s:Key", namespaces=ns) for item in root.findall("s:Contents", ns)]
    return max((name for name in keys if name and SWATH_KEY.fullmatch(name)), default=None)


def _swath_rgba(compressed: bytes, bbox: str) -> bytes:
    """Sample a GRIB grid in a disposable child; return only a small RGBA image."""
    import eccodes
    from .model import WIDTH, HEIGHT

    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        grib = source.read(12_000_001)
    if len(grib) > 12_000_000 or not grib.startswith(b"GRIB"):
        raise DataError("MRMS hail swath file was too large or invalid")
    handle = eccodes.codes_new_from_message(grib)
    try:
        get = lambda name: eccodes.codes_get(handle, name)
        if (get("discipline"), get("parameterCategory"), get("parameterNumber")) != (209, 3, 29):
            raise DataError("MRMS file was not a 30-minute MESH hail swath")
        ni, nj = int(get("Ni")), int(get("Nj"))
        if get("gridType") != "regular_ll" or not (1 <= ni * nj <= 25_000_000):
            raise DataError("MRMS hail swath grid was unsupported")
        lon0 = float(get("longitudeOfFirstGridPointInDegrees"))
        lat0 = float(get("latitudeOfFirstGridPointInDegrees"))
        dx = float(get("iDirectionIncrementInDegrees"))
        dy = float(get("jDirectionIncrementInDegrees"))
        if not (0 < dx <= .1 and 0 < dy <= .1 and get("iScansNegatively") == 0
                and get("jScansPositively") == 0):
            raise DataError("MRMS hail swath orientation was unsupported")
        west, south, east, north = map(float, bbox.split(","))
        small_w, small_h = WIDTH // 2, HEIGHT // 2
        indexes, positions = [], []
        for y in range(small_h):
            lat = north - (y + .5) * (north - south) / small_h
            row = round((lat0 - lat) / dy)
            if not 0 <= row < nj:
                continue
            for x in range(small_w):
                lon = west + (x + .5) * (east - west) / small_w
                col = round(((lon % 360) - lon0) / dx)
                if 0 <= col < ni:
                    indexes.append(row * ni + col)
                    positions.append((x, y))
        overlay = Image.new("RGBA", (small_w, small_h))
        if indexes:
            values = eccodes.codes_get_double_elements(handle, "values", indexes)
            pixels = overlay.load()
            for (x, y), value in zip(positions, values):
                if math.isfinite(value) and 0 < value < 1000:
                    pixels[x, y] = ((255, 221, 53, 170) if value < 25.4 else
                                    (244, 120, 48, 195) if value < 50.8 else
                                    (210, 49, 80, 215) if value < 76.2 else (147, 57, 177, 225))
        return overlay.resize((WIDTH, HEIGHT), Image.Resampling.NEAREST).tobytes()
    finally:
        eccodes.codes_release(handle)


def swath_map(site_name: str, sites: dict, zoom: int = 1,
              center: tuple[float, float] | None = None, now: datetime | None = None,
              unit_mode: str = units.DEFAULT):
    from .model import WIDTH, HEIGHT, _basemap
    from .radar import _bbox
    if site_name not in sites:
        raise DataError("Unknown radar site")
    bbox = _bbox(site_name, sites, zoom, center)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key = _latest_swath_key(current.strftime("%Y%m%d"), int(current.timestamp()) // 30)
    if key is None and current.hour == 0:
        key = _latest_swath_key((current - timedelta(days=1)).strftime("%Y%m%d"), int(current.timestamp()) // 30)
    if key is None:
        raise DataError("No current MRMS hail swath is available")
    matched = SWATH_KEY.fullmatch(key)
    valid = datetime.strptime(matched[2] + matched[3], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if valid > current + timedelta(minutes=5) or current - valid > timedelta(minutes=10):
        raise DataError("MRMS hail swath is stale; no swath shown")
    compressed = _fetch(BUCKET + quote(key, safe="/"), 5_000_000, "application/gzip")
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        rgba = pool.submit(_swath_rgba, compressed, bbox).result(timeout=25)
    overlay = Image.frombytes("RGBA", (WIDTH, HEIGHT), rgba)
    picture = _basemap(bbox).copy()
    picture.alpha_composite(overlay)
    draw = ImageDraw.Draw(picture)
    draw.rectangle((8, 8, 410, 66), fill=(15, 27, 41, 225))
    draw.text((15, 13), "NOAA MRMS 30-minute MESH maximum", fill="white")
    draw.text((15, 35), f"Valid {valid:%d %b %Y %H:%M UTC} · estimate, not a forecast", fill="white")
    if overlay.getbbox() is None:
        draw.rectangle((8, 73, 325, 97), fill=(15, 27, 41, 225))
        draw.text((15, 78), "No positive hail estimate in this view", fill="white")
    draw.rectangle((8, HEIGHT - 33, 401, HEIGHT - 6), fill=(15, 27, 41, 225))
    labels = ("<2.5 cm", "2.5–5 cm", "5–7.5 cm", "≥7.5 cm") if unit_mode in ("Metric", "UK Hybrid") else ("<1 in", "1–2 in", "2–3 in", "≥3 in")
    for i, (color, label) in enumerate(zip(("#ffdd35", "#f47830", "#d23150", "#9339b1"), labels)):
        x = 15 + i * 95
        draw.rectangle((x, HEIGHT - 26, x + 15, HEIGHT - 12), fill=color)
        draw.text((x + 19, HEIGHT - 26), label, fill="white", stroke_width=2, stroke_fill="black")
    stamp = f"NOAA MRMS 30-minute MESH maximum · valid {valid:%d %b %Y %H:%M UTC} · algorithmic hail estimate"
    return picture.convert("RGB"), stamp


def _mesh_values(compressed: bytes, lat: float, lon: float) -> tuple[float | None, float | None]:
    """Run in a short-lived child: ecCodes expands a full CONUS grid in memory."""
    import eccodes

    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        grib = source.read(12_000_001)
    if len(grib) > 12_000_000 or not grib.startswith(b"GRIB"):
        raise DataError("MRMS GRIB2 file was too large or invalid")
    handle = eccodes.codes_new_from_message(grib)
    try:
        get = lambda name: eccodes.codes_get(handle, name)
        ni, nj = int(get("Ni")), int(get("Nj"))
        if (get("discipline"), get("parameterCategory"), get("parameterNumber")) != (209, 3, 28):
            raise DataError("MRMS file was not MESH hail data")
        if get("gridType") != "regular_ll" or ni * nj > 25_000_000 or ni < 1 or nj < 1:
            raise DataError("MRMS grid format was unsupported")
        lon0 = float(get("longitudeOfFirstGridPointInDegrees"))
        lat0 = float(get("latitudeOfFirstGridPointInDegrees"))
        dx = float(get("iDirectionIncrementInDegrees"))
        dy = float(get("jDirectionIncrementInDegrees"))
        if not (0 < dx <= 0.1 and 0 < dy <= 0.1 and get("iScansNegatively") == 0
                and get("jScansPositively") == 0):
            raise DataError("MRMS grid orientation was unsupported")

        def position(latitude: float, longitude: float) -> int:
            col = round(((longitude % 360) - lon0) / dx)
            row = round((lat0 - latitude) / dy)
            if not (0 <= col < ni and 0 <= row < nj):
                raise DataError("Location is outside the MRMS CONUS hail grid")
            return row * ni + col

        center = position(lat, lon)
        nearby = []
        for y in (-0.1, -0.05, 0, 0.05, 0.1):
            for x in (-0.1, -0.05, 0, 0.05, 0.1):
                try:
                    nearby.append(position(lat + y, lon + x))
                except DataError:
                    continue
        indexes = [center, *nearby]
        values = eccodes.codes_get_double_elements(handle, "values", indexes)
        valid = [value for value in values[1:] if math.isfinite(value) and value >= 0]
        point = values[0] if math.isfinite(values[0]) and values[0] >= 0 else None
        return point, max(valid) if valid else None
    finally:
        eccodes.codes_release(handle)


@dataclass(frozen=True)
class HailReadout:
    time: datetime
    point_mm: float | None
    nearby_max_mm: float | None

    def summary(self, place: str, unit_mode: str = units.DEFAULT) -> str:
        if self.point_mm is None:
            point = "no valid MESH estimate at the point"
        else:
            point = f"{units.ice(self.point_mm, unit_mode)} at the point"
        if self.nearby_max_mm is None:
            nearby = "no valid nearby estimate"
        else:
            nearby = f"nearby sampled maximum {units.ice(self.nearby_max_mm, unit_mode)}"
        return (f"NOAA MRMS MESH near {place}: {point}; {nearby}. "
                f"Valid {self.time:%d %b %Y %H:%M UTC}. Algorithmic hail estimate, not a measured stone size or forecast.")


def near_point(lat: float, lon: float, now: datetime | None = None) -> HailReadout:
    if not (math.isfinite(lat) and math.isfinite(lon) and 20 <= lat <= 55 and -130 <= lon <= -60):
        raise DataError("MRMS MESH point must be in the contiguous US")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key = _latest_key(current.strftime("%Y%m%d"), int(current.timestamp()) // 30)
    if key is None and current.hour == 0:
        key = _latest_key((current - timedelta(days=1)).strftime("%Y%m%d"), int(current.timestamp()) // 30)
    if key is None:
        raise DataError("No current MRMS MESH file is available")
    matched = KEY.fullmatch(key)
    valid = datetime.strptime(matched[2] + matched[3], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if valid > current + timedelta(minutes=5) or current - valid > timedelta(minutes=10):
        raise DataError("MRMS MESH file is stale; no hail estimate shown")
    compressed = _fetch(BUCKET + quote(key, safe="/"), 5_000_000, "application/gzip")
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        point, nearby = pool.submit(_mesh_values, compressed, lat, lon).result(timeout=25)
    return HailReadout(valid, point, nearby)
