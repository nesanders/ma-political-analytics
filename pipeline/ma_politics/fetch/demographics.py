"""Fetch district-level demographics from the Census Bureau's data API.

**Requires a free Census API key** — sign up at
https://api.census.gov/data/key_signup.html (instant, just an email) and
set it as the CENSUS_API_KEY environment variable. Confirmed live (2026-08)
that api.census.gov now rejects every request without a key, including
trivial ones — this wasn't previously true and the key requirement can't be
worked around. This module is written against the API's long-stable,
well-documented request format but has NOT been exercised against a live
response in this environment (no key available here) — verify against a
small request (e.g. --vintage 2022-present --chamber senate) before trusting
it for a full run.

Two datasets, both queried directly by "state legislative district (upper
chamber)" [[= Senate]] / "(lower chamber)" [[= House]] geography, which the
Census API supports natively — no need to do our own point-in-polygon work:

- 2020 Census PL 94-171 redistricting data (`dec/pl`): exact total
  population and voting-age population per district, as drawn for the
  *current* (2022-present) vintage only — PL 94-171 is produced once per
  redistricting cycle for the geography in effect at release time, so this
  does not give the 2012 or 2001 vintages. Historical vintages need areal
  interpolation of block-level 2020 (or 2010) population onto the older
  district polygons instead (see docs/PLAN.md §2) — not implemented here
  yet.
- ACS 5-year (`acs/acs5`): broader attributes (median income, education,
  etc.) at whatever geography vintage the requested ACS year's TIGER
  geography corresponds to.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import click
import pandas as pd

from ma_politics.util.http import get, make_session

logger = logging.getLogger(__name__)

MA_FIPS = "25"

CHAMBER_GEO = {
    "senate": "state legislative district (upper chamber)",
    "house": "state legislative district (lower chamber)",
}

# PL 94-171 (2020 Census redistricting file) variables — see
# https://api.census.gov/data/2020/dec/pl/variables.html
PL94_171_VARS = {
    "P1_001N": "total_population",
    "P3_001N": "voting_age_population",
    "P2_002N": "hispanic_or_latino_population",
}

# A small illustrative ACS 5-year set — see
# https://api.census.gov/data/2022/acs/acs5/variables.html for the full list.
ACS_VARS = {
    "B01003_001E": "total_population_acs",
    "B19013_001E": "median_household_income",
    "B15003_022E": "bachelors_degree_count",
}


def _require_api_key() -> str:
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        raise RuntimeError(
            "CENSUS_API_KEY is not set. Sign up for a free key at "
            "https://api.census.gov/data/key_signup.html and export it "
            "as CENSUS_API_KEY before running this fetcher."
        )
    return key


def fetch_pl94_171(chamber: str, session=None) -> pd.DataFrame:
    """Total/voting-age population per district, current (2022-present)
    vintage only — see module docstring on why other vintages aren't here."""
    session = session or make_session(min_interval_s=0.5)
    key = _require_api_key()
    var_codes = list(PL94_171_VARS)
    url = "https://api.census.gov/data/2020/dec/pl"
    params = {
        "get": ",".join(["NAME", *var_codes]),
        "for": f"{CHAMBER_GEO[chamber]}:*",
        "in": f"state:{MA_FIPS}",
        "key": key,
    }
    resp = get(session, url, params=params)
    rows = resp.json()
    header, *data = rows
    df = pd.DataFrame(data, columns=header)
    df = df.rename(columns=PL94_171_VARS)
    for col in PL94_171_VARS.values():
        df[col] = pd.to_numeric(df[col])
    df["chamber"] = chamber
    df["vintage"] = "2022-present"
    df["source"] = "2020 Census PL 94-171"
    return df


def fetch_acs5(chamber: str, year: int, session=None) -> pd.DataFrame:
    session = session or make_session(min_interval_s=0.5)
    key = _require_api_key()
    var_codes = list(ACS_VARS)
    url = f"https://api.census.gov/data/{year}/acs/acs5"
    params = {
        "get": ",".join(["NAME", *var_codes]),
        "for": f"{CHAMBER_GEO[chamber]}:*",
        "in": f"state:{MA_FIPS}",
        "key": key,
    }
    resp = get(session, url, params=params)
    rows = resp.json()
    header, *data = rows
    df = pd.DataFrame(data, columns=header)
    df = df.rename(columns=ACS_VARS)
    for col in ACS_VARS.values():
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["chamber"] = chamber
    df["acs_year"] = year
    df["source"] = f"ACS 5-year {year}"
    return df


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option("--acs-year", type=int, default=2022, help="ACS 5-year vintage to pull.")
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/demographics"))
@click.option("-v", "--verbose", is_flag=True)
def main(chamber: str, acs_year: int, out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    out_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(min_interval_s=0.5)
    chambers = ["house", "senate"] if chamber == "both" else [chamber]

    for c in chambers:
        pl_df = fetch_pl94_171(c, session=session)
        pl_path = out_dir / f"{c}_pl94_171.parquet"
        pl_df.to_parquet(pl_path, index=False)
        logger.info("Wrote %d rows to %s", len(pl_df), pl_path)

        acs_df = fetch_acs5(c, acs_year, session=session)
        acs_path = out_dir / f"{c}_acs5_{acs_year}.parquet"
        acs_df.to_parquet(acs_path, index=False)
        logger.info("Wrote %d rows to %s", len(acs_df), acs_path)


if __name__ == "__main__":
    main()
