# Station risk rule: limited historical replay

This is a four-event check of a candidate station dashboard reviewed in November 2026. It is **not** a validation of CAVE Portable's SPC briefing or a calibrated prediction model. No private application code or data is included here.

| Event | Nearby airport proxy | Reports in the three hours before onset | Highest dashboard label | Severe labels |
| --- | --- | ---: | --- | ---: |
| [24 August 2023 Williamston–Webberville EF2](https://www.weather.gov/grr/August24_2023_Tornadoes), onset 25 August 01:29 UTC | KLAN | 11 | Moderate | 0 |
| [7 May 2024 Portage EF2](https://www.weather.gov/grr/7_May_2024_SevereWeather), onset 21:55 UTC | KAZO | 8 | Moderate | 0 |
| [26 April 2024 Elkhorn EF4](https://www.weather.gov/oax/april262024), onset 20:30 UTC | KOMA | 6 | Moderate (one report) | 0 |
| [20 May 2013 Newcastle–Moore EF5](https://www.weather.gov/oun/events-20130520), onset 19:56 UTC | KOKC | 6 | Moderate | 0 |

The replay used temperature, relative humidity, and altimeter readings from [Iowa Environmental Mesonet's archived ASOS reports](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help=). Each report was evaluated in time order with the dashboard's live input shape: the current observation and at most one three-hour-old observation. Its pressure-drop condition requires more than twelve history entries, so that condition cannot be met by the live input shape. The severe label was therefore unreachable in these two replays, even when KLAN's reported altimeter fell roughly 0.05–0.08 inHg per hour late in the pre-event window.

The stations were proxies for the event areas, not sensors at the tornado tracks. Airport observations are sparse and can miss rapid local changes. Four tornado events without non-event controls cannot establish sensitivity, false-alarm rate, lead time, or forecast skill. A station trend alone also cannot locate or grade future severe weather. Before adding a local risk score, use a larger archive with non-event controls, time-ordered inputs, explicit missing-data rules, and calibrated comparisons with official [SPC outlooks](https://www.spc.noaa.gov/products/outlook/) and warnings. The current app shows source-attributed official guidance instead of claiming its own severe forecast.

The [issue-time outlook replay and larger validation design](INTELLIGENCE_RESEARCH.md) make the official comparison reproducible and add higher-activity regions and quiet-day controls.
