"""Derived analytics: district partisan lean and WAR (wins above
replacement, adapted from Split Ticket — see docs/PLAN.md §4 for the full
methodology writeup and citations).

Pipeline:
1. Take a statewide top-of-ticket race's *town-level* results (from
   fetch.pd43, e.g. Governor) and apportion each town's votes to districts
   using build.crosswalks' town<->district area-overlap shares. This is the
   same area-weighted-not-population-weighted simplification crosswalks.py
   documents — a town's votes are split across districts in proportion to
   how much of the town's *area* falls in each, not real precinct-level
   returns.
2. From apportioned district-level votes, compute each district's lean:
   the Democratic two-party vote share on that baseline race.
3. Match each state-legislative race (from fetch.pd43) to its district via
   name — PD43+'s district_raw strings ("Berkshire, Hampden, Franklin &
   Hampshire District") and the boundary files' district_name strings
   ("Berkshire-Hampden-Franklin-Hampshire District") use different
   separators for the same names; normalized comparison closes the gap.
   Logged, not silently dropped, for anything that doesn't resolve cleanly.
4. WAR = actual two-party vote share − expected share (district lean, or
   1 − lean for the opposing party). Only defined for Democratic/Republican
   candidates — a minor-party candidate has no meaningful "expected share"
   against a two-party baseline, so WAR is left null for them rather than
   computed against a baseline that doesn't apply.
"""

from __future__ import annotations

import logging
import re
from difflib import get_close_matches
from pathlib import Path

import click
import pandas as pd

logger = logging.getLogger(__name__)

MAJOR_PARTIES = {"Democratic", "Republican"}

# Two independently-sourced town name spellings need reconciling before any
# town-keyed join: TIGER COUSUB's NAME field suffixes some municipalities
# with "Town"/"City" (inconsistently — only some of MA's 351), while PD43+
# abbreviates directional prefixes ("N. Adams", "W. Springfield"). Verified
# live this closes the gap completely except for TIGER's one legitimate
# non-municipality placeholder row ("County subdivisions not defined",
# water/unassigned area, correctly has no PD43+ counterpart).
_DIRECTION_ABBREV = {"N.": "North", "S.": "South", "E.": "East", "W.": "West"}


def _normalize_town_name(name: str) -> str:
    name = re.sub(r"\s+(Town|City)$", "", name)
    parts = name.split()
    if parts and parts[0] in _DIRECTION_ABBREV:
        parts[0] = _DIRECTION_ABBREV[parts[0]]
    return " ".join(parts)


def _normalize_district_name(name: str) -> str:
    name = name.lower()
    name = name.replace("&", " and ")
    name = re.sub(r"[,\-]", " ", name)
    name = re.sub(r"\bdistrict\b", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def match_district_names(raw_names: list[str], boundary_names: list[str]) -> dict[str, str | None]:
    """raw_name (PD43+ district_raw) -> boundary_name, or None if unresolved.
    Exact match after normalization first; a close-match fallback (logged as
    such) catches anything with minor wording drift; unresolved names are
    logged with their nearest candidates so they can be fixed by hand."""
    norm_to_boundary = {_normalize_district_name(b): b for b in boundary_names}
    result: dict[str, str | None] = {}
    for raw in raw_names:
        norm = _normalize_district_name(raw)
        if norm in norm_to_boundary:
            result[raw] = norm_to_boundary[norm]
            continue
        close = get_close_matches(norm, list(norm_to_boundary), n=1, cutoff=0.85)
        if close:
            result[raw] = norm_to_boundary[close[0]]
            logger.info("Fuzzy-matched district name %r -> %r", raw, result[raw])
            continue
        result[raw] = None
        nearest = get_close_matches(norm, list(norm_to_boundary), n=3, cutoff=0.5)
        logger.warning("No district match for %r (nearest: %r)", raw, nearest)
    return result


def apportion_town_votes_to_districts(
    town_results: pd.DataFrame,
    overlap: pd.DataFrame,
    candidate_cols: list[str],
) -> pd.DataFrame:
    """town_results: one row per town for a single statewide race (from
    fetch.pd43's town_results table). overlap: town<->district rows for one
    chamber/vintage (from build.crosswalks), with a `pct_of_town` column.
    Returns one row per district_id with apportioned (float) vote totals."""
    overlap = overlap.copy()
    town_results = town_results.copy()
    overlap["_town_norm"] = overlap["town"].map(_normalize_town_name)
    town_results["_town_norm"] = town_results["town"].map(_normalize_town_name)

    merged = overlap.merge(town_results, on="_town_norm", how="inner", suffixes=("", "_pd43"))
    if len(merged) < len(overlap) * 0.99:
        logger.warning(
            "Only %d/%d overlap rows matched a town in town_results — check "
            "for town-name mismatches between the boundary and PD43+ sources.",
            len(merged),
            len(overlap),
        )
    for col in candidate_cols:
        merged[col] = merged[col] * merged["pct_of_town"]
    return merged.groupby(["district_id", "district_name"])[candidate_cols].sum().reset_index()


def compute_lean(
    apportioned: pd.DataFrame, dem_col: str, rep_col: str, out_col: str = "lean_dem_share"
) -> pd.DataFrame:
    out = apportioned[["district_id", "district_name"]].copy()
    two_party = apportioned[dem_col] + apportioned[rep_col]
    out[out_col] = apportioned[dem_col] / two_party
    out["baseline_two_party_votes"] = two_party
    return out


# (lower bound, label) pairs by two-party margin, standard Cook PVI-style
# bucketing — checked high to low against abs(lean_dem_share - 0.5) * 2.
_COMPETITIVENESS_BANDS = [
    (0.20, "Safe"),
    (0.10, "Likely"),
    (0.05, "Lean"),
    (0.0, "Tossup"),
]


def compute_competitiveness(lean: pd.DataFrame, lean_col: str = "lean_dem_share") -> pd.DataFrame:
    out = lean.copy()
    margin = (out[lean_col] - 0.5).abs() * 2
    out["party_favored"] = out[lean_col].apply(lambda x: "Democratic" if x >= 0.5 else "Republican")

    def _band(m: float) -> str:
        for lower, label in _COMPETITIVENESS_BANDS:
            if m >= lower:
                return label
        return _COMPETITIVENESS_BANDS[-1][1]

    out["competitiveness"] = margin.apply(_band)
    # e.g. "Safe D" / "Lean R" — built from the two columns above rather than
    # a separate lookup table so it can't drift out of sync with them.
    out["competitiveness_label"] = out["competitiveness"] + " " + out["party_favored"].map({"Democratic": "D", "Republican": "R"})
    return out


def compute_war(
    results: pd.DataFrame,
    races: pd.DataFrame,
    lean: pd.DataFrame,
    name_match: dict[str, str | None],
) -> pd.DataFrame:
    """results/races: from fetch.pd43 for one chamber/year (general-stage
    races only — WAR needs a clean D-vs-R two-party contest, not a primary).
    lean: from compute_lean, keyed by district_name. name_match: PD43+
    district_raw -> boundary district_name (from match_district_names)."""
    r = results.merge(races[["election_id", "district_raw", "stage", "is_special"]], on="election_id")
    r = r[(r["stage"] == "general") & (~r["is_special"])].copy()
    r["district_name"] = r["district_raw"].map(name_match)

    lean_by_name = lean.set_index("district_name")["lean_dem_share"]

    # Two-party vote share needs each race's D and R vote total, computed
    # once per election_id (not per row) then broadcast back.
    party_totals = (
        r[r["party"].isin(MAJOR_PARTIES)]
        .pivot_table(index="election_id", columns="party", values="votes", aggfunc="sum")
        .rename(columns={"Democratic": "dem_votes", "Republican": "rep_votes"})
    )
    r = r.merge(party_totals, on="election_id", how="left")
    two_party_votes = r["dem_votes"].fillna(0) + r["rep_votes"].fillna(0)

    r["actual_two_party_share"] = r["votes"] / two_party_votes
    r["district_lean_dem_share"] = r["district_name"].map(lean_by_name)

    expected = pd.Series(index=r.index, dtype=float)
    is_dem = r["party"] == "Democratic"
    is_rep = r["party"] == "Republican"
    expected[is_dem] = r.loc[is_dem, "district_lean_dem_share"]
    expected[is_rep] = 1 - r.loc[is_rep, "district_lean_dem_share"]
    r["expected_two_party_share"] = expected
    r["war"] = r["actual_two_party_share"] - r["expected_two_party_share"]
    r.loc[~r["party"].isin(MAJOR_PARTIES), "war"] = pd.NA

    return r


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate"]), required=True)
@click.option("--year", type=int, required=True)
@click.option("--vintage", required=True, help="e.g. 2022-present")
@click.option("--pd43-dir", type=click.Path(path_type=Path), default=Path("data/raw/pd43"))
@click.option("--baseline-dir", type=click.Path(path_type=Path), default=Path("data/raw/pd43_statewide"))
@click.option("--baseline-office", default="governor")
@click.option("--crosswalks-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber, year, vintage, pd43_dir, baseline_dir, baseline_office, crosswalks_dir, out_dir, verbose):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_races = pd.read_parquet(baseline_dir / f"{baseline_office}_races.parquet")
    baseline_town = pd.read_parquet(baseline_dir / f"{baseline_office}_town_results.parquet")
    baseline_general = baseline_races[
        (baseline_races["year"] == year) & (baseline_races["stage"] == "general")
    ]
    if len(baseline_general) != 1:
        raise ValueError(f"Expected exactly one {baseline_office} general race for {year}, got {len(baseline_general)}")
    election_id = baseline_general.iloc[0]["election_id"]
    town = baseline_town[baseline_town["election_id"] == election_id]

    overlap = pd.read_parquet(crosswalks_dir / "town_district_overlap.parquet")
    overlap = overlap[(overlap["chamber"] == chamber) & (overlap["vintage"] == vintage)]

    baseline_results = pd.read_parquet(baseline_dir / f"{baseline_office}_results.parquet")
    baseline_results = baseline_results[baseline_results["election_id"] == election_id]
    dem_name = baseline_results[baseline_results["party"] == "Democratic"].iloc[0]["candidate_name"]
    rep_name = baseline_results[baseline_results["party"] == "Republican"].iloc[0]["candidate_name"]

    apportioned = apportion_town_votes_to_districts(town, overlap, [dem_name, rep_name])
    lean = compute_lean(apportioned, dem_name, rep_name)
    lean = compute_competitiveness(lean)
    lean_path = out_dir / f"{chamber}_{vintage}_lean.parquet"
    lean.to_parquet(lean_path, index=False)
    logger.info(
        "Wrote %d district lean rows to %s (%s)",
        len(lean),
        lean_path,
        lean["competitiveness_label"].value_counts().to_dict(),
    )

    races = pd.read_parquet(pd43_dir / f"{chamber}_races.parquet")
    results = pd.read_parquet(pd43_dir / f"{chamber}_results.parquet")
    races_year = races[races["year"] == year]
    name_match = match_district_names(races_year["district_raw"].unique().tolist(), lean["district_name"].tolist())

    war = compute_war(results, races_year, lean, name_match)
    war_path = out_dir / f"{chamber}_{year}_war.parquet"
    war.to_parquet(war_path, index=False)
    logger.info("Wrote %d WAR rows to %s", len(war), war_path)


if __name__ == "__main__":
    main()
