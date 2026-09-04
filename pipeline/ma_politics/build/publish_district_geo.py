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


def _combined_features(chamber: str, vintage: str, boundaries_dir: Path, records: list[dict]) -> list[dict]:
    """The shared feature-building logic behind both publish_combined
    (below, a standalone CLI reproducer that derives `records` itself via
    build_district_records — see that function's own caveat) and
    generate_site_data.py's own end-of-run call (which passes its already
    fully-resolved, post-apply_war records instead) — factored out so the
    two callers can't drift on what properties a combined-map feature
    carries.

    Beyond lean/competitiveness (the map's default coloring), each feature
    also carries a `years` list — one entry per election year this vintage
    has on record for that district, each with that year's own lean/
    competitiveness and that year's winner's own WAR and WAR-component
    values (lean/tide/incumbency, plus demographics/fundraising wherever
    that specific race has them — see apply_war's own docstring for why
    those two are sometimes null) and turnout ratio — the statewide map's
    own variable selector (site/assets/js/statewide-map.js) lets a viewer
    recolor by any of these instead of just lean, and its election-year
    selector (dependent on which vintage is loaded, since different
    vintages cover different year ranges) switches which year's `years`
    entry is actually displayed. The top-level (non-`years`) fields mirror
    the most recent year's own entry, so a consumer that doesn't care about
    the year selector (or a fresh page load, before any year is chosen)
    still gets sensible defaults without needing to index into `years`
    itself. Deliberately the *winner's* own component values, not an
    average across every candidate in the race — "how did the person who
    actually won perform on this factor" is the more legible statewide-map
    question, and matches what a district/candidate page's own attribution
    chart already shows for that same race's winner."""
    gdf = load_district_vintage(boundaries_dir, chamber, vintage)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)

    by_name = {d["district_name"]: d for d in records}

    def _year_props(entry: dict) -> dict:
        winner = next((c for c in entry["candidates"] if c["winner"]), None)
        return {
            "year": entry["year"],
            "lean_dem_share": entry["lean_dem_share"],
            "competitiveness": entry["competitiveness"],
            "competitiveness_label": entry["competitiveness_label"],
            "party_favored": entry["party_favored"],
            "is_uncontested": entry["is_uncontested"],
            "turnout_ratio": entry["turnout_ratio"],
            "winner_name": winner["name"] if winner else None,
            "winner_party": winner["party"] if winner else None,
            "winner_war": winner.get("war_resolved") if winner else None,
            "winner_lean_component": winner.get("lean_component") if winner else None,
            "winner_tide_component": winner.get("tide_component") if winner else None,
            "winner_incumbency_adjustment": winner.get("incumbency_adjustment") if winner else None,
            "winner_demographics_component": winner.get("demographics_component") if winner else None,
            "winner_fundraising_component": winner.get("fundraising_component") if winner else None,
        }

    features = []
    for _, row in gdf.iterrows():
        d = by_name.get(row["district_name"])
        if d is None:
            continue
        years = [_year_props(entry) for entry in d["results_by_year"]]
        latest = years[0] if years else {}
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "district_name": d["district_name"],
                    "chamber": chamber,
                    "vintage": vintage,
                    "url": district_url(chamber, d["district_name"], vintage),
                    "latest_year": latest.get("year"),
                    "years": years,
                    **{k: v for k, v in latest.items() if k != "year"},
                },
                "geometry": row.geometry.__geo_interface__,
            }
        )
    return features


def write_combined_from_records(chamber: str, vintage: str, boundaries_dir: Path, records: list[dict], out_dir: Path) -> int:
    """Writes the combined statewide-map FeatureCollection from records the
    caller already built (and, crucially, may already have run apply_war/
    apply_us_house_war over) — see generate_site_data.py's own main(),
    which calls this right after its WAR fits are applied so the map's
    winner_war/winner_*_component fields are the real fitted values, not
    null. publish_combined below is the CLI-only alternative that derives
    `records` itself instead of accepting them."""
    features = _combined_features(chamber, vintage, boundaries_dir, records)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{chamber}-{vintage}-all.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return len(features)


def publish_combined(chamber: str, vintage: str, boundaries_dir: Path, derived_dir: Path, out_dir: Path) -> int:
    """Standalone CLI reproducer for the combined statewide-map file: builds
    district records itself via build_district_records, the same function
    generate_site_data.py's own main() uses — but, unlike that pipeline
    stage, this entry point never calls apply_war/apply_us_house_war
    (fitting the WAR model needs statewide tide, OCPF finance matching, and
    demographics data this script has no reason to also wire up), so every
    winner_war/winner_*_component field it writes is null. Fine for
    reproducing the map's lean/competitiveness coloring standalone; for the
    real, WAR-enriched combined file, generate_site_data.py's main() calls
    write_combined_from_records directly with its own already-resolved
    records instead of going through this function — see that call site's
    own comment."""
    records = build_district_records(chamber, vintage, derived_dir)
    return write_combined_from_records(chamber, vintage, boundaries_dir, records, out_dir)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "us-house", "both"]), default="both")
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
