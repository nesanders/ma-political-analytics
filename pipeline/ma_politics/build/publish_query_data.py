"""Publish flat, queryable Parquet tables (and a matching JSON schema card)
for the AskAI feature's client-side DuckDB-Wasm instance — see
docs/PLAN.md §8. These are the *same* underlying numbers as the Jekyll
front matter generate_site_data.py writes, just reshaped for SQL querying
instead of per-entity page rendering: one flat table per concept rather
than nested per-seat/per-candidate documents.

Written to site/assets/data/ as real, static, versioned files — deployed
alongside the rest of the site, no server needed. DuckDB-Wasm fetches them
with HTTP range requests, so it only pulls the row groups a given query
actually touches.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
import pandas as pd

logger = logging.getLogger(__name__)


def build_seats_table(chambers: list[str], year: int, vintage: str, derived_dir: Path) -> pd.DataFrame:
    frames = []
    for c in chambers:
        lean = pd.read_parquet(derived_dir / f"{c}_{vintage}_lean.parquet")
        war = pd.read_parquet(derived_dir / f"{c}_{year}_war.parquet")
        is_uncontested = war.groupby("district_name")["is_uncontested"].first()
        lean = lean.copy()
        lean["chamber"] = c
        lean["year"] = year
        lean["vintage"] = vintage
        lean["is_uncontested"] = lean["district_name"].map(is_uncontested)
        frames.append(lean)
    out = pd.concat(frames, ignore_index=True)
    return out[
        [
            "chamber",
            "year",
            "vintage",
            "district_id",
            "district_name",
            "lean_dem_share",
            "competitiveness",
            "competitiveness_label",
            "party_favored",
            "is_uncontested",
        ]
    ]


def build_results_table(chambers: list[str], year: int, derived_dir: Path) -> pd.DataFrame:
    frames = []
    for c in chambers:
        war = pd.read_parquet(derived_dir / f"{c}_{year}_war.parquet")
        war = war.copy()
        war["chamber"] = c
        war["year"] = year
        frames.append(war)
    out = pd.concat(frames, ignore_index=True)
    return out[
        [
            "chamber",
            "year",
            "district_name",
            "candidate_name",
            "candidate_slug",
            "party",
            "votes",
            "winner",
            "is_uncontested",
            "actual_two_party_share",
            "district_lean_dem_share",
            "war",
        ]
    ]


def build_towns_table(chambers: list[str], vintage: str, crosswalks_dir: Path) -> pd.DataFrame:
    from ma_politics.util.names import normalize_town_name

    overlap = pd.read_parquet(crosswalks_dir / "town_district_overlap.parquet")
    overlap = overlap[(overlap["vintage"] == vintage) & (overlap["chamber"].isin(chambers))]
    overlap = overlap[overlap["town"] != "County subdivisions not defined"].copy()
    overlap["town"] = overlap["town"].map(normalize_town_name)
    return overlap[["town", "chamber", "vintage", "district_id", "district_name", "pct_of_town"]]


SCHEMA_CARD = {
    "description": (
        "MA state legislative election data: House (160 districts) and Senate "
        "(40 districts) races. WAR (wins above replacement) is adapted from "
        "Split Ticket's published methodology, not an original metric — see "
        "https://github.com/nesanders/ma-political-analytics/blob/main/docs/PLAN.md "
        "section 4 for the full definition and citations."
    ),
    "tables": {
        "seats": {
            "description": "One row per (chamber, district, year): the district's partisan lean and competitiveness.",
            "columns": {
                "chamber": "'house' or 'senate'",
                "year": "election year",
                "vintage": "redistricting vintage this district geometry belongs to, e.g. '2022-present'",
                "district_id": "short internal district code",
                "district_name": "human-readable district name, e.g. 'Fourth Middlesex District'",
                "lean_dem_share": (
                    "Democratic two-party vote share on a statewide baseline race (e.g. Governor), "
                    "apportioned to this district by town-area overlap. 0.5 = even; >0.5 leans Democratic."
                ),
                "competitiveness": "Safe / Likely / Lean / Tossup, by margin from lean_dem_share",
                "competitiveness_label": "competitiveness + favored party, e.g. 'Safe D', 'Tossup R'",
                "party_favored": "'Democratic' or 'Republican' — whichever lean_dem_share favors",
                "is_uncontested": "true if only one major party fielded a candidate in the general",
            },
        },
        "results": {
            "description": "One row per candidate per general-election race — the actual outcome, joined to the seat's expected lean via WAR.",
            "columns": {
                "chamber": "'house' or 'senate'",
                "year": "election year",
                "district_name": "human-readable district name — join key to seats.district_name",
                "candidate_name": "candidate's display name",
                "candidate_slug": "candidate's URL slug, e.g. 'cindy-f-friedman' — matches /candidate/<slug>/",
                "party": "candidate's party, or null if PD43+ has no parseable party for them",
                "votes": "raw vote count",
                "winner": "true if this candidate won the race",
                "is_uncontested": "true if this race had no opposing major-party candidate",
                "actual_two_party_share": "this candidate's share of (Democratic + Republican) votes in the race",
                "district_lean_dem_share": "the district's baseline lean at the time of this race (same as seats.lean_dem_share)",
                "war": (
                    "actual_two_party_share minus the expected share from district_lean_dem_share. "
                    "Only defined for Democratic/Republican candidates. Positive = overperformed the "
                    "baseline; negative = underperformed. Inflated for uncontested races — see is_uncontested."
                ),
            },
        },
        "towns": {
            "description": "One row per (town, chamber, district): how much of a town's land area falls in each legislative district. A town is often split across several districts.",
            "columns": {
                "town": "municipality name",
                "chamber": "'house' or 'senate'",
                "vintage": "redistricting vintage",
                "district_id": "short internal district code — join key to seats.district_id",
                "district_name": "human-readable district name — join key to seats.district_name",
                "pct_of_town": (
                    "share of the town's land AREA (not population) in this district, 0-1. "
                    "A known simplification — see the design plan."
                ),
            },
        },
    },
    "example_queries": [
        {
            "question": "Which Senate seats are Democratic but competitive (Tossup or Lean)?",
            "sql": (
                "SELECT district_name, lean_dem_share, competitiveness_label "
                "FROM seats WHERE chamber = 'senate' AND party_favored = 'Democratic' "
                "AND competitiveness IN ('Tossup', 'Lean') ORDER BY lean_dem_share"
            ),
        },
        {
            "question": "Who overperformed their district's lean the most in the House in 2022?",
            "sql": (
                "SELECT candidate_name, district_name, party, war FROM results "
                "WHERE chamber = 'house' AND year = 2022 AND war IS NOT NULL "
                "ORDER BY war DESC LIMIT 10"
            ),
        },
        {
            "question": "Which districts does Worcester span?",
            "sql": (
                "SELECT chamber, district_name, pct_of_town FROM towns "
                "WHERE town = 'Worcester' ORDER BY chamber, pct_of_town DESC"
            ),
        },
    ],
}


def publish(chambers: list[str], year: int, vintage: str, derived_dir: Path, crosswalks_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    seats = build_seats_table(chambers, year, vintage, derived_dir)
    seats.to_parquet(out_dir / "seats.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(seats), out_dir / "seats.parquet")

    results = build_results_table(chambers, year, derived_dir)
    results.to_parquet(out_dir / "results.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(results), out_dir / "results.parquet")

    towns = build_towns_table(chambers, vintage, crosswalks_dir)
    towns.to_parquet(out_dir / "towns.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(towns), out_dir / "towns.parquet")

    schema_path = out_dir / "schema.json"
    schema_path.write_text(json.dumps(SCHEMA_CARD, indent=2))
    logger.info("Wrote schema card to %s", schema_path)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option("--year", type=int, default=2022)
@click.option("--vintage", default="2022-present")
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--crosswalks-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("site/assets/data"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, year: int, vintage: str, derived_dir: Path, crosswalks_dir: Path, out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    publish(chambers, year, vintage, derived_dir, crosswalks_dir, out_dir)


if __name__ == "__main__":
    main()
