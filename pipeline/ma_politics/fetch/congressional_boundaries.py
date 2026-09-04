"""Fetch MA U.S. House (congressional) district boundaries, one file per
redistricting vintage — same three vintages already used for state House/
Senate boundaries (see district_boundaries.py): "2001-2010", "2012-2020",
"2022-present". Unlike state legislative districts, TIGER covers all three
vintages directly (no MIT GeoData Repository fallback needed for 2001-2010),
confirmed live (2026-09):

- 2001-2010 (10 districts, the pre-2010-census map, used 2002-2010):
  TIGER's per-Congress CD archive, not its regular per-year directories —
  https://www2.census.gov/geo/tiger/TIGER2010/CD/108/tl_2010_25_cd108.zip
  (108th Congress = the map's first Congress; TIGER's regular
  TIGER{2007..2010}/CD/ directories are all empty for this era, only the
  nested .../CD/108/ and .../CD/111/ subdirectories carry files). Already
  per-state (STATEFP00=25 only) and already 10 rows, one per district.
- 2012-2020 (9 districts, used 2012-2020): TIGER only ever published this
  map as a whole-US file, never split by state, e.g.
  https://www2.census.gov/geo/tiger/TIGER2013/CD/tl_2013_us_cd113.zip
  (113th Congress) — filtered to STATEFP=25 after loading. Confirmed the
  same 9-district MA map is re-published unchanged under cd112/cd114/cd115/
  cd116 in other years spanning this vintage; 113 is used for consistency
  with district_boundaries.py's own TIGER_VINTAGES pick of TIGER2013 for
  the equivalent state-legislative vintage.
- 2022-present (9 districts, used 2022-present):
  https://www2.census.gov/geo/tiger/TIGER2023/CD/tl_2023_25_cd118.zip
  (118th Congress). Per-state again, like 2001-2010.

Column names carry the Congress number as a suffix (CD108FP, CD113FP,
CD118FP; NAMELSAD00 for the 2001 vintage vs. NAMELSAD for the other two) —
normalized here to (district_id, district_name) matching
district_district_overlap.py's / crosswalks.py's own convention for state
legislative districts, so build_crosswalks.py can be extended to congressional
districts with the same code shape.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import click

from ma_politics.util.geo import TARGET_CRS, download_shapefile
from ma_politics.util.http import make_session

logger = logging.getLogger(__name__)

MA_FIPS = "25"


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _to_pd43_style_name(namelsad: str) -> str:
    """TIGER's own NAMELSAD ("Congressional District 9") puts the number
    last and spells out no ordinal, unlike every other district name this
    site already matches against (PD43+'s own "1st Congressional
    District", and, for state legislative districts, "1st Essex
    District" — see build.derived_metrics.match_district_names /
    util.names.normalize_district_name, which strip ordinal suffixes and
    the word "district" but never reorder tokens, so a same-number
    reordering like "Congressional District 9" vs. "9th Congressional
    District" doesn't collide even after normalization). Reformatted here,
    at fetch time, into PD43+'s own word order instead of teaching the
    shared normalizer to also tolerate reordering — found live: every one
    of MA's 9-10 congressional districts failed to match under the
    original TIGER order, all with the same "different word order, same
    numbers" near-miss."""
    m = re.match(r"^Congressional District (\d+)$", namelsad)
    if not m:
        raise ValueError(f"Unexpected NAMELSAD format: {namelsad!r}")
    return f"{_ordinal(int(m.group(1)))} Congressional District"

# vintage -> (URL, id_col, name_col, statefp_col, filter_to_ma)
# filter_to_ma=True for the one whole-US file; the other two are already
# MA-only downloads.
_VINTAGE_SOURCES = {
    "2001-2010": (
        "https://www2.census.gov/geo/tiger/TIGER2010/CD/108/tl_2010_25_cd108.zip",
        "CD108FP",
        "NAMELSAD00",
        "STATEFP00",
        False,
    ),
    "2012-2020": (
        "https://www2.census.gov/geo/tiger/TIGER2013/CD/tl_2013_us_cd113.zip",
        "CD113FP",
        "NAMELSAD",
        "STATEFP",
        True,
    ),
    "2022-present": (
        "https://www2.census.gov/geo/tiger/TIGER2023/CD/tl_2023_25_cd118.zip",
        "CD118FP",
        "NAMELSAD",
        "STATEFP",
        False,
    ),
}

VINTAGES = list(_VINTAGE_SOURCES)


def fetch_vintage(vintage: str, out_dir: Path, session=None) -> Path:
    session = session or make_session(min_interval_s=0.5)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"us-house_{vintage}.geoparquet"
    extract_dir = out_dir / f"_tmp_us-house_{vintage}"

    url, id_col, name_col, statefp_col, filter_to_ma = _VINTAGE_SOURCES[vintage]
    gdf = download_shapefile(url, None, extract_dir, session)
    if filter_to_ma:
        gdf = gdf[gdf[statefp_col] == MA_FIPS]

    out = gdf[[id_col, name_col, "geometry"]].rename(columns={id_col: "district_id", name_col: "district_name"})
    out["district_id"] = out["district_id"].astype(str)
    out["district_name"] = out["district_name"].map(_to_pd43_style_name)
    out = out.to_crs(TARGET_CRS)
    out["chamber"] = "us-house"
    out["vintage"] = vintage
    out["source"] = url
    out.to_parquet(out_path)
    logger.info("Wrote %d districts to %s (crs=%s)", len(out), out_path, out.crs)
    return out_path


@click.command()
@click.option("--vintage", type=click.Choice([*VINTAGES, "all"]), default="all")
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/boundaries"))
@click.option("-v", "--verbose", is_flag=True)
def main(vintage: str, out_dir: Path, verbose: bool):
    """Fetch MA U.S. House (congressional) district boundaries from TIGER, one
    file per redistricting vintage."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    vintages = list(VINTAGES) if vintage == "all" else [vintage]
    session = make_session(min_interval_s=0.5)
    for v in vintages:
        fetch_vintage(v, out_dir, session=session)


if __name__ == "__main__":
    main()
