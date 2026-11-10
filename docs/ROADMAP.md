# Scope and roadmap

See the [native-code assessment](PORTING_ASSESSMENT.md) for measured performance and criteria for a possible C++ or Rust migration.

## Current release

0.4.0 adds decoded Level III base Doppler velocity and selectable tilts 0–3 to reflectivity and dual-pol products, a mapped NOAA MRMS 30-minute MESH maximum, and GFS surface lifted index. The app still lacks decoded Level II data, EDEX integration, soundings, and independently validated severe-weather prediction. The older storm-relative velocity and hydrometeor products are upstream imagery.

## Next milestones

1. Extend decoding to Level II and add radar volume analysis and loop playback. Preserve site, tilt, scan time, units, legend, and freshness checks. Do not use stale archived products as live imagery. See [CAVE capability research](CAVE_RESEARCH.md).
2. Interactive map with station, radar, satellite, and SPC polygon layers; pan/zoom and valid-time controls.
3. Explicit model run selection, additional GFS/NAM/HRRR fields (shear, CIN, lapse rate, moisture), and uncertainty. Compose source-attributed multi-field forecast images. Avoid a severity score based on CAPE alone.
4. Soundings and time series; probabilistic severe guidance with an explanation of SPC risk and hazard probabilities.
5. Optional read-only EDEX data integration, keeping the lightweight standalone mode.
6. Reproducible packaged installers and measured startup, memory, download, and idle CPU budgets on Ubuntu, Fedora, Windows, and macOS.
7. Consider Europe only after verifying postal geocoding, current observation and radar sources, and authoritative warning feeds for each supported country.
8. Add optional AMBER and other public-safety categories only after acquiring and validating live all-hazards sources. The current NWS and ECCC weather feeds do not represent all US EAS/WEA or Canadian Alert Ready messages. Keep AMBER desktop notifications off by default when implemented. A mobile app is a later possibility and is outside this desktop release.

Forecast interpretation should rely on multiple ingredients and official products. Any automated severe-weather guidance must be validated against archived events before presentation as a prediction.
