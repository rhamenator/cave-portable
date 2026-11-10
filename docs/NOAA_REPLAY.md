# NOAA observational event replay

This research workflow examines **observations** around historical weather events. It does not produce a tornado probability or a new warning. The one-minute airport observations originate with [NOAA NCEI](https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/) and are served in a processed CSV by the [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?help=). This archive is delayed about a day and may have been processed after the event. The radar replay uses [NOAA Level III NEXRAD digital radial data](https://www.ncei.noaa.gov/products/radar/next-generation-weather-radar) in a public archive and the app's existing decoder.

## Reproduce a station replay

From the repository root:

```bash
.venv/bin/python scripts/noaa_asos_replay.py --station OMA --as-of 2024-04-26T17:00Z
.venv/bin/python scripts/noaa_asos_replay.py --station OMA --as-of 2024-04-19T17:00Z
```

Station IDs here use the [IEM ASOS network's](https://mesonet.agron.iastate.edu/ASOS/) three-character form (`OMA`, `LAN`, `AZO`, `OKC`). The tool reports count and fraction of expected minute slots, largest gap, age of the latest report, missing-value counts, three-hour changes, and maximum observed wind and gust. It never uses a row later than `--as-of`. A saved response can be replayed with `--csv /path/to/file.csv`. Airport station pressure (`pres1`) is reported in inches of mercury; it is not sea-level pressure or an altimeter setting.

These are exploratory comparisons at the same station and UTC time one week apart. The earlier dates have **not** been verified as quiet days or matched controls. Each airport is a proxy some distance from the storm track. Event onset times come from [NWS Grand Rapids](https://www.weather.gov/grr/August24_2023_Tornadoes), [NWS Omaha](https://www.weather.gov/oax/april262024), and [NWS Grand Rapids's Portage review](https://www.weather.gov/grr/7_May_2024_SevereWeather).

| Event area / airport | Replay cutoff UTC | One-minute coverage | Three-hour air temperature / dewpoint / station-pressure change | Maximum five-second gust in window |
| --- | --- | --- | --- | --- |
| Webberville area / LAN | 24 Aug 2023 20:00 | 181/181 | +3°F / +6°F / −0.028 inHg | 24 kt |
| LAN, seven days earlier (unverified comparison) | 17 Aug 2023 20:00 | 181/181 | +8°F / +3°F / −0.015 inHg | 22 kt |
| Elkhorn area / OMA | 26 Apr 2024 17:00 | 181/181 | +2°F / +2°F / −0.051 inHg | 34 kt |
| OMA, seven days earlier (unverified comparison) | 19 Apr 2024 17:00 | 181/181 | +7°F / −5°F / +0.004 inHg | 23 kt |
| Portage area / AZO | 7 May 2024 18:00 | 181/181 | −5°F / +9°F / −0.065 inHg | 22 kt |
| AZO, seven days earlier (unverified comparison) | 30 Apr 2024 18:00 | 181/181 | +5°F / +1°F / +0.005 inHg | 30 kt |

The AZO earlier-date gust exceeded the event-day **pre-cutoff airport gust** in this tiny comparison. This illustrates why a station change alone cannot stand in for a forecast. The [NCEI May 2013 KOKC one-minute file](https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/2013/05/asos-1min-pg1-KOKC-201305.dat) has no records in the 14:00–20:00 UTC Moore pre-event window; the processed IEM query also returns none. That case should use other observations and mark the one-minute gap, not impute it.

## Southern and Plains event cohort

The [fixed cohort manifest](../research/noaa_cohort.json) adds eight NWS-documented cases across the states requested for the next observational study. Reproduce all station and radar checks with:

```bash
.venv/bin/python scripts/noaa_cohort_replay.py --radar > /tmp/cave-noaa-cohort.json
```

The station cutoff is **before** the listed event reference; the CC radar check is **at or near** the reference to confirm archive coverage. Each case also samples the same station and UTC time seven days earlier. Those earlier dates are unverified comparison dates, not established non-event controls. None of these station readings measures conditions directly on a tornado track.

| NWS-documented event | Station cutoff UTC / airport | Event-day minute slots | Archived CC scan at reference |
| --- | --- | ---: | --- |
| [Selma, Alabama, EF2](https://www.weather.gov/bmx/event_01122023) | 12 Jan 2023 17:00 / MGM | 181/181 | KBMX 18:03 UTC |
| [Rolling Fork, Mississippi, EF4](https://mesonet.agron.iastate.edu/wx/afos/p.php?e=202306062206&pil=PNSJAN) | 24 Mar 2023 23:00 / GLH | 181/181 | KDGX 25 Mar 00:55 UTC |
| [Griffin area, Georgia, EF3](https://www.weather.gov/ffc/20230112_Tornado_Map) | 12 Jan 2023 20:00 / FFC | 181/181 | KFFC 21:10 UTC |
| [Western Kentucky long-track EF4](https://www.weather.gov/pah/December-10th-11th-2021-Tornado) | 11 Dec 2021 01:00 / PAH | **0/181** | KPAH 02:49 UTC |
| [Clarksville, Tennessee, EF3](https://www.weather.gov/ohx/20231209) | 9 Dec 2023 18:00 / CKV | 181/181 | KOHX 19:44 UTC |
| [Bollinger County, Missouri, EF2](https://www.weather.gov/pah/april5Bollingertor) | 5 Apr 2023 07:00 / CGI | **43/181** | KPAH 08:33 UTC |
| [Little Rock, Arkansas, EF3](https://www.weather.gov/lzk/svr0323ayr.htm) | 31 Mar 2023 18:00 / LIT | **0/181** | KLZK 19:15 UTC |
| [Valley View area, Texas, EF3](https://www.weather.gov/fwd/events) | 26 May 2024 02:00 / DTO | 181/181 | KFWS 03:38 UTC |

These counts are from the IEM-processed NCEI one-minute service checked in November 2026. The Texas radar reference is a [03:38 UTC NWS confirmed-tornado update](https://mesonet.agron.iastate.edu/wx/afos/p.php?e=202405260338&pil=SVSFWD), **not** a surveyed onset time. The Kentucky reference is the long-track tornado's entry into Kentucky, rather than its arrival at Mayfield. All eight radar CC scans decoded after the Level III decoder was corrected to allow a forecast-office ID different from the radar site. The Arkansas selection skipped one later archive candidate because its decoded scan did not meet the cutoff or format checks. These results establish archive availability and gaps; they do not measure forecast performance or radar interpretation accuracy.

## Reproduce a historical radar scan

```bash
.venv/bin/python scripts/noaa_radar_replay.py --site OAX --product 'Correlation coefficient (CC)' --as-of 2024-04-26T20:30Z --bbox=-96.8,41.05,-95.8,41.65 --output /tmp/oax-cc.png
.venv/bin/python scripts/noaa_radar_replay.py --site GRR --product 'Digital velocity' --as-of 2023-08-25T01:29Z
```

The KOAX example selected a decoded 20:28:12 UTC CC scan and a 20:29:39 UTC reflectivity mask, both before the 20:30 cutoff. The script checks **decoded scan time** because an archive filename timestamp can precede the data inside it. It excludes products more than 30 minutes old, and the render masks dual-polarization values where reflectivity is below 10 dBZ. Low CC has multiple causes and does not establish a debris signature by itself. These scans show what radar measured near event time, not what could have been predicted hours earlier.

For the next observational case study, add NCEI Level II volumes, official warning issue times, and storm reports to a time-ordered display. Select event and control windows in advance and retain every data gap. Keep forecast-model comparisons separate from the observation replay.
