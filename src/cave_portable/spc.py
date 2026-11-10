"""Point-specific, source-attributed SPC Day 1 outlook values from NOAA GIS."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from . import data

SERVICE = "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/MapServer"
LAYERS = {"category": 1, "tornado": 3, "hail": 5, "wind": 7}
CATEGORIES = {2: "General thunderstorm", 3: "Marginal", 4: "Slight",
              5: "Enhanced", 6: "Moderate", 8: "High"}
PROBABILITIES = {
    "tornado": {2, 5, 10, 15, 30, 45, 60},
    "hail": {5, 15, 30, 45, 60},
    "wind": {5, 15, 30, 45, 60},
}


@dataclass(frozen=True)
class PointGuidance:
    issue: datetime
    valid: datetime
    expire: datetime
    category: str | None
    tornado: int | None
    hail: int | None
    wind: int | None

    def summary(self, place: str) -> str:
        category = self.category or "No outlined SPC category at this point"
        hazards = " · ".join(f"{name.title()}: {value}%" if value is not None else f"{name.title()}: not outlined"
                             for name, value in (("tornado", self.tornado), ("hail", self.hail), ("wind", self.wind)))
        return (f"SPC Day 1 at {place}: {category}\n{hazards}\n"
                f"Issued {self.issue:%d %b %H:%M UTC} · valid {self.valid:%d %b %H:%M}–{self.expire:%d %b %H:%M UTC}. "
                "These are official outlook areas, not a local warning or a zero-risk guarantee.")


def _time(value) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise data.DataError("SPC outlook time was invalid") from exc


def _query(layer: int, lat: float | None = None, lon: float | None = None) -> list[dict]:
    params = {"where": "1=1", "outFields": "dn,issue,valid,expire", "returnGeometry": "false", "f": "json"}
    if lat is not None and lon is not None:
        params.update({"geometry": f"{lon:.4f},{lat:.4f}", "geometryType": "esriGeometryPoint",
                       "inSR": "4326", "spatialRel": "esriSpatialRelIntersects"})
    payload = data._json(f"{SERVICE}/{layer}/query?" + urlencode(params))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list) or payload.get("error"):
        raise data.DataError("SPC outlook service returned an invalid response")
    return [item["attributes"] for item in payload["features"]
            if isinstance(item, dict) and isinstance(item.get("attributes"), dict)]


def _identify(lat: float, lon: float) -> dict[int, list[dict]]:
    """One spatial request for the four official Day 1 outlook layers."""
    params = {"geometry": f"{lon:.4f},{lat:.4f}", "geometryType": "esriGeometryPoint",
              "sr": "4326", "layers": "all:1,3,5,7", "tolerance": "0",
              "mapExtent": f"{lon-1:.4f},{lat-1:.4f},{lon+1:.4f},{lat+1:.4f}",
              "imageDisplay": "960,500,96", "returnGeometry": "false", "f": "json"}
    payload = data._json(f"{SERVICE}/identify?" + urlencode(params))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list) or payload.get("error"):
        raise data.DataError("SPC point outlook service returned an invalid response")
    output = {layer: [] for layer in LAYERS.values()}
    for result in payload["results"]:
        if not isinstance(result, dict) or result.get("layerId") not in output or not isinstance(result.get("attributes"), dict):
            continue
        attributes = result["attributes"]
        try:
            level = int(attributes.get("dn value", attributes.get("dn")))
        except (TypeError, ValueError) as exc:
            raise data.DataError("SPC point outlook contained an invalid risk value") from exc
        output[result["layerId"]].append({"dn": level, "issue": attributes.get("issue"),
                                          "valid": attributes.get("valid"), "expire": attributes.get("expire")})
    return output


def point_guidance(lat: float, lon: float, now: datetime | None = None) -> PointGuidance:
    if not (math.isfinite(lat) and math.isfinite(lon) and 24 <= lat <= 50 and -126 <= lon <= -66):
        raise data.DataError("SPC Day 1 point guidance covers the contiguous US")
    catalog = _query(LAYERS["category"])
    if not catalog:
        raise data.DataError("SPC Day 1 outlook issue time is unavailable")
    issue = max(_time(row.get("issue")) for row in catalog)
    latest = next(row for row in catalog if _time(row.get("issue")) == issue)
    valid, expire = _time(latest.get("valid")), _time(latest.get("expire"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if issue > current + timedelta(minutes=30) or expire <= current or valid >= expire:
        raise data.DataError("SPC Day 1 outlook is outside its valid period")
    identified = _identify(lat, lon)
    values = {}
    for name, layer in LAYERS.items():
        rows = identified[layer]
        matched = [row for row in rows if _time(row.get("issue")) == issue
                   and _time(row.get("valid")) == valid and _time(row.get("expire")) == expire]
        if rows and not matched:
            raise data.DataError(f"SPC {name} layer did not match the current outlook")
        allowed = CATEGORIES if name == "category" else PROBABILITIES[name]
        levels = [row["dn"] for row in matched if isinstance(row.get("dn"), int) and row["dn"] in allowed]
        if len(levels) != len(matched):
            raise data.DataError(f"SPC {name} layer contained an unknown value")
        values[name] = max(levels) if levels else None
    return PointGuidance(issue, valid, expire, CATEGORIES.get(values["category"]),
                         values["tornado"], values["hail"], values["wind"])
