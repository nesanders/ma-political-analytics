"""Fetch MA state legislative election results from PD43+
(electionstats.state.ma.us), the Secretary of the Commonwealth's official
historical election-results database.

Structure verified against the live site (2026-08):
  - Search: /elections/search/year_from:{Y}/year_to:{Y}/stage:{S}/office_id:{O}/
    returns one <a href="/elections/view/{id}/"> per race.
  - Detail page /elections/view/{id}/: <title> is
    "PD43+ » {year} {office} General Election {district}" or
    "PD43+ » {year} {office} {party} Primary {district}"; each candidate is a
    <div class="candidate"> whose *parent* div carries classes like
    "item democratic_party winner" — that parent's class list is the
    reliable source for party and winner, not the (often-blank, esp. for
    primaries) <span class="party"> text.
  - CSV download /elections/download/{id}/precincts_include:0/: municipality-
    level vote counts, columns = one per candidate (name only, no party) plus
    "All Others", "Blanks", "Total Votes Cast"; row 2 repeats party per
    candidate for generals but is blank for primaries (redundant with the
    detail-page party anyway); last row is "TOTALS".

Only the municipality-level download (precincts_include:0) is used — it's
enough for both race totals and the town-level breakdown our partisan-lean
baseline needs (see docs/PLAN.md §2/§4). Precinct-level
(precincts_include:1) is available at the same URL pattern if finer
granularity is ever needed.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import click
import pandas as pd
from bs4 import BeautifulSoup

from ma_politics.util.http import get, make_session

logger = logging.getLogger(__name__)

BASE_URL = "https://electionstats.state.ma.us"
OFFICE_IDS = {"house": 8, "senate": 9}

# PD43+'s own stage vocabulary (see the "SearchOfficeId"/"stageListForOffice*"
# <select> options on /elections/search/).
STAGE_GENERAL = "General"
STAGE_PRIMARIES = "Primaries"  # all parties' primaries in one query

TITLE_RE = re.compile(
    r"^PD43\+\s*»\s*(?P<year>\d{4})\s+(?P<office>State (?:Senate|Representative))\s+"
    r"(?P<special>Special\s+)?(?:(?P<party>.+?)\s+Primary|General Election)\s+(?P<district>.+)$"
)


@dataclass
class Candidate:
    slug: str
    name: str
    party: str | None
    winner: bool


@dataclass
class Race:
    election_id: str
    year: int
    chamber: str  # "house" | "senate"
    stage: str  # "general" | "primary"
    party: str | None  # set for primaries, None for generals
    is_special: bool  # special election (mid-cycle vacancy), not a regular cycle
    district_raw: str
    source_url: str
    candidates: list[Candidate] = field(default_factory=list)


def search_election_ids(
    session, chamber: str, stage: str, year: int
) -> list[str]:
    """Return the sorted, deduped list of election_ids for one
    chamber/stage/year from the PD43+ search results page."""
    office_id = OFFICE_IDS[chamber]
    url = f"{BASE_URL}/elections/search/year_from:{year}/year_to:{year}/stage:{stage}/office_id:{office_id}"
    resp = get(session, url)
    soup = BeautifulSoup(resp.text, "lxml")
    ids = set()
    for a in soup.find_all("a", href=re.compile(r"^/elections/view/\d+/?$")):
        ids.add(a["href"].strip("/").split("/")[-1])
    return sorted(ids, key=int)


_PARTY_CLASS_RE = re.compile(r"^(?P<slug>[a-z_]+)_party$")


def fetch_race_detail(session, election_id: str, chamber: str) -> Race:
    url = f"{BASE_URL}/elections/view/{election_id}/"
    resp = get(session, url)
    soup = BeautifulSoup(resp.text, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else ""
    m = TITLE_RE.match(title)
    if not m:
        raise ValueError(f"Unrecognized election title format: {title!r} ({url})")

    year = int(m.group("year"))
    party = m.group("party")
    stage = "primary" if party else "general"
    is_special = bool(m.group("special"))
    district_raw = m.group("district").strip()

    candidates: list[Candidate] = []
    for cdiv in soup.find_all("div", class_="candidate"):
        link = cdiv.find("a", href=re.compile(r"^/candidates/view/"))
        name_span = cdiv.find("span", class_="display_name")
        if not link or not name_span:
            continue
        slug = link["href"].strip("/").split("/")[-1]
        name = name_span.get_text(strip=True)

        item = cdiv.find_parent(class_=lambda c: c and "item" in c.split())
        item_classes = item.get("class", []) if item else []
        winner = "winner" in item_classes
        cand_party = None
        for cls in item_classes:
            pm = _PARTY_CLASS_RE.match(cls)
            if pm:
                cand_party = pm.group("slug").replace("_", " ").title()
        candidates.append(Candidate(slug=slug, name=name, party=cand_party, winner=winner))

    return Race(
        election_id=election_id,
        year=year,
        chamber=chamber,
        stage=stage,
        party=party,
        is_special=is_special,
        district_raw=district_raw,
        source_url=url,
        candidates=candidates,
    )


def _parse_int(s: str) -> int:
    s = s.strip().replace(",", "").replace('"', "")
    return int(s) if s else 0


def fetch_town_results(session, election_id: str) -> tuple[list[str], list[dict]]:
    """Returns (candidate_names_in_csv_order, town_rows) where each town row
    is {"town": ..., <candidate_name>: votes, ..., "all_others": ..., "blanks": ..., "total": ...}.
    Excludes the trailing TOTALS row (race totals are just the column sums)."""
    url = f"{BASE_URL}/elections/download/{election_id}/precincts_include:0/"
    resp = get(session, url)
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    if len(rows) < 3:
        raise ValueError(f"Unexpectedly short CSV for election {election_id}: {rows}")

    header = rows[0]
    # header: ["City/Town", "", "", cand1, cand2, ..., "All Others", "Blanks", "Total Votes Cast"]
    candidate_cols = header[3:-3]
    town_rows = []
    for row in rows[2:]:  # row[1] is the party row, skip it
        if not row or not row[0].strip():
            continue
        town = row[0].strip()
        if town.upper() == "TOTALS":
            continue
        values = row[3:]
        entry = {"town": town}
        for name, val in zip(candidate_cols, values[: len(candidate_cols)]):
            entry[name] = _parse_int(val)
        entry["all_others"] = _parse_int(values[len(candidate_cols)]) if len(values) > len(candidate_cols) else 0
        entry["blanks"] = _parse_int(values[len(candidate_cols) + 1]) if len(values) > len(candidate_cols) + 1 else 0
        entry["total"] = _parse_int(values[len(candidate_cols) + 2]) if len(values) > len(candidate_cols) + 2 else 0
        town_rows.append(entry)

    return candidate_cols, town_rows


def races_to_frames(races: list[Race], town_results: dict[str, tuple[list[str], list[dict]]]):
    race_rows = []
    result_rows = []
    town_rows_out = []

    for race in races:
        race_rows.append(
            {
                "election_id": race.election_id,
                "year": race.year,
                "chamber": race.chamber,
                "stage": race.stage,
                "party": race.party,
                "is_special": race.is_special,
                "district_raw": race.district_raw,
                "source_url": race.source_url,
            }
        )
        csv_names, town_rows = town_results.get(race.election_id, ([], []))
        totals_by_name = {n: 0 for n in csv_names}
        for row in town_rows:
            for n in csv_names:
                totals_by_name[n] += row.get(n, 0)
            town_rows_out.append({"election_id": race.election_id, **row})

        for cand in race.candidates:
            votes = totals_by_name.get(cand.name)
            if votes is None:
                logger.warning(
                    "Candidate %r (election %s) not found in CSV columns %r",
                    cand.name,
                    race.election_id,
                    csv_names,
                )
            result_rows.append(
                {
                    "election_id": race.election_id,
                    "candidate_slug": cand.slug,
                    "candidate_name": cand.name,
                    "party": cand.party,
                    "winner": cand.winner,
                    "votes": votes,
                }
            )

    return (
        pd.DataFrame(race_rows),
        pd.DataFrame(result_rows),
        pd.DataFrame(town_rows_out),
    )


def fetch_years(
    chamber: str, year_from: int, year_to: int, out_dir: Path, min_interval_s: float = 0.5
) -> None:
    session = make_session(min_interval_s=min_interval_s)
    out_dir.mkdir(parents=True, exist_ok=True)

    races_path = out_dir / f"{chamber}_races.parquet"
    existing_ids: set[str] = set()
    if races_path.exists():
        existing_ids = set(pd.read_parquet(races_path)["election_id"].astype(str))

    all_races: list[Race] = []
    town_results: dict[str, tuple[list[str], list[dict]]] = {}

    for year in range(year_from, year_to + 1):
        for stage in (STAGE_GENERAL, STAGE_PRIMARIES):
            ids = search_election_ids(session, chamber, stage, year)
            logger.info("%s %s %s: %d elections", chamber, year, stage, len(ids))
            for election_id in ids:
                if election_id in existing_ids:
                    continue
                race = fetch_race_detail(session, election_id, chamber)
                candidate_cols, town_rows = fetch_town_results(session, election_id)
                all_races.append(race)
                town_results[election_id] = (candidate_cols, town_rows)

    if not all_races:
        logger.info("Nothing new to fetch.")
        return

    races_df, results_df, town_df = races_to_frames(all_races, town_results)

    for name, df in (("races", races_df), ("results", results_df), ("town_results", town_df)):
        path = out_dir / f"{chamber}_{name}.parquet"
        if path.exists():
            df = pd.concat([pd.read_parquet(path), df], ignore_index=True)
        df.to_parquet(path, index=False)
        logger.info("Wrote %d total rows to %s", len(df), path)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option("--year-from", type=int, default=2002)
@click.option("--year-to", type=int, default=2024)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/pd43"),
)
@click.option("--min-interval-s", type=float, default=0.5, help="Minimum seconds between requests.")
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, year_from: int, year_to: int, out_dir: Path, min_interval_s: float, verbose: bool):
    """Fetch PD43+ election results for MA state House/Senate races.

    Idempotent: election_ids already present in <out_dir>/<chamber>_races.parquet
    are skipped, so re-running after a future election only fetches new rows.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    for c in chambers:
        fetch_years(c, year_from, year_to, out_dir, min_interval_s=min_interval_s)


if __name__ == "__main__":
    main()
