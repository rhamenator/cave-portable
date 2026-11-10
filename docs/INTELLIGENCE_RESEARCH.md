# Weather intelligence and validation

The desktop app displays official SPC/NWS guidance, live radar, model imagery, and a descriptive airport trend. It does not issue a locally generated severe-weather probability. This research workflow tests whether a future candidate adds useful lead time without using information issued after the forecast was made.

## What the colleague source establishes

The privately archived station dashboard includes pressure, dewpoint, humidity, and wind heuristics, plus an LLM prompt that asks for a 6–12 hour forecast and numeric risk percentages. The inspected repository contains no timestamped historical predictions and no comparison against SPC issuance times or observed events. Its claim of anticipating later SPC concern therefore remains unverified. Private source and assets are not copied here.

## A first issue-time replay

The research-only [`outlook_replay.py`](../scripts/outlook_replay.py) reads the Iowa Environmental Mesonet's reconstructed archive of SPC-issued Day 1 outlook polygons. It selects only polygons whose product issuance preceded `--as-of`, whose valid period covers `--target`, and whose geometry contains the requested point. Install optional research dependencies with `python -m pip install -e '.[research]'`.

Example: `python scripts/outlook_replay.py --as-of 2023-08-24T20:00Z --target 2023-08-25T01:29Z --lat 42.66 --lon -84.18`

| Point and event | What SPC had issued by the chosen time | Target |
| --- | --- | --- |
| Approximate Webberville, MI; as of 24 Aug 2023 20:00 UTC | Enhanced; tornado 5%, damaging wind 30%, significant-wind area; issued 19:55 UTC | 25 Aug 01:29 UTC tornado onset |
| Approximate Elkhorn, NE; as of 26 Apr 2024 17:00 UTC | Enhanced; tornado 10%, hail 30%, significant-tornado and significant-hail areas; issued 16:42 UTC | 20:30 UTC tornado onset |
| Approximate Newcastle, OK; as of 20 May 2013 17:00 UTC | Moderate; tornado 10%, hail 45%; issued 16:31 UTC | 19:56 UTC tornado onset |

These probabilities describe an event **within 25 miles of a point** over the outlook period, not the odds of a tornado at that exact address. An outlook can correctly flag a regional environment while the location, timing, and form of a particular tornado remain surprising. The Webberville area had a regional wind and tornado signal several hours before the tornado, consistent with the [NWS Grand Rapids event review](https://www.weather.gov/grr/August24_2023_Tornadoes) and [NWS Detroit's wind-dominant analysis](https://www.weather.gov/dtx/tornadoes08242023). This comparison does not verify the colleague's prediction claim; no dated outputs from that program were available to place on the same timeline.

## Validation cohort

1. Sample all days, including quiet days, in higher-activity regions: southern and central Plains (OK, KS, NE, north TX), lower Mississippi Valley/Deep South, and Midwest/Great Lakes. Include lower-activity regions as transfer tests. Select spatial grid cells before inspecting outcomes so the data set is not composed only of memorable storms.
2. For each cell and issuance time, preserve the exact information available then: source, issue and valid times, location, model cycle, forecast lead, missing-data flags, and a hash of the candidate's output. Do not train on later SPC revisions, warnings, radar scans, or storm reports.
3. Use archived surface observations, model analyses/forecasts, radar, and official SPC outlooks as distinct inputs. [Oklahoma Mesonet](https://www.mesonet.org/about/technical-information) has unusually dense five-minute observations. The local-file [Mesonet MTS replay](MESONET_ARCHIVE.md) is ready for archive data obtained under its [access terms](https://www.mesonet.org/about/data-access-and-pricing). The Aviation Weather Center's live API covers only the recent 30 days, so historical replay uses appropriate archives.
4. Verify hazard occurrence and location against [NCEI Storm Events](https://www.ncei.noaa.gov/access/storm-events-database/) and the [Severe Weather Data Inventory](https://www.ncei.noaa.gov/products/severe-weather-data-inventory), accounting for their incomplete and delayed reporting. Compare with SPC outlooks issued at the same or earlier time, not with a later revision as if it were known in advance.
5. Split training and evaluation by storm day, year, and region. Report lead time, event detection, false alarms per cell-day, precision, calibration, Brier score, and performance by region and data availability. Only a prospectively recorded, well-calibrated result should be considered for an experimental public display.

Until then, airport pressure trends are presented as observations. SPC/NWS products retain their own labels and times; the app does not turn station heuristics or LLM prose into emergency alerts.
