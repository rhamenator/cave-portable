"""Current single-site NEXRAD reflectivity and storm-relative velocity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode
from xml.etree import ElementTree

from PIL import Image

from .data import DataError, _fetch, _json
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
PRODUCTS = {"Site reflectivity": "N0B", "Storm-relative velocity": "N0S",
            "Hydrometeor class (hail indicator)": "BDHC"}
WMS = "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/ridge.cgi"
METADATA = "https://mesonet.agron.iastate.edu/data/gis/images/4326/ridge"
NWS_STATIONS = "https://api.weather.gov/radar/stations"
NWS_WMS = "https://opengeo.ncep.noaa.gov/geoserver"


def available_sites() -> dict[str, tuple[str, float, float, str]]:
    """Current NWS WSR-88D catalog; the built-in list remains a network fallback."""
    payload = _json(NWS_STATIONS)
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise DataError("NWS radar station catalog was invalid")
    sites = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        prop, geometry = feature.get("properties"), feature.get("geometry")
        if not isinstance(prop, dict) or not isinstance(geometry, dict) or prop.get("stationType") != "WSR-88D":
            continue
        identifier, name, coordinates = prop.get("id"), prop.get("name"), geometry.get("coordinates")
        if not (isinstance(identifier, str) and len(identifier) == 4 and identifier.isascii()
                and identifier.isalnum() and isinstance(name, str) and isinstance(coordinates, list)
                and len(coordinates) >= 2):
            continue
        try:
            lon, lat = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            short = identifier[1:].upper()
            sites[f"{short} · {name[:55]}"] = (short, lon, lat, identifier.upper())
    if len(sites) < 100:
        raise DataError("NWS radar catalog contained too few sites")
    return dict(sorted(sites.items()))


def _bbox(site: str, sites: dict | None = None, zoom: int = 1) -> str:
    if zoom not in (1, 2, 4):
        raise DataError("Unsupported radar zoom")
    try:
        record = (sites or SITES)[site]
        lon, lat = record[1], record[2]
    except KeyError as exc:
        raise DataError("Unknown radar site") from exc
    return f"{lon-3.5/zoom:.3f},{lat-2.5/zoom:.3f},{lon+3.5/zoom:.3f},{lat+2.5/zoom:.3f}"


@lru_cache(maxsize=24)
def _site_base(bbox: str) -> Image.Image:
    url = BASEMAP + "?" + urlencode({
        "bbox": bbox, "bboxSR": "4326", "imageSR": "4326",
        "size": f"{WIDTH},{HEIGHT}", "format": "png", "f": "image",
    })
    return _png(url)


def site_map(site: str, product_name: str, now: datetime | None = None,
             sites: dict | None = None, zoom: int = 1) -> tuple[Image.Image, str]:
    sites = sites or SITES
    if site not in sites or product_name not in PRODUCTS or zoom not in (1, 2, 4):
        raise DataError("Unknown radar site or product")
    record = sites[site]
    site_id = record[0]
    product = PRODUCTS[product_name]
    bbox = _bbox(site, sites, zoom)
    if product == "BDHC":
        return _nws_hydrometeor(record[3] if len(record) > 3 else "K" + site_id, bbox, now)
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
        "transparent": "true", "srs": "EPSG:4326", "bbox": bbox,
        "width": str(WIDTH), "height": str(HEIGHT),
    })
    overlay = _png(url)
    if overlay.size != (WIDTH, HEIGHT):
        raise DataError("Radar service returned an unexpected map size")
    result = _site_base(bbox).copy()
    result.alpha_composite(overlay)
    return result.convert("RGB"), valid.strftime("%d %b %Y %H:%M UTC")


def _nws_hydrometeor(full_id: str, bbox: str, now: datetime | None) -> tuple[Image.Image, str]:
    """NWS Level III hydrometeor classes, including a hail category; no hail size."""
    layer = f"{full_id.lower()}_bdhc"
    endpoint = f"{NWS_WMS}/{full_id.lower()}/wms"
    capabilities = _fetch(endpoint + "?" + urlencode({"service": "WMS", "request": "GetCapabilities", "version": "1.3.0"}),
                          120_000, "application/xml")
    try:
        root = ElementTree.fromstring(capabilities)
        ns = {"w": "http://www.opengis.net/wms"}
        selected = next(item for item in root.findall(".//w:Layer", ns)
                        if item.findtext("w:Name", default="", namespaces=ns) == layer)
        time_dimension = next(item for item in selected.findall("w:Dimension", ns)
                              if item.attrib.get("name") == "time")
        valid = datetime.fromisoformat(time_dimension.attrib["default"].replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ElementTree.ParseError, StopIteration, KeyError, ValueError) as exc:
        raise DataError("NWS hydrometeor scan time was unavailable") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if valid > current + timedelta(minutes=5) or current - valid > timedelta(minutes=15):
        raise DataError(f"NWS hydrometeor product is stale ({valid:%d %b %H:%M UTC}); showing no image")
    overlay = _png(endpoint + "?" + urlencode({
        "service": "WMS", "request": "GetMap", "version": "1.1.1", "layers": layer,
        "styles": "", "format": "image/png", "transparent": "true", "srs": "EPSG:4326",
        "bbox": bbox, "width": str(WIDTH), "height": str(HEIGHT),
        "time": valid.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }))
    if overlay.size != (WIDTH, HEIGHT):
        raise DataError("NWS hydrometeor service returned an unexpected map size")
    result = _site_base(bbox).copy()
    result.alpha_composite(overlay)
    legend = _png(endpoint + "?" + urlencode({"service": "WMS", "request": "GetLegendGraphic",
                                            "version": "1.1.1", "layer": layer, "format": "image/png"}))
    if legend.width > WIDTH or legend.height > HEIGHT:
        raise DataError("NWS hydrometeor legend was unexpectedly large")
    result.alpha_composite(legend, (8, HEIGHT - legend.height - 8))
    return result.convert("RGB"), valid.strftime("%d %b %Y %H:%M UTC")
