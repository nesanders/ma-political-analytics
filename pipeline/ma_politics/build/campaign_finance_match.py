"""Matches this site's own PD43+-derived candidates to OCPF campaign-finance
filers, then aggregates OCPF's per-year totals onto each matched candidate
— see docs/PLAN.md §2/§9 and pipeline/README.md for the fetch side
(fetch.campaign_finance) this builds on.

**Why this is a real matching problem, not a join**: OCPF's filer roster
(`filers.parquet`) has no PD43+ candidate_slug, election_id, or year — it's
a standing roster of committees/candidates, one row per `cpf_id`, carrying
only their *most recently filed* district/office (`district_name_sought`/
`_held`), not a per-election history the way this site's own race data is.
Names differ too: OCPF's `candidate_first_name` is sometimes a nickname
("Nick") where PD43+'s display name uses the formal one ("Nicholas A.") —
found live checking a known real case (Nicholas A. Boldyga / OCPF's "Nick
Boldyga", cpf_id 14831).

**Matching strategy, deliberately not exact-name matching**: last name
(normalized) + district (normalized, "District" suffix stripped) +
chamber, checked against *every* race a candidate is known to have run
(not just their most recent one), since OCPF's roster reflects only one
point-in-time district that might not be the specific year being matched.
Last name + a specific numbered district is a strong enough constraint on
its own that first-name variation (nicknames, initials) doesn't need to
factor in — two different people sharing a last name *and* running for
the exact same numbered district is a vanishingly unlikely collision.

**A real, documented limitation this scope accepts**: last-name extraction
is "the final whitespace-separated token, generational suffixes (Jr./Sr./
II/III/IV) stripped first" — this mishandles multi-word last names (e.g.
"Van Buren"), which would show up as an unmatched candidate rather than a
wrong match (a name that fails to find its OCPF filer is safe; a name
that matches the *wrong* filer is not, so this design errs toward missing
matches over risking incorrect ones).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_OFFICE_TO_CHAMBER = {"House": "house", "Senate": "senate"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_district(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"\bdistrict\b", "", name)
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return name.strip()


def last_name_from_display_name(display_name: str) -> str:
    """"Nicholas A. Boldyga" -> "boldyga". Takes the final whitespace-
    separated token, skipping a trailing generational suffix (with or
    without its own punctuation, e.g. "John Smith, III" or "John Smith
    III") — see module docstring for what this does and doesn't handle.
    Also strips PD43+'s trailing "(W)" write-in marker first (e.g. "Kevin
    Patrick McKeown (W)") — found live: without this, "(w)" itself was
    being extracted as the "last name" for every write-in candidate."""
    display_name = re.sub(r"\s*\(w\)\s*$", "", display_name, flags=re.IGNORECASE)
    tokens = [t.strip(",.") for t in display_name.split()]
    tokens = [t for t in tokens if t]
    while tokens and tokens[-1].lower() in _SUFFIXES:
        tokens.pop()
    return tokens[-1].lower() if tokens else ""


def build_ocpf_lookup(filers: pd.DataFrame) -> dict[tuple[str, str, str], set[int]]:
    """(last_name, district, chamber) -> set of cpf_ids. Both
    district_name_sought and district_name_held are indexed — a filer's
    "sought" district may be stale relative to what they actually held,
    or vice versa, and either can be the one that matches a given year's
    race."""
    lookup: dict[tuple[str, str, str], set[int]] = {}
    for _, row in filers.iterrows():
        last = str(row["candidate_last_name"] or "").strip().lower()
        if not last:
            continue
        for office_col, district_col in (
            ("office_type_sought", "district_name_sought"),
            ("office_type_held", "district_name_held"),
        ):
            chamber = _OFFICE_TO_CHAMBER.get(row[office_col])
            if chamber is None:
                continue
            district = normalize_district(str(row[district_col] or ""))
            if not district:
                continue
            lookup.setdefault((last, district, chamber), set()).add(int(row["cpf_id"]))
    return lookup


def match_candidates_to_ocpf(
    candidate_records: list[dict], filers: pd.DataFrame, finance_summary: pd.DataFrame
) -> dict[str, dict]:
    """candidate_records: this site's own build_candidate_records() output.
    Returns {candidate_slug: {"cpf_ids": [...], "by_year": {year: {"total_raised":
    ..., "total_spent": ...}}}} for every candidate with at least one
    matched cpf_id and at least one year of finance data — candidates with
    neither simply don't appear in the result, rather than an all-null
    placeholder entry."""
    lookup = build_ocpf_lookup(filers)
    finance_by_cpf_year = finance_summary.set_index(["cpf_id", "year"])[["total_raised", "total_spent"]]

    result: dict[str, dict] = {}
    matched_count = 0
    for candidate in candidate_records:
        last = last_name_from_display_name(candidate["name"])
        if not last:
            continue
        cpf_ids: set[int] = set()
        for race in candidate["races"]:
            district = normalize_district(race["district_name"])
            cpf_ids |= lookup.get((last, district, race["chamber"]), set())
        if not cpf_ids:
            continue

        by_year: dict[int, dict] = {}
        for cpf_id in cpf_ids:
            for year in {r["year"] for r in candidate["races"]}:
                if (cpf_id, year) not in finance_by_cpf_year.index:
                    continue
                row = finance_by_cpf_year.loc[(cpf_id, year)]
                entry = by_year.setdefault(year, {"total_raised": 0.0, "total_spent": 0.0})
                entry["total_raised"] += float(row["total_raised"])
                entry["total_spent"] += float(row["total_spent"])

        if by_year:
            matched_count += 1
            result[candidate["slug"]] = {
                "cpf_ids": sorted(cpf_ids),
                "by_year": {y: {k: round(v, 2) for k, v in vals.items()} for y, vals in by_year.items()},
            }

    logger.info(
        "Matched %d of %d candidates to OCPF finance data (by last name + district + chamber)",
        matched_count,
        len(candidate_records),
    )
    return result


def load_and_match(candidate_records: list[dict], ocpf_dir: Path) -> dict[str, dict]:
    filers = pd.read_parquet(ocpf_dir / "filers.parquet")
    finance_summary = pd.read_parquet(ocpf_dir / "finance_summary.parquet")
    return match_candidates_to_ocpf(candidate_records, filers, finance_summary)
