"""Publish one small GeoJSON file per (chamber, district_name, vintage) for
the district page map (site/_layouts/district.html), plus one combined
FeatureCollection per (chamber, vintage) — every district's geometry and
lean/competitiveness in a single file — for the statewide overview map
(site/map/). See docs/PLAN.md §6.

Reuses build.crosswalks' load_district_vintage() for the (district_id,
district_name, geometry) roster rather than re-deriving the per-vintage
column mapping (TIGER's SLDLST/SLDUST + NAMELSAD vs. the MIT 2001-vintage
shapefile's REPDISTNUM/REP_DIST — three different source schemas, already
normalized once in that module), so the district_name values here are
guaranteed to match what derived_metrics.py and generate_site_data.py
already use — the whole point of publishing these next to (not instead
of) the existing per-entity pages.

Geometry is reprojected to EPSG:4326 (WGS84, what GeoJSON/web maps expect
— the source files are EPSG:4269/NAD83, close but not identical) and
simplified (Douglas-Peucker, ~11m tolerance at MA's latitude) to cut
per-file size by roughly 80% with no visible loss at the zoom levels a
single-district map actually renders at — verified by comparing rendered
file sizes before publishing at this tolerance, not guessed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from ma_politics.build.crosswalks import load_district_vintage
from ma_politics.build.generate_site_data import build_district_records, district_slug, district_url

logger = logging.getLogger(__name__)

SIMPLIFY_TOLERANCE_DEG = 0.0001


def publish_vintage(chamber: str, vintage: str, boundaries_dir: Path, out_dir: Path) -> int:
    gdf = load_district_vintage(boundaries_dir, chamber, vintage)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for _, row in gdf.iterrows():
        feature = {
            "type": "Feature",
            "properties": {"district_name": row["district_name"], "chamber": chamber, "vintage": vintage},
            "geometry": row.geometry.__geo_interface__,
        }
        # Same slug function generate_site_data.py uses for the district
        # page's own filename/URL — imported rather than reimplemented, so
        # this file's name is guaranteed to match what the page fetches,
        # not just conventionally similar.
        slug = district_slug(chamber, row["district_name"], vintage)
        path = out_dir / f"{slug}.geojson"
        path.write_text(json.dumps(feature))
        count += 1
    return count


def publish_combined(chamber: str, vintage: str, boundaries_dir: Path, derived_dir: Path, out_dir: Path) -> int:
    """One FeatureCollection per (chamber, vintage) — every district's
    geometry plus its lean/competitiveness/URL, for the statewide overview
    map (site/map/), which needs to color and click through ~160-200
    districts at once without a fetch per district. Districts with no
    results data yet (derived_metrics.py hasn't been run for any year in
    this vintage) are skipped — geometry alone can't be colored by
    anything meaningful, and a colorless district would just be visual
    noise on an otherwise-informative map."""
    gdf = load_district_vintage(boundaries_dir, chamber, vintage)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)

    by_name = {d["district_name"]: d for d in build_district_records(chamber, vintage, derived_dir)}

    features = []
    for _, row in gdf.iterrows():
        d = by_name.get(row["district_name"])
        if d is None:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "district_name": d["district_name"],
                    "chamber": chamber,
                    "vintage": vintage,
                    "lean_dem_share": d["lean_dem_share"],
                    "competitiveness": d["competitiveness"],
                    "competitiveness_label": d["competitiveness_label"],
                    "party_favored": d["party_favored"],
                    "url": district_url(chamber, d["district_name"], vintage),
                },
                "geometry": row.geometry.__geo_interface__,
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{chamber}-{vintage}-all.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return len(features)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option(
    "--vintages",
    default="2001-2010,2012-2020,2022-present",
    help="Comma-separated list of vintages to publish district geometry for",
)
@click.option("--boundaries-dir", type=click.Path(path_type=Path), default=Path("data/raw/boundaries"))
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("site/assets/data/geo"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, vintages: str, boundaries_dir: Path, derived_dir: Path, out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    vintage_list = [v.strip() for v in vintages.split(",") if v.strip()]

    total = 0
    for c in chambers:
        for vintage in vintage_list:
            n = publish_vintage(c, vintage, boundaries_dir, out_dir)
            logger.info("Wrote %d district geometries for %s %s to %s", n, c, vintage, out_dir)
            total += n

            n_combined = publish_combined(c, vintage, boundaries_dir, derived_dir, out_dir)
            logger.info("Wrote combined map (%d districts) for %s %s to %s", n_combined, c, vintage, out_dir)
    logger.info("Wrote %d district geometry files total to %s", total, out_dir)


if __name__ == "__main__":
    main()
