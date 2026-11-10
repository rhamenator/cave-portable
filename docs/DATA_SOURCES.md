# Weather data and forecast image plan

## Where the maps come from

| Product | Data path | What the current app can show |
| --- | --- | --- |
| AWIPS CAVE | EDEX decodes and serves radar, satellite, model, and observation data to the CAVE client. | CAVE Portable does not connect to EDEX or copy AWIPS code. |
| RadarScope (paid) | Its documented providers include the NOAA public radar feed and other providers. Its price pays for its interface, processing, distribution, and additional features; a public upstream feed does not imply identical products. | CAVE Portable uses public NOAA/NWS and Iowa Mesonet feeds directly. |
| CAVE Portable current radar | NWS national composite, Iowa Mesonet site reflectivity and storm-relative velocity, and NWS Level III hydrometeor classification. The NWS station catalog supplies the site list. | A scan is withheld when its source time is more than 15 minutes old. The hydrometeor layer includes a hail category, **not hail size**. |
| CAVE Portable decoded radar | Public NOAA Level III digital radial objects for site reflectivity, CC, ZDR, and KDP. | The app renders its own map, scan timeline, tilt, palette, and selected point value. CC alone does not prove debris. |
| CAVE Portable hail estimate | NOAA MRMS MESH GRIB2 from the public MRMS S3 bucket. | On-demand point and nearby sampled maximum, with valid time. It is an algorithmic estimate, not a measured stone size or forecast. |
| CAVE Portable forecast | SPC categorical convective outlooks, SPC regional mixed-layer CAPE analysis, GFS surface-based CAPE via Unidata, and NCEP HRRR simulated reflectivity via Iowa Mesonet. | The HRRR view composes model imagery over a USGS basemap and adds run and valid times to the image. It is a forecast of reflectivity, **not current radar or a severe-weather probability**. |
| CAVE Portable point guidance | Official SPC Day 1 GIS vector layers and NWS point forecast API for a selected US location. | Reads categorical and tornado/hail/wind outlook values, issue/valid times, and a readable local forecast. It does not calculate its own severe-weather risk. |
| CAVE Portable forecast ingredients | One explicit GFS run via NSF Unidata THREDDS WMS. | CAPE, CIN, 2 m relative humidity, and 2 m dewpoint by forecast hour, with run and valid times. |

Sources: [AWIPS system manual](https://unidata.github.io/awips2/pdf/raytheon/System_Manual_13.4.1.pdf), [Unidata AWIPS architecture](https://unidata.github.io/python-awips/about.html), [RadarScope data providers](https://radarscope.zendesk.com/hc/en-us/articles/4411492912146-Data-Provider-Settings), [NCEI NEXRAD products](https://www.ncei.noaa.gov/products/radar/next-generation-weather-radar), [NWS radar FAQ](https://www.weather.gov/radarfaq/), [Iowa Mesonet OGC services](https://mesonet.agron.iastate.edu/ogc/), [Iowa Mesonet HRRR imagery](https://mesonet.agron.iastate.edu/GIS/model.phtml), [SPC outlooks](https://www.spc.noaa.gov/products/outlook/).

## Building more useful forecast images

Render from timestamped data fields rather than reusing an unlabelled web picture. Each image needs the model/source, initialization and valid times, field units, geographic area, and a legend or an explicit warning when a source does not supply one. A future multi-panel severe-weather view could align CAPE, shear, CIN, moisture, and simulated reflectivity for a selected HRRR or NAM run. It should place the official SPC outlook alongside those fields and show uncertainty. CAPE by itself cannot determine tornado or hail likelihood.

Current decoded CC and ZDR come from NOAA Level III digital radial objects in the public NEXRAD S3 bucket. The scan and tilt are shown, and dual-pol values are masked where reflectivity is below 10 dBZ. Low CC is not a debris confirmation. NOAA MRMS MESH provides an on-demand point and nearby algorithmic hail-size estimate, not measured hail or a hail forecast. The GFS ingredients view uses a specific run, field, and valid time from Unidata THREDDS. Further predictive capability needs additional fields, event validation, and uncertainty reporting; CAPE alone cannot determine severe-weather likelihood.
