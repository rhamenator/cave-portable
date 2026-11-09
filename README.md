# CAVE Portable

A lightweight, cross-platform weather viewer inspired by the needs of AWIPS CAVE users. This is an **independent companion**, not a fork or replacement for the full AWIPS CAVE workstation. It runs without an EDEX server and does not issue warnings or generate its own convective forecast.

## What works in 0.1.0

- National radar composite from NOAA/NWS, single-site reflectivity and storm-relative Doppler velocity from Iowa Environmental Mesonet, and GOES East/West GeoColor satellite imagery from NOAA/NESDIS.
- Current METAR observations at 24 US airports, direct ICAO station lookup, raw METAR and TAF, and active NWS alerts by state.
- Official SPC Day 1–3 categorical convective outlook maps, current Southern Plains mixed-layer CAPE analysis, and 0–72 hour GFS surface-based CAPE forecasts from NSF Unidata THREDDS. The outlook is the forecast guidance; CAPE is only one ingredient in severe weather potential.
- A required US ZIP or full Canadian postal code for local weather and alerts. An optional small temperature/conditions window uses the nearest reporting airport; opt-in NWS/ECCC warning monitoring uses a postal-area centroid with a system bell and message box. Start at login is optional.
- Background network loading, 60-second refresh for observations/radar/satellite and NWS alerts, source-time checks on imagery, bounded downloads, and no EDEX dependency.

The app is designed to start and remain responsive on machines below the [8 GB minimum](https://unidata.github.io/awips2/install/install-cave/) listed for full CAVE. Resource measurements and wider platform validation are still needed before claiming a specific RAM target. See [Scope and roadmap](docs/ROADMAP.md).

## Install

### Desktop bundles

Tagged builds produce downloadable Windows, macOS Intel/Apple Silicon, and Linux archives on GitHub Releases. These bundles are currently **unsigned**. Extract the archive and launch `CAVE-Portable.exe`, `CAVE-Portable.app`, or `CAVE-Portable`. A signed installer and cross-distribution Linux package are planned. The Linux executable uses the build runner's glibc baseline and may not work on older distributions.

### From source (Linux, Windows, macOS)

Install Python 3.10 or later, Tk, and Python's `venv` module. On Debian/Ubuntu, install `python3-tk` and `python3-venv`; on Fedora/RHEL, install `python3-tkinter`; on Arch, install `tk`. Tk and `venv` are included with standard Python installers on Windows and macOS. Then:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
cave-portable
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and run `cave-portable`. No administrator access or EDEX server is required.

## Use

Choose **Observations**, **Radar**, **Satellite**, **Severe outlook & CAPE**, or **Forecast CAPE**. Select a station in the observations table to read the raw METAR. Enter a four-character ICAO code and choose **Load station** for the latest METAR and TAF. Enter a two-letter US state code for active NWS alerts; the top button refreshes its count every minute and opens the alert detail. In Radar, choose a national mosaic or a curated radar site for reflectivity or storm-relative velocity. Select Day 1, 2, or 3 to see SPC's forecast severe weather areas. **Southern Plains MLCAPE** is a regional analysis; **Forecast CAPE** is a GFS model forecast from a best-available time series that may combine model runs. Neither is a warning or a reliable severity measure on its own.

For local weather and alerts, choose **US** or **CA**, enter a valid five-digit ZIP (ZIP+4 accepted) or a full six-character Canadian postal code, optionally enter a street address, and choose **Set ZIP / postal code**. The app never infers location from an IP address. The mini window labels temperature and conditions as a nearby airport observation, including station and observation time. Select **Monitor official warnings at postal area** to poll NWS severe/extreme point alerts in the US or ECCC weather warnings in Canada every minute while running. New warnings ring the system bell and open a message box; repeat polls do not repeat the same alert. **Start at login** registers only this user's login startup entry. These options are off by default and require a set postal location. Closing the main window stops the monitor. The mini window is not a system tray service.

Without a street address, the US lookup uses the ZIP centroid. Canadian postal lookup uses only the first three characters (the forward sortation area, or FSA) and its centroid, even though entering the full code is required. A street address refines US coordinates through the US Census geocoder or Canadian coordinates through Natural Resources Canada's Geolocator. These geocodes are still **approximations** and may differ from your address or an alert polygon boundary. The weather bug reports airport weather, which may differ from conditions at your location. Europe coverage is planned only if suitable live weather and official alert data can be verified.

Weather data can be delayed, missing, or unavailable. The app refuses radar scans and national radar imagery older than 15 minutes, and satellite imagery older than 30 minutes. It shows the source timestamp; forecasts and outlooks have separate valid times. The alert monitor is an internet-dependent API client, **not an Emergency Alert System (EAS) or Wireless Emergency Alerts (WEA) receiver**. It cannot guarantee delivery or audibility. This software is for education and situational awareness. **For shelter decisions, use [weather.gov](https://www.weather.gov/) in the US, [weather.gc.ca](https://weather.gc.ca/) in Canada, mobile emergency alerts, weather radio, and official local instructions.** The GPL license includes a no-warranty clause.

Other public-safety alerts, including AMBER alerts, are not available in the current weather-only feeds. See [Alert coverage and limits](docs/ALERTS.md) for the US/Canada distinction and the planned opt-in AMBER category.

## Data and network

The application sends read-only HTTPS requests to NOAA/NWS/NESDIS/SPC, ECCC, Zippopotam.us, US Census, Natural Resources Canada, NSF Unidata THREDDS, USGS, and Iowa Environmental Mesonet endpoints in [data.py](src/cave_portable/data.py), [location.py](src/cave_portable/location.py), [model.py](src/cave_portable/model.py), and [radar.py](src/cave_portable/radar.py). The first five ZIP digits or first three Canadian postal characters are sent to Zippopotam.us for geocoding; the full Canadian code is not sent there. If entered, the street address and ZIP are sent to US Census, or the street, locality, and province are sent to Natural Resources Canada. A nearby bounding box or selected station code is sent to NOAA Aviation Weather Center. When local monitoring is enabled, geocoded coordinates are sent to the NWS or ECCC alert endpoint. There is no telemetry or API key. Country, postal code, optional street address, selected station, and monitor preference are stored in a user settings file; weather data is not cached on disk. Network requests have a 12-second timeout and response size limits. Imagery is shown with the source's own legend and valid time when present. Stale or failed images are cleared and an error is shown.

Sources: [Zippopotam.us](https://docs.zippopotam.us/docs/getting-started/), [US Census Geocoder](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html/), [Natural Resources Canada Geolocator](https://natural-resources.canada.ca/maps-tools-publications/satellite-elevation-air-photos/geolocation-service), [NOAA Aviation Weather Center API](https://aviationweather.gov/data/api/), [NWS Alerts API](https://www.weather.gov/documentation/services-web-api), [ECCC OGC API](https://eccc-msc.github.io/open-data/msc-geomet/ogc_api_en/), [NWS radar](https://radar.weather.gov/), [NOAA GOES imagery](https://www.star.nesdis.noaa.gov/GOES/), [SPC convective outlooks](https://www.spc.noaa.gov/products/outlook/), [SPC mesoanalysis](https://www.spc.noaa.gov/exper/mesoanalysis/), [NSF Unidata THREDDS](https://www.unidata.ucar.edu/data/nsf-unidatas-thredds-data-server), [USGS National Map](https://www.usgs.gov/programs/national-geospatial-program/national-map), and [Iowa Environmental Mesonet radar services](https://mesonet.agron.iastate.edu/ogc/).

## Develop

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python -m cave_portable
```

Report issues using GitHub issue templates. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [SUPPORT.md](SUPPORT.md).

## License and relationship to AWIPS

The original code in this repository is **GNU GPL version 3 only**; see [LICENSE](LICENSE). Pillow is a separate dependency under the HPND license. No AWIPS source or binaries are copied into this repository. NSF Unidata's AWIPS is [MIT licensed](https://www.unidata.ucar.edu/software/awips/licensing); its full CAVE client already has [Windows and macOS installers](https://unidata.github.io/awips2/install/install-cave/). CAVE Portable is unofficial and is not endorsed by NSF Unidata, NOAA, NWS, NESDIS, or SPC.
