# NOAA observational event replay

This research workflow examines **observations** around historical weather events. It does not produce a tornado probability or a new warning. The one-minute airport observations originate with [NOAA NCEI](https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/) and are served in a processed CSV by the [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?help=). This archive is delayed about a day and may have been processed after the event. The radar replay uses [NOAA Level III NEXRAD digital radial data](https://www.ncei.noaa.gov/products/radar/next-generation-weather-radar) in a public archive and the app's existing decoder.

## Reproduce a station replay

From the repository root:

```bash
.venv/bin/python scripts/noaa_asos_replay.py --station OMA --as-of 2024-04-26T17:00Z
.venv/bin/python scripts/noaa_asos_replay.py --station OMA --as-of 2024-04-19T17:00Z
```

Station IDs here use the [IEM ASOS network's](https://mesonet.agron.iastate.edu/ASOS/) three-character form (`OMA`, `LAN`, `AZO`, `OKC`). The tool reports count and fraction of expected minute slots, largest gap, age of the latest report, missing-value counts, three-hour changes, and maximum observed wind and gust. It never uses a row later than `--as-of`. A saved response can be replayed with `--csv /path/to/file.csv`. Airport station pressure (`pres1`) is reported in inches of mercury; it is not sea-level pressure or an altimeter setting.

These are exploratory comparisons at the same station and UTC time one week apart. The quiet days were selected for a quick data check, not as a matched validation sample. Each airport is a proxy some distance from the storm track. Event onset times come from [NWS Grand Rapids](https://www.weather.gov/grr/August24_2023_Tornadoes), [NWS Omaha](https://www.weather.gov/oax/april262024), and [NWS Grand Rapids's Portage review](https://www.weather.gov/grr/7_May_2024_SevereWeather).

| Event area / airport | Replay cutoff UTC | One-minute coverage | Three-hour air temperature / dewpoint / station-pressure change | Maximum five-second gust in window |
| --- | --- | --- | --- | --- |
| Webberville area / LAN | 24 Aug 2023 20:00 | 181/181 | +3°F / +6°F / −0.028 inHg | 24 kt |
| LAN, seven days earlier | 17 Aug 2023 20:00 | 181/181 | +8°F / +3°F / −0.015 inHg | 22 kt |
| Elkhorn area / OMA | 26 Apr 2024 17:00 | 181/181 | +2°F / +2°F / −0.051 inHg | 34 kt |
| OMA, seven days earlier | 19 Apr 2024 17:00 | 181/181 | +7°F / −5°F / +0.004 inHg | 23 kt |
| Portage area / AZO | 7 May 2024 18:00 | 181/181 | −5°F / +9°F / −0.065 inHg | 22 kt |
| AZO, seven days earlier | 30 Apr 2024 18:00 | 181/181 | +5°F / +1°F / +0.005 inHg | 30 kt |

The AZO quiet-day gust exceeded the event-day **pre-cutoff airport gust** in this tiny comparison. This illustrates why a station change alone cannot stand in for a forecast. The [NCEI May 2013 KOKC one-minute file](https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/2013/05/asos-1min-pg1-KOKC-201305.dat) has no records in the 14:00–20:00 UTC Moore pre-event window; the processed IEM query also returns none. That case should use other observations and mark the one-minute gap, not impute it.

## Reproduce a historical radar scan

```bash
.venv/bin/python scripts/noaa_radar_replay.py --site OAX --product 'Correlation coefficient (CC)' --as-of 2024-04-26T20:30Z --bbox=-96.8,41.05,-95.8,41.65 --output /tmp/oax-cc.png
.venv/bin/python scripts/noaa_radar_replay.py --site GRR --product 'Digital velocity' --as-of 2023-08-25T01:29Z
```

The KOAX example selected a decoded 20:28:12 UTC CC scan and a 20:29:39 UTC reflectivity mask, both before the 20:30 cutoff. The script checks **decoded scan time** because an archive filename timestamp can precede the data inside it. It excludes products more than 30 minutes old, and the render masks dual-polarization values where reflectivity is below 10 dBZ. Low CC has multiple causes and does not establish a debris signature by itself. These scans show what radar measured near event time, not what could have been predicted hours earlier.

For the next observational case study, add NCEI Level II volumes, official warning issue times, and storm reports to a time-ordered display. Select event and control windows in advance and retain every data gap. Keep forecast-model comparisons separate from the observation replay.
