"""Read an archived Day 1 SPC outlook as it existed before a target event.

Research-only tool. Install with `pip install -e '.[research]'`.
The IEM archive reconstructs SPC polygons; it is not an operational alert feed.
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone


ARCHIVE = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/outlooks.py"
CATEGORY_ORDER = {"TSTM": 0, "MRGL": 1, "SLGT": 2, "ENH": 3, "MDT": 4, "HIGH": 5}


def utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("UTC offset required")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO time with a UTC offset") from exc


def archive_rows(day: datetime):
    """Fetch one day's IEM reconstruction; keep this out of the desktop runtime."""
    import shapefile

    start = (day - timedelta(days=1)).strftime("%Y-%m-%dT00:00Z")
    end = (day + timedelta(days=1)).strftime("%Y-%m-%dT00:00Z")
    url = ARCHIVE + "?" + urllib.parse.urlencode({"d": "1", "type": "C", "sts": start, "ets": end})
    request = urllib.request.Request(url, headers={"User-Agent": "CAVE-Portable-research/0.4.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("Archive response exceeded 5 MB")
    with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
        names = zipped.namelist()
        stem = next((name[:-4] for name in names if name.endswith(".shp")), None)
        if stem is None or any(stem + ext not in names for ext in (".shp", ".shx", ".dbf")):
            raise ValueError("Outlook archive omitted its shapefile")
        if any(zipped.getinfo(stem + ext).file_size > 12_000_000 for ext in (".shp", ".shx", ".dbf")):
            raise ValueError("Outlook shapefile exceeded its size limit")
        reader = shapefile.Reader(shp=io.BytesIO(zipped.read(stem + ".shp")),
                                  shx=io.BytesIO(zipped.read(stem + ".shx")),
                                  dbf=io.BytesIO(zipped.read(stem + ".dbf")))
        if len(reader) > 5000:
            raise ValueError("Outlook archive had too many polygons")
        return [(item.record.as_dict(), item.shape.__geo_interface__) for item in reader.iterShapeRecords()]


def point_outlook(rows, latitude: float, longitude: float, as_of: datetime, target: datetime) -> dict:
    """Select the latest issued outlook known as of `as_of`, then test its polygons."""
    from shapely.geometry import Point, shape

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and as_of <= target):
        raise ValueError("Invalid point or time order")
    valid = []
    for attributes, geometry in rows:
        try:
            issued = datetime.strptime(str(attributes["PRODISS"]), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            begins = datetime.strptime(str(attributes["ISSUE"]), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            expires = datetime.strptime(str(attributes["EXPIRE"]), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if (attributes.get("TYPE") == "C" and int(attributes.get("DAY", -1)) == 1
                and int(attributes.get("CYCLE", -1)) >= 0 and issued <= as_of and begins <= target < expires):
            valid.append((issued, attributes, geometry))
    if not valid:
        raise ValueError("No archived Day 1 outlook was issued before the requested time")
    issue = max(item[0] for item in valid)
    point = Point(longitude, latitude)
    selected = [(item[1]["CATEGORY"], item[1]["THRESHOLD"])
                for item in valid if item[0] == issue and shape(item[2]).covers(point)]
    categories = [threshold for category, threshold in selected if category == "CATEGORICAL"
                  and threshold in CATEGORY_ORDER]
    hazards = {}
    for hazard in ("TORNADO", "WIND", "HAIL"):
        levels = []
        for category, threshold in selected:
            if category == hazard and threshold != "SIGN":
                try:
                    levels.append(round(float(threshold) * 100))
                except ValueError:
                    pass
        hazards[hazard.lower()] = max(levels, default=None)
        hazards[hazard.lower() + "_significant"] = (hazard, "SIGN") in selected
    return {"source": "Iowa Environmental Mesonet archive of SPC-issued Day 1 polygons",
            "issued_utc": issue.isoformat(), "as_of_utc": as_of.isoformat(),
            "target_utc": target.isoformat(), "latitude": latitude, "longitude": longitude,
            "category": max(categories, key=CATEGORY_ORDER.get) if categories else None, **hazards}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=utc, required=True, help="What had been issued by this UTC time")
    parser.add_argument("--target", type=utc, required=True, help="UTC time the outlook is being checked for")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    args = parser.parse_args()
    if args.target - args.as_of > timedelta(days=1) or args.target < args.as_of:
        parser.error("Target must be within 24 hours after as-of time")
    result = point_outlook(archive_rows(args.as_of), args.lat, args.lon, args.as_of, args.target)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
