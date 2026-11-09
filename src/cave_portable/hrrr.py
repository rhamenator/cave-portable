"""Near-term simulated reflectivity from NCEP HRRR via Iowa Mesonet WMS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageFont

from . import data, model

HOURS = (3, 6, 12, 18)
METADATA = "https://mesonet.agron.iastate.edu/data/gis/images/4326/hrrr"
WMS = "https://mesonet.agron.iastate.edu/cgi-bin/wms/hrrr/refd.cgi"


def _utc(value) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("missing timezone")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise data.DataError("HRRR metadata time was invalid") from exc


def reflectivity(hours: int, now: datetime | None = None) -> tuple[Image.Image, str]:
    """Latest run's future simulated reflectivity; stale/past guidance is withheld."""
    if hours not in HOURS:
        raise data.DataError("Unsupported HRRR forecast lead")
    metadata = data._json(f"{METADATA}/refd_{hours * 60:04d}.json")
    if not isinstance(metadata, dict):
        raise data.DataError("HRRR metadata was invalid")
    initialized = _utc(metadata.get("model_init_utc"))
    valid = _utc(metadata.get("model_forecast_utc"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if valid != initialized + timedelta(hours=hours):
        raise data.DataError("HRRR forecast time did not match its run")
    if initialized > current + timedelta(minutes=15) or current - initialized > timedelta(hours=4):
        raise data.DataError("Latest HRRR run is too old for near-term guidance")
    if valid < current:
        raise data.DataError("Selected HRRR lead is already past; choose a longer lead")
    params = {
        "service": "WMS", "request": "GetMap", "version": "1.1.1",
        "layers": f"refd_{hours * 60:04d}", "styles": "", "format": "image/png",
        "transparent": "true", "srs": "EPSG:4326", "bbox": "-130,20,-60,55",
        "width": str(model.WIDTH), "height": str(model.HEIGHT),
    }
    overlay = model._png(WMS + "?" + urlencode(params))
    if overlay.size != (model.WIDTH, model.HEIGHT):
        raise data.DataError("HRRR service returned an unexpected map size")
    result = model._basemap().copy()
    result.alpha_composite(overlay)
    timing = f"Run {initialized:%d %b %H:%M UTC} · valid {valid:%d %b %H:%M UTC}"
    # Render a new, source-attributed forecast image from the WMS field and map.
    # Keep forecast status legible even when an image is saved outside the app.
    draw = ImageDraw.Draw(result)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle((0, 0, model.WIDTH, 35), fill=(12, 24, 36, 225))
    draw.text((10, 8), f"HRRR simulated reflectivity · {timing}", fill="white", font=font)
    draw.rectangle((0, model.HEIGHT - 28, model.WIDTH, model.HEIGHT), fill=(12, 24, 36, 225))
    draw.text((10, model.HEIGHT - 23), "Forecast, not observed radar · NCEP HRRR via Iowa Mesonet · USGS map · no numeric legend",
              fill="white", font=font)
    return result.convert("RGB"), timing
