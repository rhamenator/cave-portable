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

from .data import DataError, _fetch

BUCKET = "https://noaa-mrms-pds.s3.us-east-1.amazonaws.com/"
PREFIX = "CONUS/MESH_00.50/"
KEY = re.compile(r"^CONUS/MESH_00\.50/(\d{8})/MRMS_MESH_00\.50_(\d{8})-(\d{6})\.grib2\.gz$")


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

    def summary(self, place: str) -> str:
        if self.point_mm is None:
            point = "no valid MESH estimate at the point"
        else:
            point = f"{self.point_mm:.1f} mm ({self.point_mm / 25.4:.2f} in) at the point"
        if self.nearby_max_mm is None:
            nearby = "no valid nearby estimate"
        else:
            nearby = f"nearby sampled maximum {self.nearby_max_mm:.1f} mm ({self.nearby_max_mm / 25.4:.2f} in)"
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
