"""Fetch MA state legislative district boundaries.

Primary source: Census TIGER/Line, not MassGIS. Verified live (2026-08):
MassGIS's own branded open-data hosts (gis.data.mass.gov,
maps-massgis.opendata.arcgis.com, geo-massdot.opendata.arcgis.com) render
item pages fine but redirect every actual download through hub.arcgis.com
regardless of which domain fronts them (an ArcGIS Hub product behavior) —
and MassGIS's self-hosted ArcGIS Server (arcgisserver.digital.mass.gov) was
also unreachable from this environment. See docs/PLAN.md's network appendix
for what's needed if you want to add MassGIS as a source later (it's the
more authoritative one for fine boundary detail).

TIGER/Line state legislative district shapefiles (SLDU = upper chamber =
Senate, SLDL = lower chamber = House), by contrast, download directly with
no auth and no redirect chain: https://www2.census.gov/geo/tiger/TIGER{year}/
SLD{U,L}/tl_{year}_25_sld{u,l}.zip (25 = MA's FIPS code). Confirmed live for
the 2012 vintage (used 2012-2020) and the 2022 vintage (used 2022-present).

The 2001 vintage (used 2002-2010) is NOT yet wired up here: TIGER's
per-state SLDU/SLDL zip pattern only starts around TIGER2012 (TIGER2010/2011
directories exist but were empty for every state when checked, and TIGER
didn't publish standalone state-legislative-district shapefiles the same
way before then) — getting the 2001 vintage will need either MassGIS access
(once unblocked) or tracking down the pre-2012 Census 2000-era TIGER format.
Calling fetch_vintage("2001") raises NotImplementedError rather than
silently returning nothing.
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import click
import geopandas as gpd

from ma_politics.util.http import get, make_session

logger = logging.getLogger(__name__)

MA_FIPS = "25"

# vintage -> (label, TIGER release year to pull from)
# The TIGER release year need not equal the vintage's first election year —
# it just needs to be any TIGER year that falls within the vintage's span,
# since Census re-publishes the same current boundaries every year between
# redistricting cycles.
VINTAGES = {
    "2012-2020": 2013,
    "2022-present": 2023,
}

CHAMBER_TIGER = {"senate": "sldu", "house": "sldl"}


def _tiger_url(year: int, chamber: str) -> str:
    layer = CHAMBER_TIGER[chamber]
    return f"https://www2.census.gov/geo/tiger/TIGER{year}/{layer.upper()}/tl_{year}_25_{layer}.zip"


def fetch_vintage(vintage: str, chamber: str, out_dir: Path, session=None) -> Path:
    if vintage not in VINTAGES:
        raise NotImplementedError(
            f"No TIGER source wired up yet for vintage {vintage!r}. "
            "See this module's docstring — needs either MassGIS access "
            "(blocked pending hub.arcgis.com/arcgisserver.digital.mass.gov "
            "allowlisting) or the pre-2012 TIGER format."
        )
    session = session or make_session(min_interval_s=0.5)
    year = VINTAGES[vintage]
    url = _tiger_url(year, chamber)
    out_path = out_dir / f"{chamber}_{vintage}.geoparquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    resp = get(session, url)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        shp_names = [n for n in zf.namelist() if n.endswith(".shp")]
        if len(shp_names) != 1:
            raise ValueError(f"Expected exactly one .shp in {url}, found {shp_names}")
        # geopandas needs all sidecar files (.shx/.dbf/.prj) on disk together
        extract_dir = out_dir / f"_tmp_{chamber}_{vintage}"
        extract_dir.mkdir(exist_ok=True)
        zf.extractall(extract_dir)
        gdf = gpd.read_file(extract_dir / shp_names[0])

    gdf["chamber"] = chamber
    gdf["vintage"] = vintage
    gdf["source"] = f"TIGER{year}"
    gdf.to_parquet(out_path)
    logger.info("Wrote %d districts to %s (crs=%s)", len(gdf), out_path, gdf.crs)
    return out_path


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option(
    "--vintage",
    type=click.Choice(["2012-2020", "2022-present", "all"]),
    default="all",
)
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/boundaries"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, vintage: str, out_dir: Path, verbose: bool):
    """Fetch MA state legislative district boundaries from Census TIGER/Line."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    vintages = list(VINTAGES) if vintage == "all" else [vintage]
    session = make_session(min_interval_s=0.5)
    for c in chambers:
        for v in vintages:
            fetch_vintage(v, c, out_dir, session=session)


if __name__ == "__main__":
    main()
