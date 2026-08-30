"""Emit Jekyll-consumable content from the interim derived-metrics data:
one Markdown file per seat (with lean/competitiveness/WAR as YAML front
matter) into site/_seats/, per docs/PLAN.md §5/§7 — a collection of
front-matter files rendered by a single Liquid template, rather than a
separate Python/Node HTML generator, since Jekyll (via GitHub Actions,
not the Pages-native build) handles this natively.

Scope of this first pass: the current (2022-present) vintage only, both
chambers, using the 2022 general-election results already fetched and
verified (see pipeline/README.md). Historical vintages/years follow the
same shape once backfilled — this script doesn't hardcode "2022" beyond
its CLI defaults.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import click
import pandas as pd
import yaml

from ma_politics.util.names import normalize_town_name

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _clean_str(value) -> str | None:
    """PD43+ occasionally has no parseable party for a candidate (e.g. a
    losing write-in whose detail page carries no recognized party class —
    a real, pre-existing data gap, not a fetch bug; see fetch.pd43). pandas
    represents that as float NaN even in an otherwise-string column, and
    yaml.safe_dump renders float NaN as the YAML literal `.nan`, which
    Ruby's JSON generator (Jekyll's `jsonify` filter) then rejects outright
    ("NaN not allowed in JSON") — found by running an actual `jekyll
    build`, not caught by the Python side alone. Coerce to a real Python
    None so it serializes as YAML null / JSON null instead."""
    return None if pd.isna(value) else value


def candidate_slug(pd43_slug: str) -> str:
    """PD43+'s own candidate slug (e.g. "Paul-W-Mark", from their
    /candidates/view/ URLs) lowercased for consistency with this site's
    other (all-lowercase) slugs. Used as the candidate's durable identity
    instead of re-deriving one from their name, which risks collisions
    between different candidates with similar names."""
    return pd43_slug.lower()


def build_seat_records(chamber: str, year: int, vintage: str, derived_dir: Path) -> list[dict]:
    lean = pd.read_parquet(derived_dir / f"{chamber}_{vintage}_lean.parquet")
    war = pd.read_parquet(derived_dir / f"{chamber}_{year}_war.parquet")

    records = []
    for _, district in lean.iterrows():
        district_war = war[war["district_name"] == district["district_name"]]
        candidates = [
            {
                "name": row["candidate_name"],
                "slug": candidate_slug(row["candidate_slug"]),
                "party": _clean_str(row["party"]),
                "votes": int(row["votes"]) if pd.notna(row["votes"]) else None,
                "winner": bool(row["winner"]),
                "actual_two_party_share": (
                    round(float(row["actual_two_party_share"]), 4)
                    if pd.notna(row["actual_two_party_share"])
                    else None
                ),
                "war": round(float(row["war"]), 4) if pd.notna(row["war"]) else None,
            }
            for _, row in district_war.sort_values("votes", ascending=False).iterrows()
        ]
        is_uncontested = bool(district_war["is_uncontested"].iloc[0]) if len(district_war) else None

        records.append(
            {
                "chamber": chamber,
                "vintage": vintage,
                "year": year,
                "district_name": district["district_name"],
                "district_id": district["district_id"],
                "lean_dem_share": round(float(district["lean_dem_share"]), 4),
                "competitiveness": district["competitiveness"],
                "competitiveness_label": district["competitiveness_label"],
                "party_favored": district["party_favored"],
                "is_uncontested": is_uncontested,
                "candidates": candidates,
            }
        )
    return records


def write_seat_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = f"{record['chamber']}-{slugify(record['district_name'])}"
        front_matter = {**record, "title": record["district_name"], "layout": "seat"}
        path = out_dir / f"{slug}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d seat pages to %s", len(records), out_dir)


def build_candidate_records(chambers: list[str], year: int, derived_dir: Path) -> list[dict]:
    """One record per candidate_slug, with every race they ran across all
    given chambers this year. Combines all chambers' WAR tables *before*
    grouping by candidate_slug — a candidate who somehow ran in both a
    House and Senate race the same year (vanishingly rare, but a real
    possibility, unlike two different people sharing a slug) still gets
    one merged record with both races, rather than two per-chamber records
    that would silently overwrite each other at the same output filename
    if built separately."""
    war = pd.concat(
        [
            pd.read_parquet(derived_dir / f"{c}_{year}_war.parquet").assign(chamber=c, year=year)
            for c in chambers
        ],
        ignore_index=True,
    )
    records = []
    for slug, group in war.groupby("candidate_slug"):
        races = [
            {
                "chamber": row["chamber"],
                "year": year,
                "district_name": row["district_name"],
                "party": _clean_str(row["party"]),
                "votes": int(row["votes"]) if pd.notna(row["votes"]) else None,
                "winner": bool(row["winner"]),
                "actual_two_party_share": (
                    round(float(row["actual_two_party_share"]), 4)
                    if pd.notna(row["actual_two_party_share"])
                    else None
                ),
                "war": round(float(row["war"]), 4) if pd.notna(row["war"]) else None,
                "is_uncontested": bool(row["is_uncontested"]),
            }
            for _, row in group.sort_values("year", ascending=False).iterrows()
        ]
        latest = group.sort_values("year", ascending=False).iloc[0]
        records.append(
            {
                "slug": candidate_slug(slug),
                "name": latest["candidate_name"],
                "party": _clean_str(latest["party"]),
                "races": races,
            }
        )
    return records


def write_candidate_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "candidate"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d candidate pages to %s", len(records), out_dir)


def seat_url(chamber: str, district_name: str) -> str:
    return f"/seat/{chamber}-{slugify(district_name)}/"


def build_town_records(chambers: list[str], vintage: str, crosswalks_dir: Path, seat_records: list[dict]) -> list[dict]:
    """One record per town, listing every district (in any given chamber)
    that overlaps it — a town routinely splits across multiple districts,
    especially in denser areas (Boston alone spans 16 House districts in
    the 2022 vintage). Joined against the already-built seat_records for
    each district's current lean/winner rather than re-deriving from raw
    parquet, since that's already computed and correct."""
    overlap = pd.read_parquet(crosswalks_dir / "town_district_overlap.parquet")
    overlap = overlap[overlap["vintage"] == vintage]
    overlap = overlap[overlap["chamber"].isin(chambers)]
    # TIGER's one non-municipality placeholder row (water/unassigned area,
    # see fetch.towns) — not a real town, exclude.
    overlap = overlap[overlap["town"] != "County subdivisions not defined"]

    seat_by_key = {(s["chamber"], s["district_name"]): s for s in seat_records}

    records = []
    for raw_town, group in overlap.groupby("town"):
        # TIGER's NAME field inconsistently suffixes some municipalities
        # with "Town"/"City" (e.g. "Agawam Town") — same normalization
        # derived_metrics.py applies before joining town-level votes,
        # reused here so page titles/URLs read as "Agawam", not "Agawam Town".
        town = normalize_town_name(raw_town)
        districts = []
        for _, row in group.sort_values("pct_of_town", ascending=False).iterrows():
            seat = seat_by_key.get((row["chamber"], row["district_name"]))
            winner = next((c for c in seat["candidates"] if c["winner"]), None) if seat else None
            districts.append(
                {
                    "chamber": row["chamber"],
                    "district_name": row["district_name"],
                    "url": seat_url(row["chamber"], row["district_name"]),
                    "pct_of_town": round(float(row["pct_of_town"]), 4),
                    "lean_dem_share": seat["lean_dem_share"] if seat else None,
                    "competitiveness_label": seat["competitiveness_label"] if seat else None,
                    "current_rep": winner["name"] if winner else None,
                    "current_rep_party": winner["party"] if winner else None,
                }
            )
        records.append({"name": town, "slug": slugify(town), "districts": districts})
    return records


def write_town_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "town"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d town pages to %s", len(records), out_dir)


def build_party_records(seat_records: list[dict]) -> list[dict]:
    """One record per party that currently holds at least one seat, with
    every seat they hold and each winner's WAR — a natural "who's
    overperforming for this party" view. Built from seat_records' winners
    rather than a separate query, since "holds this seat" is exactly
    "is this seat's winner"."""
    parties: dict[str, list[dict]] = {}
    for seat in seat_records:
        winner = next((c for c in seat["candidates"] if c["winner"]), None)
        if not winner or not winner["party"]:
            continue
        parties.setdefault(winner["party"], []).append(
            {
                "chamber": seat["chamber"],
                "district_name": seat["district_name"],
                "url": seat_url(seat["chamber"], seat["district_name"]),
                "winner_name": winner["name"],
                "winner_slug": winner["slug"],
                "war": winner["war"],
            }
        )

    records = []
    for party, seats_held in parties.items():
        # Highest WAR (biggest overperformance) first; null-WAR (uncontested
        # or minor-party winner) entries sort last, not scattered by the
        # coincidence of comparing None to a float.
        seats_held_sorted = sorted(seats_held, key=lambda s: (s["war"] is None, -(s["war"] or 0)))
        by_chamber = {}
        for s in seats_held:
            by_chamber[s["chamber"]] = by_chamber.get(s["chamber"], 0) + 1
        records.append(
            {
                "name": party,
                "slug": slugify(party),
                "seat_count": len(seats_held),
                "seat_count_by_chamber": by_chamber,
                "seats_held": seats_held_sorted,
            }
        )
    return records


def write_party_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "party"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d party pages to %s", len(records), out_dir)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option("--year", type=int, default=2022)
@click.option("--vintage", default="2022-present")
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--crosswalks-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option("--seats-out-dir", type=click.Path(path_type=Path), default=Path("site/_seats"))
@click.option("--candidates-out-dir", type=click.Path(path_type=Path), default=Path("site/_candidates"))
@click.option("--towns-out-dir", type=click.Path(path_type=Path), default=Path("site/_towns"))
@click.option("--parties-out-dir", type=click.Path(path_type=Path), default=Path("site/_parties"))
@click.option("-v", "--verbose", is_flag=True)
def main(
    chamber: str,
    year: int,
    vintage: str,
    derived_dir: Path,
    crosswalks_dir: Path,
    seats_out_dir: Path,
    candidates_out_dir: Path,
    towns_out_dir: Path,
    parties_out_dir: Path,
    verbose: bool,
):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]

    seat_records = []
    for c in chambers:
        seat_records.extend(build_seat_records(c, year, vintage, derived_dir))
    write_seat_files(seat_records, seats_out_dir)

    candidate_records = build_candidate_records(chambers, year, derived_dir)
    write_candidate_files(candidate_records, candidates_out_dir)

    town_records = build_town_records(chambers, vintage, crosswalks_dir, seat_records)
    write_town_files(town_records, towns_out_dir)

    party_records = build_party_records(seat_records)
    write_party_files(party_records, parties_out_dir)


if __name__ == "__main__":
    main()
