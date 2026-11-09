# Scope and roadmap

## Current release

0.2.0 adds the NWS WSR-88D station catalog, 1×/2×/4× radar site zoom, NWS hydrometeor classification, NCEP HRRR simulated reflectivity images with run/valid times, and watch status in the optional Linux Wayland tray indicator. It retains national and single-site radar, satellite, Southern Plains MLCAPE, GFS CAPE, official SPC outlooks, required US ZIP or full Canadian postal entry for local weather, and opt-in NWS/ECCC weather alert monitoring. It has no AWIPS EDEX protocol integration, interactive geospatial layers, soundings, GFE editing, EAS/WEA reception, or warning issuance. Correlation coefficient and quantitative hail size products are not yet available in the verified live imagery feed. The hydrometeor hail category is qualitative. Canadian location uses an approximate FSA centroid.

## Next milestones

1. Current correlation coefficient, differential reflectivity, and hail estimates from a verified live Level III or Level II source, with radar site, tilt, scan time, legend, and freshness checks. Do not use stale archived products as live imagery.
2. Interactive map with station, radar, satellite, and SPC polygon layers; pan/zoom and valid-time controls.
3. Explicit model run selection, additional GFS/NAM/HRRR fields (shear, CIN, lapse rate, moisture), and uncertainty. Compose source-attributed multi-field forecast images. Avoid a severity score based on CAPE alone.
4. Soundings and time series; probabilistic severe guidance with an explanation of SPC risk and hazard probabilities.
5. Optional read-only EDEX data integration, keeping the lightweight standalone mode.
6. Reproducible packaged installers and measured startup, memory, download, and idle CPU budgets on Ubuntu, Fedora, Windows, and macOS.
7. Consider Europe only after verifying postal geocoding, current observation and radar sources, and authoritative warning feeds for each supported country.
8. Add optional AMBER and other public-safety categories only after acquiring and validating live all-hazards sources. The current NWS and ECCC weather feeds do not represent all US EAS/WEA or Canadian Alert Ready messages. Keep AMBER desktop notifications off by default when implemented. A mobile app is a later possibility and is outside this desktop release.

Forecast interpretation should rely on multiple ingredients and official products. Any automated severe-weather guidance must be validated against archived events before presentation as a prediction.
