# CAVE capability and radar-data research

## Installed CAVE evidence

The Rocky 8 VM has `awips2-cave-23.4.3-1.x86_64`. I inspected its installed radar plug-in archive, `com.raytheon.viz.radar.jar` (SHA-256 `0bb2a421b69b7b8570b48f38e4995ae383304a053369832889172ea0286a0616`), without copying it into this repository. REA archive inventory evidence: `ev_f7e8492405b5f363f14a1238bcce5bdc477fd7c26f987a1ac4392e98a7659f56`. Static inspection shows:

- `RadarResourceData` has a point/site ID, latest-data flag, available-time lookup, and update handling.
- `RadarProductFactory` selects a radar display resource and interrogator from product code and type.
- `RadarRadialResource` builds a radial mesh, exposes tilt/elevation and center, and supports interrogation at a map coordinate.
- `RadarImageResource` paints decoded radar images, computes range circles, and reprojects imagery. Separate raster, storm-relative-motion, graphic, and mosaic resource classes are present.
- The installed plug-in registers radar image, graphic, and mosaic resources against `RadarRecord`. Other installed plug-ins cover satellite, grid, point data, soundings, lightning, warnings, and GFE.

These are **static artifact observations**, not a claim that every function was exercised in the VM. CAVE also uses an EDEX data ingest and query service. [Unidata's source description](https://github.com/Unidata/awips2) says EDEX decodes raw feeds to HDF5 and PostgreSQL and serves CAVE over HTTP. [The CAVE Product Browser manual](https://unidata.github.io/awips2/cave/d2d-perspective/) describes inventory browsing for grid, lightning, maps, radar, and satellite data. That data model and map interaction explain much of the difference from our current image-request tabs.

## Other weather repositories examined

| Repository | Useful idea | Constraint |
| --- | --- | --- |
| [Supercell Wx](https://github.com/dpaulat/supercell-wx) | C++20 radar decoder in a separate `wxdata` library; Level II/III, products, timeline, responsive map, and background work. Its [architecture notes](https://github.com/dpaulat/supercell-wx/blob/develop/AGENTS.md) separate the decoder from its Qt UI. | MIT license permits integration with attribution after dependency and package review. Its full Qt/OpenGL application has GPU and installer requirements that need measurement on limited machines. |
| [OpenStorm](https://github.com/JordanSchlick/OpenStorm) | Native radar volume decoding, correlation coefficient, 2D slices, and 3D exploration. | Unreal Engine 5 is a poor fit for a small desktop footprint. Its repository carries a GPLv2 license file; do not reuse code without a compatibility review. |
| [LibreWXR](https://github.com/JoshuaKimsey/LibreWXR) | Regional source adapters, tiles, color schemes, and experimental radar/model nowcasting. | It is a Python server under AGPL-3.0-or-later; its nowcast is described as experimental. Architectural inspiration only for now. |

The private reference weather application was reviewed locally for model/run/field selection; no private code or assets were copied into this public repository.

## Data path to a CAVE-class lightweight viewer

1. Add a bounded, independent decoder for [real-time NEXRAD Level II and Level III](https://registry.opendata.aws/noaa-nexrad/) data. The raw field model must retain site, product, tilt, scan time, units, missing-data flags, and provenance. The NOAA/Open Data registry lists the public real-time feeds and NOAA's Level II/III format documents.
2. Render decoded polar/raster fields on a reusable pan/zoom map, with honest legends and point inspection. Distinguish reflectivity, velocity, correlation coefficient, hydrometeor class, and quantitative hail estimates. Show unavailable products as unavailable, never substitute a different product silently.
3. Retain the official [SPC vector outlook service](https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/MapServer) for categorical and tornado/hail/wind probability guidance. Its point query provides issue and valid times; the displayed percentages come from SPC, not from our algorithm.
4. Build model-field views from numerical grids (CAPE, shear, CIN, moisture, lapse rates) with run/lead selection and unit legends. Validate any derived severe-weather prediction against archived events before presenting it as a risk forecast.
5. Benchmark Python rendering/decoding, memory, startup, idle CPU, and package size before deciding whether a C++ decoder or a full C++/Qt UI is needed. Supercell Wx's MIT-licensed `wxdata` is a candidate, but no integration decision has been made.

The 0.2.x image feeds remain a fallback for continuity. Current work adds local station context and structured SPC point values, while the decoded radar pipeline is a separate milestone.
