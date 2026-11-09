# CAVE Portable

A lightweight, cross-platform weather viewer inspired by the needs of AWIPS CAVE users. This is an **independent companion**, not a fork or replacement for the full AWIPS CAVE workstation. It runs without an EDEX server and does not issue warnings or generate its own convective forecast.

## What works in 0.1.0

- National radar composite from NOAA/NWS and GOES East/West GeoColor satellite imagery from NOAA/NESDIS.
- Current METAR observations at 24 US airports, direct ICAO station lookup, raw METAR and TAF, and active NWS alerts by state.
- Official SPC Day 1–3 categorical convective outlook maps and current Southern Plains mixed-layer CAPE analysis. The outlook is the forecast guidance; CAPE is only one ingredient in severe weather potential.
- Background network loading, five-minute refresh, bounded downloads, and no local data store or EDEX dependency.

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

Choose **Observations**, **Radar**, **Satellite**, or **Severe outlook & CAPE**. Select a station in the observations table to read the raw METAR. Enter a four-character ICAO code and choose **Load station** for the latest METAR and TAF. Enter a two-letter US state code for active NWS alerts. Select Day 1, 2, or 3 to see SPC's forecast severe weather areas. **Southern Plains MLCAPE** is a regional analysis, not a forecast; read it together with the outlook, radar, and other environmental data.

Weather data can be delayed, missing, or unavailable. This software is for education and situational awareness, not operational warning decisions. For urgent decisions consult [weather.gov](https://www.weather.gov/) and official local instructions.

## Data and network

The application sends read-only HTTPS requests only to the fixed NOAA/NWS/NESDIS/SPC endpoints in [data.py](src/cave_portable/data.py). It does not send personal information, run telemetry, request an API key, or keep a disk cache. Network requests have a 12-second timeout and response size limits. Imagery is shown with the source's own legend and valid time when present. On error, the status bar shows the failure and existing displayed data remains visible.

Sources: [NOAA Aviation Weather Center API](https://aviationweather.gov/data/api/), [NWS Alerts API](https://www.weather.gov/documentation/services-web-api), [NWS radar](https://radar.weather.gov/), [NOAA GOES imagery](https://www.star.nesdis.noaa.gov/GOES/), [SPC convective outlooks](https://www.spc.noaa.gov/products/outlook/), and [SPC mesoanalysis](https://www.spc.noaa.gov/exper/mesoanalysis/).

## Develop

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python -m cave_portable
```

Report issues using GitHub issue templates. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [SUPPORT.md](SUPPORT.md).

## License and relationship to AWIPS

The original code in this repository is **GNU GPL version 3 only**; see [LICENSE](LICENSE). Pillow is a separate dependency under the HPND license. No AWIPS source or binaries are copied into this repository. NSF Unidata's AWIPS is [MIT licensed](https://www.unidata.ucar.edu/software/awips/licensing); its full CAVE client already has [Windows and macOS installers](https://unidata.github.io/awips2/install/install-cave/). CAVE Portable is unofficial and is not endorsed by NSF Unidata, NOAA, NWS, NESDIS, or SPC.
