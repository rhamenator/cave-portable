"""Summarize archived NOAA one-minute ASOS observations at a historical cutoff.

Research-only; Iowa Environmental Mesonet transcodes NCEI's ASOS archive.
Archive observation time does not prove the value was available in real time.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


ENDPOINT = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py"
FIELDS = ("tmpf", "dwpf", "sknt", "gust_sknt", "pres1")
UNITS = {"tmpf": "°F", "dwpf": "°F", "sknt": "kt", "gust_sknt": "kt",
         "pres1": "inHg station pressure"}


def utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("offset required")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO time with a UTC offset") from exc


def request_url(station: str, start: datetime, end: datetime) -> str:
    station = station.upper()
    if not re.fullmatch(r"[A-Z0-9]{3,4}", station) or not start < end:
        raise ValueError("Use a three- or four-character station and ordered times")
    parameters = [("station", station), ("sts", start.strftime("%Y-%m-%dT%H:%MZ")),
                  ("ets", end.strftime("%Y-%m-%dT%H:%MZ")),
                  ("sample", "1min"), ("what", "view"), ("tz", "UTC")]
    parameters += [("vars", field) for field in FIELDS]
    return ENDPOINT + "?" + urllib.parse.urlencode(parameters)


def fetch_csv(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "CAVE-Portable-research/0.4.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("ASOS response exceeds 1 MB")
    return raw.decode("utf-8")


def parse_csv(content: str, station: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    required = {"station", "valid(UTC)", *FIELDS}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("ASOS response has no expected CSV columns")
    rows = []
    seen = set()
    for raw in reader:
        if raw["station"] != station or not raw["valid(UTC)"]:
            raise ValueError("ASOS response contains a different station or missing time")
        try:
            when = datetime.strptime(raw["valid(UTC)"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            if when in seen:
                raise ValueError("duplicate time")
            seen.add(when)
            values = {}
            for field in FIELDS:
                value = raw[field]
                number = None if value in ("", "M", None) else float(value)
                if number is not None and not math.isfinite(number):
                    raise ValueError("non-finite value")
                values[field] = number
        except ValueError as exc:
            raise ValueError(f"Invalid ASOS row: {exc}") from exc
        rows.append({"time": when, "values": values})
    return sorted(rows, key=lambda row: row["time"])


def summarize(rows: list[dict], station: str, as_of: datetime,
              lookback: timedelta = timedelta(hours=3)) -> dict:
    if as_of.tzinfo is None or not timedelta(0) < lookback <= timedelta(hours=12):
        raise ValueError("Use an offset-aware cutoff and a lookback of at most 12 hours")
    as_of = as_of.astimezone(timezone.utc)
    start = as_of - lookback
    known = [row for row in rows if row["time"] <= as_of]
    window = [row for row in known if start <= row["time"]]
    if not window:
        return {"source": "NCEI one-minute ASOS via Iowa Environmental Mesonet",
                "station": station, "as_of_utc": as_of.isoformat(),
                "window_start_utc": start.isoformat(), "status": "no_observations",
                "observation_count": 0}
    latest = window[-1]
    anchor = max((row for row in known if row["time"] <= start),
                 key=lambda row: row["time"], default=None)
    if anchor and start - anchor["time"] > timedelta(minutes=5):
        anchor = None
    gaps = [(right["time"] - left["time"]).total_seconds() / 60
            for left, right in zip(window, window[1:])]
    values = latest["values"]
    changes = {field: round(values[field] - anchor["values"][field], 3)
               if anchor and values[field] is not None and anchor["values"][field] is not None else None
               for field in ("tmpf", "dwpf", "sknt", "pres1")}
    maxima = {field: max((row["values"][field] for row in window
                          if row["values"][field] is not None), default=None)
              for field in ("sknt", "gust_sknt")}
    count_expected = int(lookback.total_seconds() // 60) + 1
    return {"source": "NCEI one-minute ASOS via Iowa Environmental Mesonet",
            "station": station, "as_of_utc": as_of.isoformat(),
            "window_start_utc": start.isoformat(), "status": "observed",
            "latest_observation_utc": latest["time"].isoformat(),
            "latest_age_minutes": round((as_of - latest["time"]).total_seconds() / 60, 1),
            "stale_at_as_of": as_of - latest["time"] > timedelta(minutes=15),
            "observation_count": len(window), "expected_one_minute_slots": count_expected,
            "coverage_fraction": round(len(window) / count_expected, 3),
            "max_observed_gap_minutes": max(gaps, default=None),
            "anchor_utc": anchor["time"].isoformat() if anchor else None,
            "latest_values": values, "changes_since_anchor": changes,
            "maxima_in_window": maxima, "missing_value_counts": {
                field: sum(row["values"][field] is None for row in window) for field in FIELDS},
            "units": UNITS,
            "note": "Descriptive airport observations only; archived values may have been processed after the event."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", required=True, help="IEM ASOS ID, e.g. LAN or OMA")
    parser.add_argument("--as-of", required=True, type=utc)
    parser.add_argument("--lookback-hours", type=float, default=3)
    parser.add_argument("--csv", type=Path, help="Read a saved IEM CSV instead of fetching")
    args = parser.parse_args()
    station = args.station.upper()
    if not 0 < args.lookback_hours <= 12:
        parser.error("Lookback must be between 0 and 12 hours")
    lookback = timedelta(hours=args.lookback_hours)
    url = request_url(station, args.as_of - lookback - timedelta(minutes=5),
                      args.as_of + timedelta(minutes=1))
    if args.csv:
        if args.csv.stat().st_size > 1_000_000:
            parser.error("Saved ASOS CSV exceeds 1 MB")
        content = args.csv.read_text(encoding="utf-8")
    else:
        content = fetch_csv(url)
    result = summarize(parse_csv(content, station), station, args.as_of, lookback)
    result["archive_request"] = url
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
