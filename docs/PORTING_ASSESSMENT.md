# Native-code assessment

This is an architecture assessment, not a decision to replace the working desktop client. It uses the 0.3.2 Linux build and a review of privately archived colleague projects. No private source or assets were copied into this repository.

## Measured baseline

One local Linux run on 9 November 2026, with KGRR Level III digital reflectivity and a 960 × 500 viewport, gave these approximate times:

| Operation | Time |
| --- | ---: |
| Fetch and decode current radar object | 0.50 s |
| Fetch and decode USGS basemap | 0.79 s |
| Render decoded radar over cached basemap, three repetitions | 0.38 s each |

The published Linux executable occupies about 109 MiB on disk. Its GTK child process used about 138 MiB resident memory ten seconds after launch; a source launch on the same host used about 144 MiB. These are snapshots, not peak or cross-platform measurements. Network latency, tile service behavior, and the GTK/Pillow stack matter at least as much as the radar loop in this sample. The on-demand MRMS path expands a CONUS GRIB grid in a short-lived child process and merits separate peak-memory measurement.

A second source-run measurement on the same Linux host on 10 November 2026 used live KGRR tilt-0 data and a 960 × 500 viewport at 2× zoom. Fetch plus decode took 0.44 s for reflectivity, 0.39 s for velocity, and 0.39 s for correlation coefficient. Rendering took 1.05 s on the first map (including a cold basemap fetch), then 0.37 s and 0.36 s on the reused map. The benchmark process reached about 53 MiB maximum resident memory; this excludes a running GUI and is not a peak for the full application. The GTK window separately loaded the decoded KGRR map in a desktop smoke test. These measurements still do not justify a whole-app language change; future Level II volumes and multiple concurrent layers need their own measurements.

## Findings from the private reference projects

- A C++20/Qt Widgets model browser demonstrates a useful architecture: configuration-driven model catalogs, explicit run and forecast selection, asynchronous network requests, bounded downloads, and an image cache. Its radar products are upstream WMS images; it is not a decoded radar engine. Several configured layers are marked broken. On this Linux host, its CMake configuration succeeded but the executable build stopped at an unconditional Windows `winsock2.h` include. It is not a ready cross-platform replacement.
- A C++ personal-station dashboard includes sensor trend analysis and an optional language-model forecast. Its severe-risk label is a pressure/dewpoint heuristic, and the source does not establish calibration against archived severe events. It cannot be treated as an SPC-like probability or a shelter trigger.
- A smaller C++ weather console app uses an AccuWeather API key and IP-based geolocation. Those choices conflict with this project's free public-feed and mandatory postal-location requirements.
- A Python snowfall project explores model training, but its heavy machine-learning dependencies and daily retraining do not fit a lightweight severe-weather desktop client. Its documentation refers to a launch file absent from the archived tree, so its claims require execution and validation before reuse.
- The refreshed private weather-model catalog also lists IEM one-hour precipitation, storm-total precipitation, and echo-top WMS views. They are image products with unverified current layer IDs and would not advance decoded radar inspection by themselves. A regional product catalog with explicit availability checks is a useful interface idea.
- The private personal-station dashboard describes sensor-health checks and optional local telemetry ingestion. Those may inform a later station-data adapter. Its readme's tornado-probability and AI forecast claims are not supported by an archived, geographically separated verification set and must not be displayed as calibrated severe-weather probabilities.

The private code has mixed or absent licensing and uncertain provenance. Reimplement ideas from specifications and public data; review rights before copying any source, assets, or model weights into this public GPL-3.0-only repository.

## Recommendation

Keep the current client while improving weather capability. The measured local radar render is under half a second, so a whole-app rewrite is not yet justified by speed. Prioritize decoded velocity and additional tilts, clearer product legends, loop playback, MRMS hail swaths, and model ingredients such as shear and lapse rate. Forecast probabilities need archived-event validation and calibration before presentation as new severe-weather guidance.

If profiling later finds a repeatable CPU or memory bottleneck, move that decoder or raster operation to a small Rust library with a stable interface and keep the current UI. For a complete desktop replacement, prototype a C++20/Qt 6 Widgets vertical slice against the same live feeds and compare startup, idle and peak memory, interaction latency, archive size, accessibility, tray behavior, and install effort. Qt supports Linux, Windows, and macOS and offers GPL-3 licensing; native code alone does not guarantee a smaller app. Rust GUI options should be tested against those same requirements before choosing one.

Do not start a full rewrite until the prototype matches the current radar, alerts, postal-location workflow, and Linux Wayland visibility, and shows a meaningful resource or usability improvement on low-end hardware.

Sources: [Qt supported platforms](https://doc.qt.io/qt-6/supported-platforms.html), [Qt GPL licensing](https://doc.qt.io/qt-6/gpl.html), [ecCodes C API](https://sites.ecmwf.int/docs/eccodes/group__get__set.html), [egui project](https://github.com/emilk/egui).
