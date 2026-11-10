# Changelog

## 0.4.0 — 2026-11-09

- Decode NOAA Level III base Doppler velocity and select elevation tilts 0–3 for decoded reflectivity and dual-pol fields. Correct digital radial value scaling at the first data code.
- Map the current NOAA MRMS 30-minute MESH hail maximum with valid time and estimate-only legend; reject stale products.
- Add GFS surface lifted index to the explicit-run forecast ingredient selector.
- Replay the archived colleague station risk logic against airport observations before the 24 August 2023 Lansing-area and 7 May 2024 Portage tornadoes; document the limited result in the weather validation note.

## 0.3.2 — 2026-11-09

- Use the bundled Adwaita GTK theme on Linux so text stays readable when another desktop theme needs an SVG loader absent from the bundle. Verified against the published 0.3.1 Linux archive in a clean desktop smoke test.

## 0.3.1 — 2026-11-09

- Correct Linux release packaging after the initial 0.3.0 tag failed the GTK/ecCodes CFFI check. All four platform bundles built in the follow-up workflow.

## 0.3.0 — 2026-11-09

- Decode and render live NOAA Level III digital reflectivity, correlation coefficient, ZDR, and KDP for selected radar sites, with scan timeline, geographic zoom/pan, value inspection, scan time, tilt, and palette. Mask dual-pol values below 10 dBZ reflectivity. Low CC alone cannot confirm debris.
- Overlay current SPC Day 1 outlook areas and NWS alerts at the selected US point on decoded radar, with clear status when an overlay is unavailable.
- Add on-demand NOAA MRMS MESH hail-size estimate at and near the selected contiguous-US point, labelled as an algorithmic estimate with valid time.
- Add explicit GFS run, forecast hour, CAPE, CIN, 2 m humidity, and 2 m dewpoint selections. Keep official SPC guidance separate from forecast ingredients.
- Add a local briefing with current observation, alert count, SPC point outlook, readable NWS forecast, and next three hourly periods.

## 0.2.1 — 2026-11-09

- Add KLAN to the observation list and use the nearest radar site when a station is selected. Selecting KLAN opens a Lansing-centered KGRR site image.
- Add +/− buttons and keys for radar, regional GFS CAPE, and HRRR maps, with 1× through 16× geographic extents.
- Query official SPC Day 1 vector outlooks for the selected US point and show categorical and tornado/hail/wind values with issue and valid times. Add a readable NWS point forecast. These are source values, not a new severe-weather prediction.
- Inspect the installed CAVE radar plug-in and public weather repositories; document a decoded Level II/III radar and numerical-model roadmap. No AWIPS or private code is included.

## 0.2.0 — 2026-11-09

- Load the live NWS WSR-88D station catalog (159 sites in the verified response), with a small offline fallback, and add 1×/2×/4× radar site zoom.
- Add NWS hydrometeor classification with a source scan time and legend. The hail class is qualitative and is not a hail-size estimate.
- Compose NCEP HRRR simulated reflectivity forecast images over a USGS basemap. Label each image with model initialization, valid time, and forecast status.
- Fix the mini window's local weather state after a completed or failed request.
- Monitor NWS/ECCC weather watches as well as warnings. On Linux Wayland with AppIndicator support, show a yellow watch or red warning tray badge and offer Minimize to tray; only a new warning sounds the system bell.
- Compare public upstream data, AWIPS EDEX, and a paid radar app in the source plan. Do not claim correlation coefficient or quantitative hail products until a live feed is verified.

## 0.1.4 — 2026-11-09

- Use a native GTK 3 window on Linux Wayland after user testing showed Tk windows remained minimized even when mapped and centered.
- Keep the five weather views, local postal-area weather, and opt-in warning monitor in the Wayland interface.
- Tested the native window on GNOME Wayland and the observation and radar layouts in a desktop smoke test.

## 0.1.3 — 2026-11-09

- This tag was not released after user testing found the Tk window was still invisible on GNOME Wayland.
- Point the Linux menu entry directly at the installed weather icon and show the icon in the app header.
- Recover the window when GNOME Wayland immediately minimizes it; the fallback has a draggable header and Close button.

## 0.1.2 — 2026-11-09

- Added a weather radar and storm icon to the window, desktop launcher, Windows executable, and macOS app.
- Matched the Linux desktop launcher to the app window and added initial window presentation handling on GNOME Wayland (improved in 0.1.3).
- Added a one-step per-user Linux installer to the release archive.

## 0.1.1 — 2026-11-09

- Kept map legends, product controls, and source times visible when the desktop window is shorter.
- Reflowed location controls and improved the mini weather window layout.
- Cleared old mini weather readings when a refresh cannot find a recent observation.

## 0.1.0 — 2026-11-09

- Initial lightweight desktop client for national and single-site radar, satellite, METAR, TAF, NWS alerts, SPC Day 1–3 outlooks, current MLCAPE, and GFS forecast CAPE.
- Added required US ZIP or full Canadian postal entry for local weather, optional NWS/ECCC warning notification at a postal-area centroid, nearby-airport mini temperature/conditions window, and per-user login startup.
- Source install and automated cross-platform test/build workflows.
