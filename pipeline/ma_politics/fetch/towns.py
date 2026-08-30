"""Fetch MA town/municipality boundaries.

Source: Census TIGER/Line county subdivisions (COUSUB) — for New England
states, county subdivisions *are* the towns/cities, so this needs no
MassGIS dependency, consistent with district_boundaries.py. Verified live:
357 rows for MA (matches expectations: 351 municipalities plus a handful of
water-only/coastal entries TIGER includes as separate COUSUB records).

Unlike legislative districts, MA town boundaries are essentially static
across the redistricting vintages this project covers (no town has been
created, dissolved, or had its outer boundary meaningfully redrawn since
well before 2001) — so a single current-vintage town layer is used for the
town↔district overlay against *all* district vintages in build_crosswalks.py,
rather than fetching a town layer per vintage. If that assumption ever
turns out wrong for a specific town, re-visit here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from ma_politics.util.geo import TARGET_CRS, download_shapefile
from ma_politics.util.http import make_session

logger = logging.getLogger(__name__)

TOWNS_TIGER_YEAR = 2023


def fetch_towns(out_dir: Path, session=None) -> Path:
    session = session or make_session(min_interval_s=0.5)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "towns.geoparquet"
    extract_dir = out_dir / "_tmp_towns"

    url = f"https://www2.census.gov/geo/tiger/TIGER{TOWNS_TIGER_YEAR}/COUSUB/tl_{TOWNS_TIGER_YEAR}_25_cousub.zip"
    gdf = download_shapefile(url, None, extract_dir, session)
    gdf = gdf.to_crs(TARGET_CRS)
    gdf = gdf.rename(columns={"NAME": "town"})
    gdf["source"] = f"TIGER{TOWNS_TIGER_YEAR} COUSUB"

    gdf.to_parquet(out_path)
    logger.info("Wrote %d towns to %s (crs=%s)", len(gdf), out_path, gdf.crs)
    return out_path


@click.command()
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/boundaries"))
@click.option("-v", "--verbose", is_flag=True)
def main(out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    fetch_towns(out_dir)


if __name__ == "__main__":
    main()
