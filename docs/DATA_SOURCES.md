# Weather data and forecast image plan

## Where the maps come from

| Product | Data path | What the current app can show |
| --- | --- | --- |
| AWIPS CAVE | EDEX decodes and serves radar, satellite, model, and observation data to the CAVE client. | CAVE Portable does not connect to EDEX or copy AWIPS code. |
| RadarScope (paid) | Its documented providers include the NOAA public radar feed and other providers. Its price pays for its interface, processing, distribution, and additional features; a public upstream feed does not imply identical products. | CAVE Portable uses public NOAA/NWS and Iowa Mesonet feeds directly. |
| CAVE Portable current radar | NWS national composite, Iowa Mesonet site reflectivity and storm-relative velocity, and NWS Level III hydrometeor classification. The NWS station catalog supplies the site list. | A scan is withheld when its source time is more than 15 minutes old. The hydrometeor layer includes a hail category, **not hail size**. |
| CAVE Portable forecast | SPC categorical convective outlooks, SPC regional mixed-layer CAPE analysis, GFS surface-based CAPE via Unidata, and NCEP HRRR simulated reflectivity via Iowa Mesonet. | The HRRR view composes model imagery over a USGS basemap and adds run and valid times to the image. It is a forecast of reflectivity, **not current radar or a severe-weather probability**. |

Sources: [AWIPS system manual](https://unidata.github.io/awips2/pdf/raytheon/System_Manual_13.4.1.pdf), [Unidata AWIPS architecture](https://unidata.github.io/python-awips/about.html), [RadarScope data providers](https://radarscope.zendesk.com/hc/en-us/articles/4411492912146-Data-Provider-Settings), [NCEI NEXRAD products](https://www.ncei.noaa.gov/products/radar/next-generation-weather-radar), [NWS radar FAQ](https://www.weather.gov/radarfaq/), [Iowa Mesonet OGC services](https://mesonet.agron.iastate.edu/ogc/), [Iowa Mesonet HRRR imagery](https://mesonet.agron.iastate.edu/GIS/model.phtml), [SPC outlooks](https://www.spc.noaa.gov/products/outlook/).

## Building more useful forecast images

Render from timestamped data fields rather than reusing an unlabelled web picture. Each image needs the model/source, initialization and valid times, field units, geographic area, and a legend or an explicit warning when a source does not supply one. A future multi-panel severe-weather view could align CAPE, shear, CIN, moisture, and simulated reflectivity for a selected HRRR or NAM run. It should place the official SPC outlook alongside those fields and show uncertainty. CAPE by itself cannot determine tornado or hail likelihood.

Correlation coefficient, differential reflectivity, and quantitative hail estimates require a verified live Level III or Level II feed, site and tilt handling, scan times, and an appropriate legend. The current Iowa Mesonet site service exposed reflectivity and storm-relative velocity in the tested catalog; the NWS hydrometeor layer was separately verified. No current correlation or hail-size image is claimed. Validate any derived severe-weather probability against archived events before showing it as predictive guidance.
