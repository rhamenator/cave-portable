"""Explicit US ZIP and Canadian postal locations; no IP location inference."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from . import data


@dataclass(frozen=True)
class PostalLocation:
    country: str
    code: str
    locality: str
    region: str
    lat: float
    lon: float
    approximate: bool
    street: str = ""

    @property
    def label(self) -> str:
        if self.street:
            return f"{self.street}, {self.code} (geocoded address; approximate)"
        suffix = " (FSA centroid; approximate)" if self.approximate else " (ZIP centroid)"
        return f"{self.code} · {self.locality}, {self.region}{suffix}"


def validate_postal(country: str, code: str) -> tuple[str, str]:
    country = country.strip().upper()
    code = code.strip().upper()
    if country == "US":
        if not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", code):
            raise data.DataError("Enter a five-digit US ZIP code (ZIP+4 also accepted)")
        return country, code
    if country == "CA":
        code = re.sub(r"\s+", "", code)
        if not re.fullmatch(r"[ABCEGHJ-NPRSTVXY][0-9][ABCEGHJ-NPRSTV-Z][0-9][ABCEGHJ-NPRSTV-Z][0-9]", code):
            raise data.DataError("Enter a full six-character Canadian postal code, such as K1A 0B1")
        return country, code[:3] + " " + code[3:]
    raise data.DataError("Choose United States or Canada")


def resolve(country: str, code: str, street: str = "") -> PostalLocation:
    country, code = validate_postal(country, code)
    street = street.strip()
    if street and (len(street) > 120 or not re.fullmatch(r"[\w .,'#/-]+", street, re.UNICODE)):
        raise data.DataError("Enter a street address of at most 120 ordinary characters")
    query = code[:5] if country == "US" else code[:3]
    payload = data._json(f"https://api.zippopotam.us/{country.lower()}/{query}")
    places = payload.get("places") if isinstance(payload, dict) else None
    if not isinstance(places, list) or not places or not isinstance(places[0], dict):
        raise data.DataError("Postal code was not found")
    place = places[0]
    try:
        lat, lon = float(place["latitude"]), float(place["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise data.DataError("Postal service returned invalid coordinates") from exc
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise data.DataError("Postal service returned invalid coordinates")
    locality = str(place.get("place name") or "Postal area")[:80]
    region = str(place.get("state abbreviation") or place.get("state") or "")[:40]
    if street:
        if country == "US":
            url = "https://geocoding.geo.census.gov/geocoder/locations/address?" + urlencode({"street": street, "zip": code[:5], "benchmark": "Public_AR_Current", "format": "json"})
            result = data._json(url)
            matches = result.get("result", {}).get("addressMatches", []) if isinstance(result, dict) else []
            matches = [m for m in matches if str(m.get("addressComponents", {}).get("zip")) == code[:5]]
            if not matches:
                raise data.DataError("Street address did not match the required ZIP code")
            coordinates = matches[0].get("coordinates", {})
            lat, lon = float(coordinates["y"]), float(coordinates["x"])
        else:
            url = "https://geolocator.api.geo.ca/?" + urlencode({"q": f"{street}, {locality}, {region}", "lang": "en", "keys": "locate,nominatim"})
            results = data._json(url)
            if not isinstance(results, list):
                raise data.DataError("Canadian address service returned an invalid response")
            candidates = []
            house = re.match(r"\d+[A-Z]?", street.upper())
            for item in results:
                if not isinstance(item, dict) or item.get("category") not in ("Street", "Place", "Office", "Building", "Address"):
                    continue
                if house and not re.search(r"\b" + re.escape(house.group()) + r"\b", str(item.get("name") or "").upper()):
                    continue
                try:
                    y, x = float(item["lat"]), float(item["lng"])
                except (KeyError, TypeError, ValueError):
                    continue
                distance = math.hypot(y-lat, (x-lon)*math.cos(math.radians(lat))) * 111
                if distance < 100:
                    candidates.append((distance, y, x))
            if not candidates:
                raise data.DataError("Street address could not be verified near this postal area")
            _, lat, lon = min(candidates)
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise data.DataError("Address service returned invalid coordinates")
    return PostalLocation(country, code, locality, region, lat, lon, country == "CA" or bool(street), street)
