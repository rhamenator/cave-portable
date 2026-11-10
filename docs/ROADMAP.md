# Scope and roadmap

See the [native-code assessment](PORTING_ASSESSMENT.md) for measured performance and criteria for a possible C++ or Rust migration.

## Current release

0.4.1 adds a timestamp-based airport pressure trend and GFS storm-relative helicity and 500 hPa wind-speed layers. The research-only outlook replay selects SPC polygons that were actually issued by a requested time. The app still lacks decoded Level II data, EDEX integration, and soundings. The older storm-relative velocity and hydrometeor products are upstream imagery.

The source branch also contains [NOAA observational replay](NOAA_REPLAY.md) tools for historical case studies. Locally generated severe-weather prediction remains a later research question.

## Next milestones

1. Extend decoding to Level II and add radar volume analysis and loop playback. Preserve site, tilt, scan time, units, legend, and freshness checks. Do not use stale archived products as live imagery. See [CAVE capability research](CAVE_RESEARCH.md).
2. Interactive map with station, radar, satellite, and SPC polygon layers; pan/zoom and valid-time controls.
3. A time-aligned event viewer combining archived NOAA surface observations, NEXRAD volumes, official warning issue times, and storm reports. Show data gaps and observation ages.
4. Soundings and measured time series for situational awareness.
5. Optional read-only EDEX data integration, keeping the lightweight standalone mode.
6. Reproducible packaged installers and measured startup, memory, download, and idle CPU budgets on Ubuntu, Fedora, Windows, and macOS.
7. Consider Europe only after verifying postal geocoding, current observation and radar sources, and authoritative warning feeds for each supported country.
8. Add optional AMBER and other public-safety categories only after acquiring and validating live all-hazards sources. The current NWS and ECCC weather feeds do not represent all US EAS/WEA or Canadian Alert Ready messages. Keep AMBER desktop notifications off by default when implemented. A mobile app is a later possibility and is outside this desktop release.

Further model research can add explicit GFS/NAM/HRRR runs, shear, CIN, lapse rate, moisture, uncertainty, and source-attributed multi-field forecast images. Any automated severe-weather guidance must be validated against archived events and quiet days before presentation as a prediction.
