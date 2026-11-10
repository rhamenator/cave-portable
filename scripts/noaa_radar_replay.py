"""Select and optionally render an archived NOAA Level III radar scan by UTC cutoff.

This research tool reuses CAVE Portable's bounded digital radial decoder.
It does not identify a tornado or confirm debris from correlation coefficient.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from cave_portable.data import DataError, _fetch
from cave_portable.level3 import BUCKET, KEY, MAX_FILE, PRODUCTS, _day_keys, decode, product_for_tilt, render


def utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("offset required")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO time with a UTC offset") from exc


def candidate_keys(site: str, product: str, as_of: datetime,
                   max_age: timedelta = timedelta(minutes=30)) -> list[tuple[str, datetime]]:
    if not re.fullmatch(r"[A-Z0-9]{3}", site) or as_of.tzinfo is None:
        raise ValueError("Use a three-character radar site and offset-aware cutoff")
    as_of = as_of.astimezone(timezone.utc)
    candidates = set()
    for day in (as_of - timedelta(days=1), as_of):
        for key in _day_keys(site, product, day.strftime("%Y_%m_%d"), 0):
            match = KEY.fullmatch(key)
            if match:
                stamp = datetime.strptime(match["time"], "%Y_%m_%d_%H_%M_%S").replace(tzinfo=timezone.utc)
                if stamp <= as_of and as_of - stamp <= max_age:
                    candidates.add((stamp, key))
    return [(key, stamp) for stamp, key in sorted(candidates, reverse=True)]


def archived_field(site: str, product: str, as_of: datetime):
    skipped = 0
    for key, stamp in candidate_keys(site, product, as_of):
        try:
            field = decode(_fetch(BUCKET + quote(key), MAX_FILE, "application/octet-stream"), site, product)
        except DataError:
            skipped += 1
            continue
        if abs(field.time - stamp) > timedelta(minutes=2):
            skipped += 1
            continue
        if field.time <= as_of and as_of - field.time <= timedelta(minutes=30):
            return field, key, skipped
    raise DataError(f"No decodable archived scan at or before cutoff within 30 minutes ({skipped} skipped)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, help="Three-character WSR-88D site, e.g. OAX")
    parser.add_argument("--product", required=True, choices=tuple(PRODUCTS))
    parser.add_argument("--tilt", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--as-of", type=utc, required=True)
    parser.add_argument("--bbox", help="west,south,east,north for optional PNG")
    parser.add_argument("--output", type=Path, help="Write a rendered PNG")
    args = parser.parse_args()
    if bool(args.bbox) != bool(args.output):
        parser.error("Provide both --bbox and --output for an image")
    site = args.site.upper()
    product, _number, units = product_for_tilt(args.product, args.tilt)
    field, key, skipped = archived_field(site, product, args.as_of)
    result = {"source": "NOAA archived NEXRAD Level III digital radial data via public Unidata bucket",
              "site": "K" + site, "product": args.product, "code": product,
              "scan_utc": field.time.isoformat(), "as_of_utc": args.as_of.isoformat(),
              "scan_age_minutes": round((args.as_of - field.time).total_seconds() / 60, 1),
              "elevation_degrees": field.elevation, "units": units, "archive_key": key,
              "skipped_archive_candidates": skipped,
              "note": "Observed radar only; low CC alone does not confirm debris."}
    reflectivity = None
    if args.output and product[-1] in "CXK":
        reflectivity, mask_key, mask_skipped = archived_field(site, f"N{args.tilt}B", args.as_of)
        if abs(field.time - reflectivity.time) > timedelta(minutes=5):
            raise DataError("Reflectivity mask and selected scan do not match")
        result["reflectivity_mask_scan_utc"] = reflectivity.time.isoformat()
        result["reflectivity_mask_key"] = mask_key
        result["reflectivity_mask_skipped_candidates"] = mask_skipped
        result["mask_rule"] = "Dual-pol values hidden where reflectivity is below 10 dBZ"
    if args.output:
        image = render(field, args.bbox, reflectivity)
        image.save(args.output, format="PNG")
        result["image"] = str(args.output.resolve())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
