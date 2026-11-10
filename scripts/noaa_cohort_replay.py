"""Run the fixed Southern/Plains NOAA observational replay cohort.

No station or radar measurements are stored in the source manifest.
Comparison dates are the same station and UTC time seven days before each event.
They have not been verified as non-event controls.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from cave_portable.data import DataError
if __package__:
    from .noaa_asos_replay import fetch_csv, parse_csv, request_url, summarize, utc
    from .noaa_radar_replay import archived_field
else:
    from noaa_asos_replay import fetch_csv, parse_csv, request_url, summarize, utc
    from noaa_radar_replay import archived_field


MANIFEST = Path(__file__).resolve().parent.parent / "research" / "noaa_cohort.json"


def station_summary(station: str, as_of):
    start = as_of - timedelta(hours=3, minutes=5)
    url = request_url(station, start, as_of + timedelta(minutes=1))
    summary = summarize(parse_csv(fetch_csv(url), station), station, as_of)
    summary["archive_request"] = url
    return summary


def run_case(case: dict, radar: bool = False) -> dict:
    as_of = utc(case["as_of_utc"])
    reference = utc(case["reference_utc"])
    if as_of >= reference:
        raise ValueError("Station cutoff must precede the event reference time")
    station = case["station"]
    result = {"id": case["id"], "state": case["state"], "event": case["event"],
              "reference_utc": reference.isoformat(),
              "reference_kind": case["reference_kind"], "nws_source": case["source"],
              "station": station,
              "event_day": station_summary(station, as_of),
              "seven_day_comparison": station_summary(station, as_of - timedelta(days=7))}
    if radar:
        radar_time = utc(case["radar_as_of_utc"])
        try:
            field, key, skipped = archived_field(case["radar_site"], "N0C", radar_time)
            result["radar_cc"] = {"status": "decoded", "site": "K" + case["radar_site"],
                                  "as_of_utc": radar_time.isoformat(), "scan_utc": field.time.isoformat(),
                                  "archive_key": key, "skipped_archive_candidates": skipped}
        except DataError as exc:
            result["radar_cc"] = {"status": "unavailable_or_unsupported",
                                  "site": "K" + case["radar_site"], "as_of_utc": radar_time.isoformat(),
                                  "reason": str(exc)}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Run one cohort ID; default runs all")
    parser.add_argument("--radar", action="store_true", help="Also inspect archived CC scans")
    args = parser.parse_args()
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = [case for case in cases if not args.case or case["id"] == args.case]
    if not selected:
        parser.error("Unknown case ID")
    print(json.dumps([run_case(case, args.radar) for case in selected], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
