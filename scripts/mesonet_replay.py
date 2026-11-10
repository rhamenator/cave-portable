"""Replay one locally supplied Oklahoma Mesonet MTS day without future observations.

Research utility. Obtain archive files under the Mesonet's own access terms.
No archive data is fetched, bundled, or redistributed by this program.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


FIELDS = ("TAIR", "RELH", "PRES", "WSPD", "WMAX", "WDIR", "RAIN")
UNITS = {"TAIR": "°C", "RELH": "%", "PRES": "hPa", "WSPD": "m/s",
         "WMAX": "m/s", "WDIR": "degrees", "RAIN": "mm since 00 UTC"}


@dataclass(frozen=True)
class Observation:
    station: str
    time: datetime
    values: dict[str, float | None]


def utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("offset required")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO time with a UTC offset") from exc


def read_mts(content: str) -> list[Observation]:
    """Parse the documented three-line header and five-minute station records."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) < 4 or "mesonet" not in lines[0].lower() or not any(
            marker in lines[0].lower() for marker in ("copyright", "(c)", "©")):
        raise ValueError("Expected an Oklahoma Mesonet MTS copyright header")
    metadata = lines[1].split()
    if len(metadata) != 7:
        raise ValueError("Expected variable count and six UTC base-time fields")
    try:
        count = int(metadata[0])
        base = datetime(*map(int, metadata[1:]), tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid MTS base time or variable count") from exc
    if not 1 <= count <= 80:
        raise ValueError("Invalid MTS variable count")
    names = lines[2].split()
    if names[:3] == ["STID", "STNM", "TIME"]:
        names = names[3:]
    if len(names) != count or len(set(names)) != count:
        raise ValueError("MTS variable list does not match header count")
    rows: list[Observation] = []
    station = None
    seen_times = set()
    for number, line in enumerate(lines[3:], start=4):
        parts = line.split()
        if len(parts) != count + 3:
            raise ValueError(f"MTS row {number} has the wrong number of columns")
        stid, stnm, minute_text = parts[:3]
        if not stid.isalnum() or not stnm.isdigit():
            raise ValueError(f"MTS row {number} has an invalid station")
        if station is None:
            station = stid
        if stid != station:
            raise ValueError("MTS station changed within a daily file")
        try:
            minute = int(minute_text)
            if not 0 <= minute < 1440:
                raise ValueError
            when = base + timedelta(minutes=minute)
            if when in seen_times:
                raise ValueError("Duplicate MTS observation time")
            seen_times.add(when)
            values = {}
            for name, raw in zip(names, parts[3:]):
                value = float(raw)
                if not math.isfinite(value):
                    raise ValueError
                values[name] = None if value <= -994 else value
        except ValueError as exc:
            raise ValueError(f"MTS row {number} has invalid time or value: {exc}") from exc
        rows.append(Observation(stid, when, values))
    if not rows:
        raise ValueError("MTS contains no observations")
    return sorted(rows, key=lambda row: row.time)


def dewpoint_c(temp_c: float | None, humidity: float | None) -> float | None:
    if temp_c is None or humidity is None or not 0 < humidity <= 100:
        return None
    gamma = math.log(humidity / 100) + 17.625 * temp_c / (243.04 + temp_c)
    return 243.04 * gamma / (17.625 - gamma)


def replay(rows: list[Observation], as_of: datetime, lookback: timedelta = timedelta(hours=3)) -> dict:
    if not rows or as_of.tzinfo is None or lookback <= timedelta(0):
        raise ValueError("Observations, offset-aware as-of, and positive lookback required")
    as_of = as_of.astimezone(timezone.utc)
    if not rows[0].time.date() == as_of.date():
        raise ValueError("As-of time must be on the supplied MTS UTC day")
    cutoff = as_of - lookback
    known = [row for row in rows if row.time <= as_of]
    window = [row for row in known if cutoff <= row.time]
    if not window:
        raise ValueError("No observations in the requested lookback window")
    latest = window[-1]
    anchor = max((row for row in known if row.time <= cutoff), key=lambda row: row.time, default=None)
    if anchor is not None and cutoff - anchor.time > timedelta(minutes=10):
        anchor = None
    observed_gaps = [(right.time - left.time).total_seconds() / 60
                     for left, right in zip(window, window[1:])]
    readings = {field.lower(): latest.values.get(field) for field in FIELDS}
    readings["dewpoint_derived_c"] = dewpoint_c(readings["tair"], readings["relh"])
    changes = {field.lower(): round(latest.values[field] - anchor.values[field], 2)
               if anchor and latest.values.get(field) is not None and anchor.values.get(field) is not None else None
               for field in ("TAIR", "RELH", "PRES", "WSPD")}
    return {
        "source": "locally supplied Oklahoma Mesonet MTS archive",
        "station": latest.station, "as_of_utc": as_of.isoformat(),
        "latest_observation_utc": latest.time.isoformat(),
        "latest_age_minutes": round((as_of - latest.time).total_seconds() / 60, 1),
        "stale_at_as_of": as_of - latest.time > timedelta(minutes=15),
        "lookback_hours": lookback.total_seconds() / 3600,
        "anchor_utc": anchor.time.isoformat() if anchor else None,
        "observations_in_window": len(window),
        "max_observed_gap_minutes": max(observed_gaps, default=None),
        "readings": readings, "changes_since_anchor": changes,
        "units": {field.lower(): UNITS[field] for field in FIELDS},
        "note": "Descriptive station observations, not a severe-weather forecast. Dewpoint is derived from temperature and relative humidity.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mts", type=Path, help="Locally supplied daily MTS file")
    parser.add_argument("--as-of", type=utc, required=True, help="Historical UTC cutoff; later rows are ignored")
    parser.add_argument("--lookback-hours", type=float, default=3)
    args = parser.parse_args()
    if not 0 < args.lookback_hours <= 12:
        parser.error("Lookback must be between 0 and 12 hours")
    if args.mts.stat().st_size > 2_000_000:
        parser.error("MTS file exceeds 2 MB")
    result = replay(read_mts(args.mts.read_text(encoding="utf-8")), args.as_of,
                    timedelta(hours=args.lookback_hours))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
