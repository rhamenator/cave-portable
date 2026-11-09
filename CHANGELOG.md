# Changelog

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
