# Oklahoma Mesonet archive replay

The Oklahoma Mesonet's five-minute MTS files can reveal local temperature, humidity, station pressure, and wind changes that sparse airport reports miss. An MTS file covers one station and one UTC day. The [format definition](https://www.mesonet.org/about/data-descriptions/mdf-mts-files) gives units, the UTC base time, and missing-value codes. This is **observational context**, not a prediction of where a tornado or damaging wind will occur.

## Access and use

The [Oklahoma Mesonet data policy](https://www.mesonet.org/about/data-access-and-pricing) says its data are copyrighted, generally forbids redistribution, and requires an agreement or request for some research uses outside Oklahoma. No Mesonet archive measurements are included in this repository. Obtain files under the applicable terms before using the reader; keep licensed files outside the Git working tree. The [archive data request page](https://www.mesonet.org/past-data/mesonet-resources/request-data) is the official starting point.

The USDA ARS [Little Washita and Fort Cobb micronet](https://ars.mesonet.org/data-files/about/) is a separate, [public-domain](https://ars.mesonet.org/data-files/data-policy/) archive. Its five-minute format differs from MTS; after 2009 it principally contains rainfall and soil variables, so it cannot substitute for the Mesonet's air and wind observations in a Moore 2013 surface replay.

## Run a time-safe replay

From the repository root, with an authorized daily MTS file stored outside it:

```bash
.venv/bin/python scripts/mesonet_replay.py /path/to/20130520NORM.mts --as-of 2013-05-20T17:00Z
```

The script uses only observations at or before `--as-of` and reports the latest observation time, age, a three-hour anchor and deltas where available, count and largest observed gap, temperature, humidity, station pressure, 10 m wind speed, maximum three-second wind speed, and a **derived** dewpoint. It treats Mesonet's `-999` through `-994` quality and missing codes as unavailable. It marks a latest report older than 15 minutes as stale. It refuses a cutoff on another UTC day, since a single MTS file cannot provide a cross-midnight lookback. The archive file itself may have been revised by later quality assurance, so replay is as-of by **observation time**, not a reconstruction of every value as it appeared operationally that day.

To compare the same forecast time with an already issued SPC outlook at an approximate point near Newcastle, use the separate archived-outlook tool:

```bash
.venv/bin/python scripts/outlook_replay.py --as-of 2013-05-20T17:00Z --target 2013-05-20T19:56Z --lat 35.34 --lon -97.56
```

The [NWS Moore event review](https://www.weather.gov/oun/events-20130520) gives the event context. The station is a point sample, not a measurement at the tornado track. The SPC outlook is regional guidance; the two outputs answer different questions. Do not turn a local pressure or dewpoint change into an emergency alert or a tornado probability.

## Validation once archive access is available

Start with central Oklahoma storm days and matched quiet days at the same stations and season. Use several stations around an event, record each station's distance from the report, and choose forecast cutoffs before examining outcomes. Track missingness, data gaps, and quality-assurance changes. Compare the added information from five-minute data against airport-only observations and SPC guidance issued by the same cutoff. Then repeat in other high-activity regions and less-observed regions. A credible predictive feature needs a held-out evaluation of false alarms, lead time, and calibration; the parser and a single storm replay do not establish that skill.
