"""Read-only GFS forecast CAPE map from NSF Unidata THREDDS WMS."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
from urllib.parse import urlencode

from PIL import Image

from .data import DataError, MAX_IMAGE, _fetch

WMS = "https://thredds.ucar.edu/thredds/wms/grib/NCEP/GFS/Global_0p25deg/Best"
BASEMAP = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/export"
LAYER = "Convective_available_potential_energy_surface"
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
