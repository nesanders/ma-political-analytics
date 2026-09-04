"""Build geometric crosswalks from the fetched boundary data:

1. **Town <-> district overlap**, per chamber/vintage — how much of each
   town falls in each district. Needed because PD43+ election results are
   reported by town, but districts (especially in dense areas like Boston)
   routinely split towns across multiple districts.
2. **Seat lineage** across consecutive redistricting vintages — which new
   district(s) a given old district's territory mostly became. Powers
   "seat over time" trend charts that need to span a redistricting (see
   docs/PLAN.md §3, `SeatLineage`).

Both are **area-weighted**, not population-weighted: overlap is computed
from polygon geometry alone. This is a real, documented simplification —
area share is a reasonable proxy for population share for most MA towns
(fairly uniform density within a town) but will be noticeably off for a
town split between a dense village center and rural outskirts. A
population-weighted version would need block-level Census population
apportioned by the same overlay, which is a real follow-up, not done here.

Also out of scope here: matching PD43+'s district name strings (e.g. "8th
Essex District") to these boundary files' district identifiers. That's a
name-normalization/fuzzy-matching problem distinct from this module's
purely geometric overlays, and belongs in its own step later
(generate_site_data.py or a dedicated script) once there's a concrete
consumer to validate matches against.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)

# Equal-ish-area, meters-based projected CRS for MA — used for all area
# calculations here (the fetched files are in EPSG:4269, geographic, where
# "area" isn't a real areal measure).
PROJECTED_CRS = "EPSG:26986"  # NAD83 / Massachusetts Mainland (meters)

VINTAGES = ["2001-2010", "2012-2020", "2022-present"]

# (chamber, vintage) -> (district_id_col, district_name_col) in the raw
# fetched files — three different source schemas (MIT 2001-vintage shapefile
# vs. TIGER 2012/2022) normalized to a common (district_id, district_name).
# us-house's fetcher (congressional_boundaries.py) already normalizes to
# district_id/district_name itself (its three vintages have three different
# native column names of their own — CD108FP/CD113FP/CD118FP — normalized at
# fetch time instead of here since none of them are shared with house/senate's
# own schemas anyway), so its mapping here is just the identity.
_DISTRICT_COLS = {
    ("house", "2001-2010"): ("REPDISTNUM", "REP_DIST"),
    ("senate", "2001-2010"): ("SENDISTNUM", "SEN_DIST"),
    ("house", "2012-2020"): ("SLDLST", "NAMELSAD"),
    ("senate", "2012-2020"): ("SLDUST", "NAMELSAD"),
    ("house", "2022-present"): ("SLDLST", "NAMELSAD"),
    ("senate", "2022-present"): ("SLDUST", "NAMELSAD"),
    ("us-house", "2001-2010"): ("district_id", "district_name"),
    ("us-house", "2012-2020"): ("district_id", "district_name"),
    ("us-house", "2022-present"): ("district_id", "district_name"),
}


def load_towns(boundaries_dir: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_parquet(boundaries_dir / "towns.geoparquet")
    return gdf.to_crs(PROJECTED_CRS)[["town", "geometry"]]


def load_district_vintage(boundaries_dir: Path, chamber: str, vintage: str) -> gpd.GeoDataFrame:
    id_col, name_col = _DISTRICT_COLS[(chamber, vintage)]
    gdf = gpd.read_parquet(boundaries_dir / f"{chamber}_{vintage}.geoparquet")
    gdf = gdf.to_crs(PROJECTED_CRS)
    out = gdf[[id_col, name_col, "geometry"]].rename(
        columns={id_col: "district_id", name_col: "district_name"}
    )
    out["district_id"] = out["district_id"].astype(str)
    return out


def town_district_overlap(towns: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> pd.DataFrame:
    """One row per (town, district) that actually intersect, with the
    overlap area and what share of the town / of the district it represents."""
    towns = towns.copy()
    towns["_town_area"] = towns.geometry.area
    districts = districts.copy()
    districts["_district_area"] = districts.geometry.area

    overlay = gpd.overlay(towns, districts, how="intersection", keep_geom_type=True)
    overlay["overlap_area"] = overlay.geometry.area
    # Slivers from imprecise/mismatched coastlines between independently
    # sourced town and district files are noise, not real overlap — drop
    # anything under 100 m^2 (~the size of a house lot).
    overlay = overlay[overlay["overlap_area"] > 100]

    overlay["pct_of_town"] = overlay["overlap_area"] / overlay["_town_area"]
    overlay["pct_of_district"] = overlay["overlap_area"] / overlay["_district_area"]

    return overlay[
        ["town", "district_id", "district_name", "overlap_area", "pct_of_town", "pct_of_district"]
    ].reset_index(drop=True)


def seat_lineage(old_districts: gpd.GeoDataFrame, new_districts: gpd.GeoDataFrame) -> pd.DataFrame:
    """One row per (old_district, new_district) pair that overlap, with what
    share of the *old* district's area ended up in the new one — the basis
    for "this is the closest successor" seat-lineage links."""
    old = old_districts.rename(columns={"district_id": "old_district_id", "district_name": "old_district_name"})
    new = new_districts.rename(columns={"district_id": "new_district_id", "district_name": "new_district_name"})
    old["_old_area"] = old.geometry.area

    overlay = gpd.overlay(old, new, how="intersection", keep_geom_type=True)
    overlay["overlap_area"] = overlay.geometry.area
    overlay = overlay[overlay["overlap_area"] > 100]
    overlay["pct_of_old_area"] = overlay["overlap_area"] / overlay["_old_area"]

    return overlay[
        [
            "old_district_id",
            "old_district_name",
            "new_district_id",
            "new_district_name",
            "overlap_area",
            "pct_of_old_area",
        ]
    ].sort_values(["old_district_id", "pct_of_old_area"], ascending=[True, False]).reset_index(drop=True)


def build_all(boundaries_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    towns = load_towns(boundaries_dir)

    town_overlap_frames = []
    for chamber in ("house", "senate", "us-house"):
        for vintage in VINTAGES:
            districts = load_district_vintage(boundaries_dir, chamber, vintage)
            overlap = town_district_overlap(towns, districts)
            overlap["chamber"] = chamber
            overlap["vintage"] = vintage
            town_overlap_frames.append(overlap)
            logger.info("%s %s: %d town-district overlap rows", chamber, vintage, len(overlap))

    town_district = pd.concat(town_overlap_frames, ignore_index=True)
    town_district_path = out_dir / "town_district_overlap.parquet"
    town_district.to_parquet(town_district_path, index=False)
    logger.info("Wrote %d rows to %s", len(town_district), town_district_path)

    lineage_frames = []
    for chamber in ("house", "senate", "us-house"):
        for old_vintage, new_vintage in zip(VINTAGES, VINTAGES[1:]):
            old_d = load_district_vintage(boundaries_dir, chamber, old_vintage)
            new_d = load_district_vintage(boundaries_dir, chamber, new_vintage)
            lineage = seat_lineage(old_d, new_d)
            lineage["chamber"] = chamber
            lineage["old_vintage"] = old_vintage
            lineage["new_vintage"] = new_vintage
            lineage_frames.append(lineage)
            logger.info("%s %s->%s: %d lineage rows", chamber, old_vintage, new_vintage, len(lineage))

    seat_lineage_df = pd.concat(lineage_frames, ignore_index=True)
    seat_lineage_path = out_dir / "seat_lineage.parquet"
    seat_lineage_df.to_parquet(seat_lineage_path, index=False)
    logger.info("Wrote %d rows to %s", len(seat_lineage_df), seat_lineage_path)


@click.command()
@click.option("--boundaries-dir", type=click.Path(path_type=Path), default=Path("data/raw/boundaries"))
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option("-v", "--verbose", is_flag=True)
def main(boundaries_dir: Path, out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    build_all(boundaries_dir, out_dir)


if __name__ == "__main__":
    main()
