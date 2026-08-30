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

from ma_politics.build import campaign_finance_match
from ma_politics.build.generate_site_data import build_candidate_records, build_district_records

logger = logging.getLogger(__name__)


def build_seats_table(chambers: list[str], vintages: list[str], derived_dir: Path) -> pd.DataFrame:
    """Built from generate_site_data.build_district_records() — the exact
    same records the Jekyll district/seat pages render — rather than
    re-reading the lean/WAR parquet independently, so this table can't
    drift from what the site itself shows, and picks up turnout_ratio for
    free instead of needing its own parallel computation."""
    rows = []
    for c in chambers:
        for vintage in vintages:
            for d in build_district_records(c, vintage, derived_dir):
                for entry in d["results_by_year"]:
                    rows.append(
                        {
                            "chamber": d["chamber"],
                            "year": entry["year"],
                            "vintage": d["vintage"],
                            "district_id": d["district_id"],
                            "district_name": d["district_name"],
                            "lean_dem_share": entry["lean_dem_share"],
                            "competitiveness": entry["competitiveness"],
                            "competitiveness_label": entry["competitiveness_label"],
                            "party_favored": entry["party_favored"],
                            "is_uncontested": entry["is_uncontested"],
                            "turnout_ratio": entry["turnout_ratio"],
                        }
                    )
    return pd.DataFrame(rows)


def build_results_table(chambers: list[str], vintages: list[str], derived_dir: Path) -> pd.DataFrame:
    """Same rationale as build_seats_table: built from the already-computed
    district records (which carry is_incumbent, resolved once there against
    the prior election within the same vintage) instead of a separate pass
    over raw WAR parquet."""
    rows = []
    for c in chambers:
        for vintage in vintages:
            for d in build_district_records(c, vintage, derived_dir):
                for entry in d["results_by_year"]:
                    for cand in entry["candidates"]:
                        rows.append(
                            {
                                "chamber": d["chamber"],
                                "year": entry["year"],
                                "district_name": d["district_name"],
                                "candidate_name": cand["name"],
                                "candidate_slug": cand["slug"],
                                "party": cand["party"],
                                "votes": cand["votes"],
                                "winner": cand["winner"],
                                "is_uncontested": entry["is_uncontested"],
                                "is_incumbent": cand["is_incumbent"],
                                "actual_two_party_share": cand["actual_two_party_share"],
                                "district_lean_dem_share": entry["lean_dem_share"],
                                "war": cand["war"],
                            }
                        )
    return pd.DataFrame(rows)


def build_finance_table(chambers: list[str], vintages: list[str], derived_dir: Path, ocpf_dir: Path) -> pd.DataFrame:
    """OCPF campaign-finance totals per candidate per year, matched via
    campaign_finance_match — same best-effort last-name+district+chamber
    match described there and on the methodology page. Empty (not missing)
    if ocpf_dir has no data, so callers can skip publishing this table
    without a special case."""
    if not (ocpf_dir / "filers.parquet").exists():
        return pd.DataFrame(columns=["candidate_slug", "candidate_name", "year", "total_raised", "total_spent"])

    district_records_by_vintage = {
        vintage: [d for c in chambers for d in build_district_records(c, vintage, derived_dir)] for vintage in vintages
    }
    candidate_records = build_candidate_records(district_records_by_vintage)
    finance_by_slug = campaign_finance_match.load_and_match(candidate_records, ocpf_dir)

    rows = []
    for candidate in candidate_records:
        finance = finance_by_slug.get(candidate["slug"])
        if not finance:
            continue
        for year, totals in finance["by_year"].items():
            rows.append(
                {
                    "candidate_slug": candidate["slug"],
                    "candidate_name": candidate["name"],
                    "year": year,
                    "total_raised": totals["total_raised"],
                    "total_spent": totals["total_spent"],
                }
            )
    return pd.DataFrame(rows)


def build_towns_table(chambers: list[str], vintages: list[str], crosswalks_dir: Path) -> pd.DataFrame:
    from ma_politics.util.names import normalize_town_name

    overlap = pd.read_parquet(crosswalks_dir / "town_district_overlap.parquet")
    overlap = overlap[(overlap["vintage"].isin(vintages)) & (overlap["chamber"].isin(chambers))]
    overlap = overlap[overlap["town"] != "County subdivisions not defined"].copy()
    overlap["town"] = overlap["town"].map(normalize_town_name)
    return overlap[["town", "chamber", "vintage", "district_id", "district_name", "pct_of_town"]]


SCHEMA_CARD = {
    "description": (
        "MA state legislative election data: House (160 districts) and Senate "
        "(40 districts) races. WAR (wins above replacement) is adapted from "
        "Split Ticket's published methodology, not an original metric — see "
        "https://github.com/nesanders/ma-political-analytics/blob/HEAD/docs/PLAN.md "
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
                "turnout_ratio": (
                    "this race's two-party vote total divided by the district's apportioned two-party "
                    "vote total on the statewide baseline race — a 'roll-off' measure, not a share of "
                    "eligible voters. Can exceed 1.0. See the methodology page."
                ),
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
                "is_incumbent": (
                    "true if this candidate won the immediately preceding election for this same "
                    "district within the same redistricting vintage. Never true for a district's first "
                    "election on record in a vintage (nothing to compare against) — not the same as "
                    "confirmed false."
                ),
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
        "finance": {
            "description": (
                "OCPF campaign-finance totals per candidate per year. Only candidates matched to an OCPF "
                "filer appear here — not every candidate has one (some file exempt, some just weren't "
                "matched — see the methodology page). Absence from this table isn't evidence of zero "
                "fundraising."
            ),
            "columns": {
                "candidate_slug": "join key to results.candidate_slug",
                "candidate_name": "candidate's display name",
                "year": "calendar year of the OCPF filing period",
                "total_raised": "total dollars raised that year, summed across every matched OCPF committee",
                "total_spent": "total dollars spent that year, summed across every matched OCPF committee",
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
            "question": "Which House races had the lowest turnout relative to the statewide baseline in 2022?",
            "sql": (
                "SELECT district_name, turnout_ratio FROM seats "
                "WHERE chamber = 'house' AND year = 2022 ORDER BY turnout_ratio ASC LIMIT 10"
            ),
        },
        {
            "question": "How many incumbents won re-election vs. lost, in the House in 2022?",
            "sql": (
                "SELECT winner, COUNT(*) AS n FROM results "
                "WHERE chamber = 'house' AND year = 2022 AND is_incumbent GROUP BY winner"
            ),
        },
        {
            "question": "Which districts does Worcester span?",
            "sql": (
                "SELECT chamber, district_name, pct_of_town FROM towns "
                "WHERE town = 'Worcester' ORDER BY chamber, pct_of_town DESC"
            ),
        },
        {
            "question": "Who raised the most money among 2022 House candidates?",
            "sql": (
                "SELECT f.candidate_name, f.total_raised FROM finance f "
                "JOIN results r ON r.candidate_slug = f.candidate_slug AND r.year = f.year "
                "WHERE r.chamber = 'house' AND f.year = 2022 ORDER BY f.total_raised DESC LIMIT 10"
            ),
        },
    ],
}


def publish(
    chambers: list[str], vintages: list[str], derived_dir: Path, crosswalks_dir: Path, ocpf_dir: Path, out_dir: Path
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    seats = build_seats_table(chambers, vintages, derived_dir)
    seats.to_parquet(out_dir / "seats.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(seats), out_dir / "seats.parquet")

    results = build_results_table(chambers, vintages, derived_dir)
    results.to_parquet(out_dir / "results.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(results), out_dir / "results.parquet")

    towns = build_towns_table(chambers, vintages, crosswalks_dir)
    towns.to_parquet(out_dir / "towns.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(towns), out_dir / "towns.parquet")

    finance = build_finance_table(chambers, vintages, derived_dir, ocpf_dir)
    finance.to_parquet(out_dir / "finance.parquet", index=False)
    logger.info("Wrote %d rows to %s", len(finance), out_dir / "finance.parquet")

    schema_path = out_dir / "schema.json"
    schema_path.write_text(json.dumps(SCHEMA_CARD, indent=2))
    logger.info("Wrote schema card to %s", schema_path)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option(
    "--vintages",
    default="2001-2010,2012-2020,2022-present",
    help="Comma-separated list of all vintages to publish",
)
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--crosswalks-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option("--ocpf-dir", type=click.Path(path_type=Path), default=Path("data/raw/ocpf"))
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("site/assets/data"))
@click.option("-v", "--verbose", is_flag=True)
def main(
    chamber: str, vintages: str, derived_dir: Path, crosswalks_dir: Path, ocpf_dir: Path, out_dir: Path, verbose: bool
):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    vintage_list = [v.strip() for v in vintages.split(",") if v.strip()]
    publish(chambers, vintage_list, derived_dir, crosswalks_dir, ocpf_dir, out_dir)


if __name__ == "__main__":
    main()
