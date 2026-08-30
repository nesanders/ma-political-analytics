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

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


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
                "party": row["party"],
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
                "party": row["party"],
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
                "party": latest["party"],
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


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option("--year", type=int, default=2022)
@click.option("--vintage", default="2022-present")
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--seats-out-dir", type=click.Path(path_type=Path), default=Path("site/_seats"))
@click.option("--candidates-out-dir", type=click.Path(path_type=Path), default=Path("site/_candidates"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, year: int, vintage: str, derived_dir: Path, seats_out_dir: Path, candidates_out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]

    seat_records = []
    for c in chambers:
        seat_records.extend(build_seat_records(c, year, vintage, derived_dir))
    write_seat_files(seat_records, seats_out_dir)

    candidate_records = build_candidate_records(chambers, year, derived_dir)
    write_candidate_files(candidate_records, candidates_out_dir)


if __name__ == "__main__":
    main()
