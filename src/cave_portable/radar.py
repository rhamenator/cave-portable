"""Current single-site NEXRAD reflectivity and storm-relative velocity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode

from PIL import Image

from .data import DataError, _json
from .model import BASEMAP, HEIGHT, WIDTH, _png

# Curated site centers keep both the map view and network target bounded.
SITES = {
    "DTX · Detroit": ("DTX", -83.47, 42.70),
    "TLX · Oklahoma City": ("TLX", -97.28, 35.33),
    "FWS · Dallas/Fort Worth": ("FWS", -97.30, 32.57),
    "BMX · Birmingham": ("BMX", -86.77, 33.17),
    "DMX · Des Moines": ("DMX", -93.72, 41.73),
    "LOT · Chicago": ("LOT", -88.08, 41.60),
    "OKX · New York City": ("OKX", -72.86, 40.87),
    "ATX · Seattle": ("ATX", -122.50, 48.19),
}
PRODUCTS = {"Site reflectivity": "N0B", "Storm-relative velocity": "N0S"}
WMS = "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/ridge.cgi"
METADATA = "https://mesonet.agron.iastate.edu/data/gis/images/4326/ridge"


def _bbox(site: str) -> str:
    try:
        _id, lon, lat = SITES[site]
    except KeyError as exc:
        raise DataError("Unknown radar site") from exc
    return f"{lon-3.5:.2f},{lat-2.5:.2f},{lon+3.5:.2f},{lat+2.5:.2f}"


@lru_cache(maxsize=8)
def _site_base(site: str) -> Image.Image:
    url = BASEMAP + "?" + urlencode({
        "bbox": _bbox(site), "bboxSR": "4326", "imageSR": "4326",
        "size": f"{WIDTH},{HEIGHT}", "format": "png", "f": "image",
    })
    return _png(url)


def site_map(site: str, product_name: str, now: datetime | None = None) -> tuple[Image.Image, str]:
    if site not in SITES or product_name not in PRODUCTS:
        raise DataError("Unknown radar site or product")
    site_id = SITES[site][0]
    product = PRODUCTS[product_name]
    metadata = _json(f"{METADATA}/{site_id}/{product}_0.json")
    try:
        meta = metadata["meta"]
        if meta["site"] != site_id or meta["product"] != product:
            raise ValueError("metadata did not match request")
        valid = datetime.fromisoformat(meta["valid"].replace("Z", "+00:00")).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("Radar metadata was missing or invalid") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if valid > current + timedelta(minutes=5) or current - valid > timedelta(minutes=15):
        raise DataError(f"Radar product is stale ({valid:%d %b %H:%M UTC}); showing no image")
    url = WMS + "?" + urlencode({
        "sector": site_id, "prod": product, "service": "WMS", "request": "GetMap",
        "version": "1.1.1", "layers": "single", "styles": "", "format": "image/png",
        "transparent": "true", "srs": "EPSG:4326", "bbox": _bbox(site),
        "width": str(WIDTH), "height": str(HEIGHT),
    })
    overlay = _png(url)
    if overlay.size != (WIDTH, HEIGHT):
        raise DataError("Radar service returned an unexpected map size")
    result = _site_base(site).copy()
    result.alpha_composite(overlay)
    return result.convert("RGB"), valid.strftime("%d %b %Y %H:%M UTC")
