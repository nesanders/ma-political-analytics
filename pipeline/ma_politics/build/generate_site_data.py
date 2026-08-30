"""Emit Jekyll-consumable content from the interim derived-metrics data:
Markdown-with-YAML-frontmatter files (districts/seats/candidates/towns/
parties) into site/_*, per docs/PLAN.md §5/§7 — a collection of front-
matter files rendered by a single Liquid template per type, rather than a
separate Python/Node HTML generator, since Jekyll (via GitHub Actions, not
the Pages-native build) handles this natively.

Two-tier district/seat model (matches docs/PLAN.md §7's original design,
completed here for the multi-year backfill):

- **District** (`/district/...`): one page per (chamber, district_name,
  vintage), accumulating every election year available for that vintage
  (a vintage spans several cycles, e.g. 2022-present covers both 2022 and
  2024). District *identity* is scoped to one vintage because boundaries
  and even names can change across redistricting — a "4th Middlesex" in
  one vintage isn't guaranteed to be the same geography as a same-named
  district in another.
- **Seat** (`/seat/...`): the *current*-vintage's district record, plus a
  `history` list walking backward through build.crosswalks' seat_lineage
  (best-area-overlap predecessor, however many vintage hops back that
  goes) to the districts it evolved from. This is the "persistent" view a
  user browsing by district naturally wants — "who represents this area
  today, and what was here before" — without needing to already know
  which vintage's naming a prior election used.

Both are driven by discovering *which* years' data actually exist on disk
(via each vintage's `{chamber}_{vintage}_{year}_lean.parquet` files) rather
than a hardcoded year list — running the pipeline for more years and
re-running this script is enough to pick them up, no code change needed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import click
import pandas as pd
import yaml

from ma_politics.build import campaign_finance_match, demographics_match
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


def district_slug(chamber: str, district_name: str, vintage: str) -> str:
    return f"{chamber}-{slugify(district_name)}-{slugify(vintage)}"


def district_url(chamber: str, district_name: str, vintage: str) -> str:
    return f"/district/{district_slug(chamber, district_name, vintage)}/"


def seat_url(chamber: str, district_name: str) -> str:
    return f"/seat/{chamber}-{slugify(district_name)}/"


def discover_years(chamber: str, vintage: str, derived_dir: Path) -> list[int]:
    """Which election years actually have derived-metrics output for this
    (chamber, vintage) — from the lean file's own name, which is year-
    scoped (see build.derived_metrics: lean is recomputed against a
    different statewide baseline race every cycle, so a vintage spanning
    several years needs one lean file per year)."""
    pattern = re.compile(rf"^{re.escape(chamber)}_{re.escape(vintage)}_(\d{{4}})_lean\.parquet$")
    years = []
    for p in derived_dir.glob(f"{chamber}_{vintage}_*_lean.parquet"):
        m = pattern.match(p.name)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _candidate_list(district_war: pd.DataFrame) -> list[dict]:
    return [
        {
            "name": row["candidate_name"],
            "slug": candidate_slug(row["candidate_slug"]),
            "party": _clean_str(row["party"]),
            "votes": int(row["votes"]) if pd.notna(row["votes"]) else None,
            "winner": bool(row["winner"]),
            "actual_two_party_share": (
                round(float(row["actual_two_party_share"]), 4) if pd.notna(row["actual_two_party_share"]) else None
            ),
            "war": round(float(row["war"]), 4) if pd.notna(row["war"]) else None,
        }
        for _, row in district_war.sort_values("votes", ascending=False).iterrows()
    ]


def build_district_records(chamber: str, vintage: str, derived_dir: Path) -> list[dict]:
    years = discover_years(chamber, vintage, derived_dir)
    if not years:
        return []

    lean_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{vintage}_{y}_lean.parquet") for y in years}
    war_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{y}_war.parquet") for y in years}

    # Union across years, not just the latest: a district still belongs on
    # this vintage's roster even if only an earlier year has been backfilled
    # so far (e.g. a partial/in-progress backfill run).
    roster = (
        pd.concat([lean_by_year[y][["district_id", "district_name"]] for y in years], ignore_index=True)
        .drop_duplicates("district_name")
    )

    records = []
    for _, row in roster.iterrows():
        district_name = row["district_name"]
        results_by_year = []
        for y in sorted(years, reverse=True):
            lean_rows = lean_by_year[y][lean_by_year[y]["district_name"] == district_name]
            if lean_rows.empty:
                continue
            lean_row = lean_rows.iloc[0]
            district_war = war_by_year[y][war_by_year[y]["district_name"] == district_name]
            is_uncontested = bool(district_war["is_uncontested"].iloc[0]) if len(district_war) else None
            turnout_ratio = (
                round(float(district_war["turnout_ratio"].iloc[0]), 4)
                if len(district_war) and pd.notna(district_war["turnout_ratio"].iloc[0])
                else None
            )
            results_by_year.append(
                {
                    "year": y,
                    "lean_dem_share": round(float(lean_row["lean_dem_share"]), 4),
                    "competitiveness": lean_row["competitiveness"],
                    "competitiveness_label": lean_row["competitiveness_label"],
                    "party_favored": lean_row["party_favored"],
                    "is_uncontested": is_uncontested,
                    "turnout_ratio": turnout_ratio,
                    "candidates": _candidate_list(district_war),
                }
            )
        if not results_by_year:
            continue

        # Incumbency, scoped to *within this vintage only* — not chased
        # across a redistricting boundary via seat_lineage, since a
        # lineage match is an area-overlap best-guess, not a guarantee the
        # same electorate (or even district name) carried over; claiming
        # someone is "the incumbent" off that guess would overstate what's
        # actually known. results_by_year is sorted descending by year, so
        # the entry one index later is the immediately preceding election
        # for this same district — an open seat (or the first year on
        # record for this vintage) leaves is_incumbent False rather than
        # guessing, and is_open_seat stays None (unknown) rather than
        # implying a confirmed open seat, when there's no prior-year data
        # to check against at all.
        for i, entry in enumerate(results_by_year):
            prev_winner_slug = None
            if i + 1 < len(results_by_year):
                prev_winner = next((c for c in results_by_year[i + 1]["candidates"] if c["winner"]), None)
                prev_winner_slug = prev_winner["slug"] if prev_winner else None
            for c in entry["candidates"]:
                c["is_incumbent"] = prev_winner_slug is not None and c["slug"] == prev_winner_slug
            entry["is_open_seat"] = (
                None if prev_winner_slug is None else not any(c["is_incumbent"] for c in entry["candidates"])
            )
        latest = results_by_year[0]
        records.append(
            {
                "chamber": chamber,
                "vintage": vintage,
                "district_id": row["district_id"],
                "district_name": district_name,
                # Same slug this record's own page file uses (write_district_files
                # below) — also what publish_district_geo.py names this
                # district's map GeoJSON file, so the district page can
                # build that file's URL directly instead of re-deriving the
                # slug in Liquid and risking it drift from either producer.
                "geo_slug": district_slug(chamber, district_name, vintage),
                "years": [ry["year"] for ry in results_by_year],
                "lean_dem_share": latest["lean_dem_share"],
                "competitiveness": latest["competitiveness"],
                "competitiveness_label": latest["competitiveness_label"],
                "party_favored": latest["party_favored"],
                "results_by_year": results_by_year,
            }
        )
    return records


def write_district_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = district_slug(record["chamber"], record["district_name"], record["vintage"])
        front_matter = {
            **record,
            "title": f"{record['district_name']} ({record['vintage']})",
            "layout": "district",
        }
        path = out_dir / f"{slug}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d district pages to %s", len(records), out_dir)


def build_seat_records(
    district_records_by_vintage: dict[str, list[dict]],
    current_vintage: str,
    lineage: pd.DataFrame,
) -> list[dict]:
    """The current vintage's district records, each with a `history` list
    walking backward through seat_lineage's best-area-overlap predecessor —
    however many vintage hops that chain reaches (currently up to two:
    2022-present -> 2012-2020 -> 2001-2010), not hardcoded to a fixed
    depth, so this keeps working if another vintage is added later."""
    by_key = {
        (r["chamber"], vintage, r["district_name"]): r
        for vintage, recs in district_records_by_vintage.items()
        for r in recs
    }

    records = []
    for d in district_records_by_vintage.get(current_vintage, []):
        chamber = d["chamber"]
        vintage, district_name = current_vintage, d["district_name"]
        history = []
        seen_vintages = {current_vintage}
        while True:
            preds = lineage[
                (lineage["chamber"] == chamber)
                & (lineage["new_vintage"] == vintage)
                & (lineage["new_district_name"] == district_name)
            ]
            if preds.empty:
                break
            best = preds.sort_values("pct_of_old_area", ascending=False).iloc[0]
            prev_vintage, prev_name = best["old_vintage"], best["old_district_name"]
            if prev_vintage in seen_vintages:
                break  # guard against any lineage cycle in the data
            prev_record = by_key.get((chamber, prev_vintage, prev_name))
            history.append(
                {
                    "vintage": prev_vintage,
                    "district_name": prev_name,
                    "url": district_url(chamber, prev_name, prev_vintage) if prev_record else None,
                    "overlap_pct": round(float(best["pct_of_old_area"]), 4),
                }
            )
            seen_vintages.add(prev_vintage)
            vintage, district_name = prev_vintage, prev_name
        records.append({**d, "history": history})
    return records


def write_seat_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = f"{record['chamber']}-{slugify(record['district_name'])}"
        front_matter = {**record, "title": record["district_name"], "layout": "seat"}
        path = out_dir / f"{slug}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d seat pages to %s", len(records), out_dir)


def build_candidate_records(district_records_by_vintage: dict[str, list[dict]]) -> list[dict]:
    """One record per candidate_slug, with every race they ran across every
    vintage/year/chamber this run has data for — built from the already-
    assembled district records (which carry is_incumbent and turnout_ratio,
    computed once there) rather than re-reading raw WAR parquet, so a
    candidate's own race history can't drift from what the district page
    for that same race shows. All years at once, not one CLI invocation
    per year, specifically so a candidate who ran in multiple election
    cycles gets one merged record instead of each year's run silently
    overwriting the last."""
    races_by_slug: dict[str, list[dict]] = {}
    latest_info: dict[str, tuple[int, str, str | None]] = {}  # slug -> (year, name, party)

    for vintage, records in district_records_by_vintage.items():
        for d in records:
            for entry in d["results_by_year"]:
                for c in entry["candidates"]:
                    races_by_slug.setdefault(c["slug"], []).append(
                        {
                            "chamber": d["chamber"],
                            "year": entry["year"],
                            "vintage": vintage,
                            "district_name": d["district_name"],
                            # Precomputed here (not reconstructed via Liquid's
                            # slugify filter in candidate.html) so this link
                            # can't drift from the district page's own actual
                            # filename the way a prior bug in this project did
                            # for a similarly-reconstructed candidate link.
                            "district_url": district_url(d["chamber"], d["district_name"], vintage),
                            "party": c["party"],
                            "votes": c["votes"],
                            "winner": c["winner"],
                            "actual_two_party_share": c["actual_two_party_share"],
                            "war": c["war"],
                            "is_uncontested": entry["is_uncontested"],
                            "is_incumbent": c["is_incumbent"],
                        }
                    )
                    prev = latest_info.get(c["slug"])
                    if prev is None or entry["year"] > prev[0]:
                        latest_info[c["slug"]] = (entry["year"], c["name"], c["party"])

    records = []
    for slug, races in races_by_slug.items():
        races_sorted = sorted(races, key=lambda r: (r["year"], r["chamber"]), reverse=True)
        _, name, party = latest_info[slug]
        records.append({"slug": slug, "name": name, "party": party, "races": races_sorted})
    return records


def write_candidate_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "candidate"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d candidate pages to %s", len(records), out_dir)


def build_town_records(chambers: list[str], vintage: str, crosswalks_dir: Path, seat_records: list[dict]) -> list[dict]:
    """One record per town, listing every district (in any given chamber)
    that overlaps it — a town routinely splits across multiple districts,
    especially in denser areas (Boston alone spans 16 House districts in
    the 2022 vintage). Joined against the already-built seat_records
    (current vintage, most recent year's winner) for each district's
    current lean/representative rather than re-deriving from raw parquet,
    since that's already computed and correct."""
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
            latest = seat["results_by_year"][0] if seat and seat["results_by_year"] else None
            winner = next((c for c in latest["candidates"] if c["winner"]), None) if latest else None
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
    """One record per party that currently holds at least one seat (most
    recent year of the current vintage), with every seat they hold and
    each winner's WAR — a natural "who's overperforming for this party"
    view. Built from seat_records' winners rather than a separate query,
    since "holds this seat" is exactly "is this seat's most recent
    winner"."""
    parties: dict[str, list[dict]] = {}
    for seat in seat_records:
        latest = seat["results_by_year"][0] if seat["results_by_year"] else None
        winner = next((c for c in latest["candidates"] if c["winner"]), None) if latest else None
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
@click.option("--current-vintage", default="2022-present", help="Vintage whose districts become /seat/ pages")
@click.option(
    "--vintages",
    default="2001-2010,2012-2020,2022-present",
    help="Comma-separated list of all vintages to build /district/ pages for",
)
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--crosswalks-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option(
    "--ocpf-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/ocpf"),
    help="Campaign finance data from fetch.campaign_finance; skipped (with a warning) if missing",
)
@click.option(
    "--demographics-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/demographics"),
    help="Census PL 94-171/ACS data from fetch.demographics; only covers the current vintage, skipped if missing",
)
@click.option("--seats-out-dir", type=click.Path(path_type=Path), default=Path("site/_seats"))
@click.option("--districts-out-dir", type=click.Path(path_type=Path), default=Path("site/_districts"))
@click.option("--candidates-out-dir", type=click.Path(path_type=Path), default=Path("site/_candidates"))
@click.option("--towns-out-dir", type=click.Path(path_type=Path), default=Path("site/_towns"))
@click.option("--parties-out-dir", type=click.Path(path_type=Path), default=Path("site/_parties"))
@click.option("-v", "--verbose", is_flag=True)
def main(
    chamber: str,
    current_vintage: str,
    vintages: str,
    derived_dir: Path,
    crosswalks_dir: Path,
    ocpf_dir: Path,
    demographics_dir: Path,
    seats_out_dir: Path,
    districts_out_dir: Path,
    candidates_out_dir: Path,
    towns_out_dir: Path,
    parties_out_dir: Path,
    verbose: bool,
):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    vintage_list = [v.strip() for v in vintages.split(",") if v.strip()]

    district_records_by_vintage: dict[str, list[dict]] = {}
    for vintage in vintage_list:
        recs = []
        for c in chambers:
            recs.extend(build_district_records(c, vintage, derived_dir))
        district_records_by_vintage[vintage] = recs

    # Census demographics (PL 94-171 + ACS) only exist for the current
    # vintage — see demographics_match.py's docstring — so only those
    # records get enriched; other vintages' district pages simply have no
    # demographics section. Enriching in place, before write_district_files
    # and build_seat_records, means the current vintage's seat records
    # (spread from these same district records) pick it up for free.
    if current_vintage in district_records_by_vintage:
        for c in chambers:
            chamber_records = [d for d in district_records_by_vintage[current_vintage] if d["chamber"] == c]
            demographics_by_name = demographics_match.load_demographics(
                c, demographics_dir, [d["district_name"] for d in chamber_records]
            )
            for d in chamber_records:
                if d["district_name"] in demographics_by_name:
                    d["demographics"] = demographics_by_name[d["district_name"]]

    all_district_records = [r for recs in district_records_by_vintage.values() for r in recs]
    write_district_files(all_district_records, districts_out_dir)

    lineage = pd.read_parquet(crosswalks_dir / "seat_lineage.parquet")
    seat_records = build_seat_records(district_records_by_vintage, current_vintage, lineage)
    write_seat_files(seat_records, seats_out_dir)

    candidate_records = build_candidate_records(district_records_by_vintage)
    if (ocpf_dir / "filers.parquet").exists():
        finance_by_slug = campaign_finance_match.load_and_match(candidate_records, ocpf_dir)
        for candidate in candidate_records:
            if candidate["slug"] in finance_by_slug:
                candidate["ocpf_finance"] = finance_by_slug[candidate["slug"]]
    else:
        logger.warning("No OCPF data at %s — candidate pages will have no campaign-finance section", ocpf_dir)
    write_candidate_files(candidate_records, candidates_out_dir)

    town_records = build_town_records(chambers, current_vintage, crosswalks_dir, seat_records)
    write_town_files(town_records, towns_out_dir)

    party_records = build_party_records(seat_records)
    write_party_files(party_records, parties_out_dir)


if __name__ == "__main__":
    main()
