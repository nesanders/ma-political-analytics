"""Fetch MA state legislative district boundaries.

Primary source: Census TIGER/Line, not MassGIS. Verified live (2026-08):
MassGIS's own branded open-data hosts (gis.data.mass.gov,
maps-massgis.opendata.arcgis.com, geo-massdot.opendata.arcgis.com) render
item pages fine but redirect every actual download through hub.arcgis.com
regardless of which domain fronts them (an ArcGIS Hub product behavior).
Once hub.arcgis.com and MassGIS's self-hosted ArcGIS Server
(arcgisserver.digital.mass.gov) were both allowlisted, a further problem
turned up: neither one's live catalog carries the 2001 vintage any more —
it's been retired, not just hard to reach — only the 2012 and 2022
vintages are still live there (which TIGER already covers below anyway).

TIGER/Line state legislative district shapefiles (SLDU = upper chamber =
Senate, SLDL = lower chamber = House) download directly with no auth and no
redirect chain: https://www2.census.gov/geo/tiger/TIGER{year}/SLD{U,L}/
tl_{year}_25_sld{u,l}.zip (25 = MA's FIPS code). Confirmed live for the 2012
vintage (used 2012-2020) and the 2022 vintage (used 2022-present).

The 2001 vintage (used 2002-2010) is NOT covered by TIGER: TIGER's
per-state SLDU/SLDL zip pattern only starts around TIGER2012 (TIGER2010/2011
directories exist but were empty for every state when checked). It comes
from MIT Libraries' GeoData Repository instead, which archives it after
MassGIS retired the live copies. The catalog pages
(geodata.libraries.mit.edu/record/...) link out to actual shapefile zips on
a *separate* host, cdn.libraries.mit.edu — both needed to be allowlisted.
The House record initially found via search
(gisogm:edu.harvard:b07d39bbd8fe) turned out to be the *wrong* vintage —
its own page says "Chapter 273 of the Acts of 1993", the redistricting
*before* 2001's, used through the 2000 elections — a trap worth flagging
since the title alone ("Massachusetts House Legislative Districts") reads
as generic. The right one, found via geodata.libraries.mit.edu/results, is
gismit:US_MA_F7HOUSE_2002 (MIT-hosted directly, not a Harvard pointer).
Confirmed correct pair, both used in the Fall 2002 elections:
- Senate: https://cdn.libraries.mit.edu/geo/public/MASENATEDIST02.zip
- House: https://cdn.libraries.mit.edu/geo/public/US_MA_F7HOUSE_2002.zip

Both are un-dissolved: multiple polygon rows per district (261 rows / 40
Senate districts, 352 / 160 House districts) rather than one row per
district like TIGER — dissolved here by district number before writing out.
Also reprojected from their native Massachusetts State Plane CRS (feet for
Senate/EPSG:2249, meters for House/EPSG:26986 — inconsistent between the
two files) to EPSG:4269 to match the TIGER-sourced vintages.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from ma_politics.util.geo import TARGET_CRS, download_shapefile
from ma_politics.util.http import make_session

logger = logging.getLogger(__name__)

MA_FIPS = "25"

# vintage -> (label, TIGER release year to pull from)
# The TIGER release year need not equal the vintage's first election year —
# it just needs to be any TIGER year that falls within the vintage's span,
# since Census re-publishes the same current boundaries every year between
# redistricting cycles.
TIGER_VINTAGES = {
    "2012-2020": 2013,
    "2022-present": 2023,
}

CHAMBER_TIGER = {"senate": "sldu", "house": "sldl"}

# MIT GeoData Repository: (zip URL, path to .shp inside the zip, column to
# dissolve on to get one row per district — these files ship un-dissolved).
MIT_VINTAGE_2001 = {
    "senate": (
        "https://cdn.libraries.mit.edu/geo/public/MASENATEDIST02.zip",
        "MASENATEDIST02/MASENATEDIST02.shp",
        "SENDISTNUM",
    ),
    "house": (
        "https://cdn.libraries.mit.edu/geo/public/US_MA_F7HOUSE_2002.zip",
        "US_MA_F7HOUSE_2002/US_MA_F7HOUSE_2002.shp",
        "REPDISTNUM",
    ),
}

VINTAGES = {**TIGER_VINTAGES, "2001-2010": None}


def _tiger_url(year: int, chamber: str) -> str:
    layer = CHAMBER_TIGER[chamber]
    return f"https://www2.census.gov/geo/tiger/TIGER{year}/{layer.upper()}/tl_{year}_25_{layer}.zip"


def fetch_vintage(vintage: str, chamber: str, out_dir: Path, session=None) -> Path:
    session = session or make_session(min_interval_s=0.5)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{chamber}_{vintage}.geoparquet"
    extract_dir = out_dir / f"_tmp_{chamber}_{vintage}"

    if vintage in TIGER_VINTAGES:
        year = TIGER_VINTAGES[vintage]
        url = _tiger_url(year, chamber)
        gdf = download_shapefile(url, None, extract_dir, session)
        source = f"TIGER{year}"
    elif vintage == "2001-2010":
        url, shp_path, dissolve_col = MIT_VINTAGE_2001[chamber]
        raw = download_shapefile(url, shp_path, extract_dir, session)
        gdf = raw.dissolve(by=dissolve_col).reset_index()
        source = "MIT GeoData Repository (2002-vintage shapefile)"
    else:
        raise ValueError(f"Unknown vintage {vintage!r}")

    gdf = gdf.to_crs(TARGET_CRS)
    gdf["chamber"] = chamber
    gdf["vintage"] = vintage
    gdf["source"] = source
    gdf.to_parquet(out_path)
    logger.info("Wrote %d districts to %s (crs=%s)", len(gdf), out_path, gdf.crs)
    return out_path


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option(
    "--vintage",
    type=click.Choice([*VINTAGES, "all"]),
    default="all",
)
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/boundaries"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, vintage: str, out_dir: Path, verbose: bool):
    """Fetch MA state legislative district boundaries (TIGER for 2012/2022
    vintages, MIT GeoData Repository for the 2001 vintage)."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    vintages = list(VINTAGES) if vintage == "all" else [vintage]
    session = make_session(min_interval_s=0.5)
    for c in chambers:
        for v in vintages:
            fetch_vintage(v, c, out_dir, session=session)


if __name__ == "__main__":
    main()
