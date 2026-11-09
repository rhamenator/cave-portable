# Alert coverage and limits

## What this desktop app currently monitors

- **United States:** severe or extreme, actual NWS alerts returned for the chosen geocoded point. The NWS API is a weather-service feed; it is not the full Emergency Alert System (EAS), Wireless Emergency Alerts (WEA), or FEMA IPAWS all-hazards feed.
- **Canada:** active Environment and Climate Change Canada weather warnings intersecting a small box around the chosen geocoded point. This is an ECCC weather feed; it is not the full Alert Ready / National Public Alerting System (NPAS) feed.

The app checks while it is open, once a minute, and uses the system bell and a message box for a newly seen warning. It does not transmit alerts, receive broadcast or cellular messages, use an official EAS or Alert Ready tone, or guarantee delivery. It never uses IP location. Postal centroids and address geocodes are approximate; a boundary-area warning may be missed or shown unexpectedly.

## Other hazards and AMBER alerts

EAS and Alert Ready can distribute public-safety messages beyond weather, including AMBER alerts. This app does not currently ingest those all-hazards feeds and does not claim AMBER coverage. The US FEMA IPAWS All-Hazards Information Feed requires an approved redistribution agreement; its public archive is delayed by 24 hours and is unsuitable for live warnings. A future live integration must verify source access, licensing, expiry/cancellation handling, location polygons, and latency. When implemented, AMBER desktop notifications should have a separate **off by default** preference. This preference cannot disable official broadcast or mobile alerts.

See [FEMA IPAWS guidance](https://www.fema.gov/sites/default/files/documents/fema_ipaws-best-practices-guide.pdf), [FEMA IPAWS archive description](https://gis.fema.gov/arcgis/rest/services/FEMA/IPAWS_Archive/MapServer), [Canada Alert Ready](https://www.canada.ca/en/environment-climate-change/services/weather-general-tools-resources/alert-ready-emergency-system.html), and [CRTC emergency-alert guidance](https://crtc.gc.ca/eng/contact/phone/q20.htm).
