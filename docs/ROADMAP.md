# Scope and roadmap

## Current release

0.1.0 is a small weather viewer with observed weather, imagery, Southern Plains MLCAPE, and official SPC outlooks. It has no AWIPS EDEX protocol integration, interactive geospatial layers, model grids, soundings, GFE editing, or warning issuance. The imagery views are fixed national, CONUS, and Southern Plains products; local radar zoom and animation are future work.

## Next milestones

1. Interactive map with station, radar, satellite, and SPC polygon layers; pan/zoom and valid-time controls.
2. Model forecast CAPE, shear, CIN, lapse rate, and moisture fields from an authoritative forecast data source, with run/lead time and uncertainty clearly shown. Avoid a severity score based on CAPE alone.
3. Soundings and time series; probabilistic severe guidance with an explanation of SPC risk and hazard probabilities.
4. Optional read-only EDEX data integration, keeping the lightweight standalone mode.
5. Reproducible packaged installers and measured startup, memory, download, and idle CPU budgets on Ubuntu, Fedora, Windows, and macOS.

Forecast interpretation should rely on multiple ingredients and official products. Any automated severe-weather guidance must be validated against archived events before presentation as a prediction.
