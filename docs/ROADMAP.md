# Scope and roadmap

## Current release

0.1.0 is a small weather viewer with observed weather, national and single-site radar imagery, satellite imagery, Southern Plains MLCAPE, a bounded GFS CAPE forecast view, and official SPC outlooks. It has no AWIPS EDEX protocol integration, interactive geospatial layers, soundings, GFE editing, or warning issuance. Correlation coefficient and hail products are not yet available in the verified live imagery feed, so they are not shown as if current.

## Next milestones

1. Current correlation coefficient, differential reflectivity, and hail estimates from a verified live Level III source, with radar site, tilt, scan time, legend, and freshness checks. Do not use stale archived products as live imagery.
2. Interactive map with station, radar, satellite, and SPC polygon layers; pan/zoom and valid-time controls.
3. Explicit model run and lead-time selection, additional GFS/NAM/HRRR fields (shear, CIN, lapse rate, moisture), and uncertainty. Avoid a severity score based on CAPE alone.
4. Soundings and time series; probabilistic severe guidance with an explanation of SPC risk and hazard probabilities.
5. Optional read-only EDEX data integration, keeping the lightweight standalone mode.
6. Reproducible packaged installers and measured startup, memory, download, and idle CPU budgets on Ubuntu, Fedora, Windows, and macOS.

Forecast interpretation should rely on multiple ingredients and official products. Any automated severe-weather guidance must be validated against archived events before presentation as a prediction.
