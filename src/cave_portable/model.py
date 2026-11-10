"""Read-only GFS forecast CAPE map from NSF Unidata THREDDS WMS."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
from urllib.parse import urlencode
from xml.etree import ElementTree
import re

from PIL import Image

from .data import DataError, MAX_IMAGE, _fetch

WMS = "https://thredds.ucar.edu/thredds/wms/grib/NCEP/GFS/Global_0p25deg/Best"
BASEMAP = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/export"
LAYER = "Convective_available_potential_energy_surface"
CATALOG = "https://thredds.ucar.edu/thredds/catalog/grib/NCEP/GFS/Global_0p25deg/catalog.xml"
FIELDS = {
    "CAPE": (LAYER, "0,4000", "J/kg", None),
    "CIN": ("Convective_inhibition_surface", "-500,0", "J/kg", None),
    "2 m relative humidity": ("Relative_humidity_height_above_ground", "0,100", "%", "2"),
    "2 m dewpoint": ("Dewpoint_temperature_height_above_ground", "240,310", "K", "2"),
}
RUN_CHOICES = ("Latest run", "Previous run", "2 runs back", "3 runs back")
RUN_PATH = re.compile(r"^grib/NCEP/GFS/Global_0p25deg/GFS_Global_0p25deg_(\d{8})_(\d{4})\.grib2$")
HOURS = (0, 6, 12, 24, 36, 48, 72)
WIDTH, HEIGHT = 960, 500
NATIONAL_BBOX = "-130,20,-60,55"


def regional_bbox(lat: float, lon: float, zoom: int = 1) -> str:
    """A bounded forecast viewport around an explicitly selected location."""
    if not (math.isfinite(lat) and math.isfinite(lon) and 20 <= lat <= 55 and -130 <= lon <= -60) or zoom not in (1, 2, 4, 8, 16):
        raise DataError("Unsupported forecast location or zoom")
    half_lon, half_lat = 9 / zoom, 5 / zoom
    center_lon = min(-60 - half_lon, max(-130 + half_lon, lon))
    center_lat = min(55 - half_lat, max(20 + half_lat, lat))
    return f"{center_lon-half_lon:.4f},{center_lat-half_lat:.4f},{center_lon+half_lon:.4f},{center_lat+half_lat:.4f}"


def valid_time(hours: int, now: datetime | None = None) -> datetime:
    if hours not in HOURS:
        raise DataError("Unsupported forecast time")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = current.replace(minute=0, second=0, microsecond=0)
    remainder = base.hour % 3
    if remainder or current.minute or current.second or current.microsecond:
        base += timedelta(hours=(3 - remainder) if remainder else 3)
    return base + timedelta(hours=hours)


def _png(url: str) -> Image.Image:
    raw = _fetch(url, MAX_IMAGE, "image/png")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise DataError("Map service returned an error instead of a PNG image")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            return opened.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise DataError("Map service returned an invalid image") from exc


@lru_cache(maxsize=16)
def _basemap(bbox: str = NATIONAL_BBOX) -> Image.Image:
    url = BASEMAP + "?" + urlencode({
        "bbox": bbox, "bboxSR": "4326", "imageSR": "4326",
        "size": f"{WIDTH},{HEIGHT}", "format": "png", "f": "image",
    })
    return _png(url)


def cape_map(hours: int, bbox: str = NATIONAL_BBOX) -> tuple[Image.Image, str]:
    valid = valid_time(hours)
    params = {
        "service": "WMS", "request": "GetMap", "version": "1.1.1",
        "layers": LAYER, "styles": "default-scalar/default", "format": "image/png",
        "transparent": "true", "srs": "EPSG:4326", "bbox": bbox,
        "width": str(WIDTH), "height": str(HEIGHT),
        "time": valid.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "colorScaleRange": "0,4000",
    }
    overlay = _png(WMS + "?" + urlencode(params))
    if overlay.size != (WIDTH, HEIGHT):
        raise DataError("Model service returned an unexpected map size")
    # The WMS paints zero CAPE opaque navy even with transparent=true.
    # Remove only that exact zero color so geography remains visible.
    pixels = overlay.getdata()
    overlay.putdata([(r, g, b, 0 if (r, g, b) == (8, 29, 88) else 180) for r, g, b, _a in pixels])
    result = _basemap(bbox).copy()
    result.alpha_composite(overlay)
    legend = _png(WMS + "?" + urlencode({
        "service": "WMS", "request": "GetLegendGraphic", "version": "1.1.1",
        "layer": LAYER, "style": "default-scalar/default", "format": "image/png",
        "colorScaleRange": "0,4000", "width": "20", "height": "300",
    }))
    result.alpha_composite(legend, (WIDTH - legend.width - 8, HEIGHT - legend.height - 8))
    return result.convert("RGB"), valid.strftime("%a %d %b %Y %H:%M UTC")


@lru_cache(maxsize=4)
def _runs(cache_slot: int) -> tuple[tuple[datetime, str], ...]:
    del cache_slot
    raw = _fetch(CATALOG, 200_000, "application/xml")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise DataError("GFS run catalog was invalid") from exc
    found = []
    for item in root.iter():
        path = item.attrib.get("urlPath", "")
        matched = RUN_PATH.fullmatch(path)
        if matched:
            initialized = datetime.strptime("".join(matched.groups()), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            found.append((initialized, path))
    if not found:
        raise DataError("No explicit GFS runs are available")
    return tuple(sorted(set(found), reverse=True)[:4])


def field_map(field_name: str, hours: int, bbox: str, run_choice: str = "Latest run") -> tuple[Image.Image, str]:
    """Render a selected field from one explicit GFS run, never the Best time series."""
    if field_name not in FIELDS or hours not in HOURS or run_choice not in RUN_CHOICES:
        raise DataError("Unsupported GFS field, lead, or run")
    runs = _runs(int(datetime.now(timezone.utc).timestamp()) // 600)
    index = RUN_CHOICES.index(run_choice)
    if index >= len(runs):
        raise DataError("Requested GFS run is not yet in the catalog")
    initialized, path = runs[index]
    valid = initialized + timedelta(hours=hours)
    if valid < datetime.now(timezone.utc) - timedelta(hours=1):
        raise DataError("Selected GFS forecast hour has passed")
    layer, color_range, unit, elevation = FIELDS[field_name]
    endpoint = "https://thredds.ucar.edu/thredds/wms/" + path
    params = {"service": "WMS", "request": "GetMap", "version": "1.1.1",
              "layers": layer, "styles": "default-scalar/default", "format": "image/png",
              "transparent": "true", "srs": "EPSG:4326", "bbox": bbox,
              "width": str(WIDTH), "height": str(HEIGHT),
              "time": valid.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "colorScaleRange": color_range}
    if elevation:
        params["elevation"] = elevation
    overlay = _png(endpoint + "?" + urlencode(params))
    if overlay.size != (WIDTH, HEIGHT):
        raise DataError("GFS field had an unexpected map size")
    pixels = overlay.getdata()
    overlay.putdata([(r, g, b, 0 if a == 0 or (field_name == "CAPE" and (r, g, b) == (8, 29, 88))
                     else min(a, 180)) for r, g, b, a in pixels])
    picture = _basemap(bbox).copy()
    picture.alpha_composite(overlay)
    legend_params = {"service": "WMS", "request": "GetLegendGraphic", "version": "1.1.1",
                     "layer": layer, "style": "default-scalar/default", "format": "image/png",
                     "colorScaleRange": color_range, "width": "20", "height": "300"}
    if elevation:
        legend_params["elevation"] = elevation
    legend = _png(endpoint + "?" + urlencode(legend_params))
    if legend.width > WIDTH or legend.height > HEIGHT:
        raise DataError("GFS legend was unexpectedly large")
    picture.alpha_composite(legend, (WIDTH - legend.width - 8, HEIGHT - legend.height - 8))
    return picture.convert("RGB"), (f"{field_name} ({unit}) · GFS run {initialized:%d %b %H:%M UTC}"
                                     f" · valid {valid:%d %b %H:%M UTC}")
