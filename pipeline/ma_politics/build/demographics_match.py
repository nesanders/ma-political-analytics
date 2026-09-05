"""Matches this site's own districts to Census demographics (PL 94-171
redistricting data + ACS 5-year estimates) fetched by fetch.demographics
— see that module's docstring for why this only covers the current
(2022-present) vintage: PL 94-171 is only published against current
district boundaries, and this project's own ACS pull uses the same.

Matching reuses derived_metrics.match_district_names() rather than a
separate normalization pass: once each Census district name's trailing
"(2018), Massachusetts"-style suffix is stripped, the same ordinal/
punctuation drift problem PD43+ names have against boundary names shows
up here too, and match_district_names() already handles it. 158 of 160
House districts matched by exact name alone after stripping the suffix;
the fuzzy fallback in match_district_names() closes the rest.

A real, known Census ACS gotcha handled here: suppressed/unavailable
estimates are encoded as a sentinel (-666666666), not a null — found live
in this project's own fetched data (one district's median household
income). Left out entirely rather than published as a wildly wrong number.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from ma_politics.build.derived_metrics import match_district_names

logger = logging.getLogger(__name__)

_NAME_SUFFIX_RE = re.compile(r"\s*\(\d{4}\),?\s*Massachusetts\s*$")
_ACS_SUPPRESSED_SENTINEL = -666666666


def _clean_census_name(name: str) -> str:
    return _NAME_SUFFIX_RE.sub("", str(name)).strip()


def load_demographics(chamber: str, demographics_dir: Path, district_names: list[str]) -> dict[str, dict]:
    """district_names: this chamber's own current-vintage district names
    (the match target). Returns {district_name: {...}} for every district
    matched to at least one of PL 94-171 / ACS — missing either source
    (not fetched) is handled gracefully, not an error."""
    pl_path = demographics_dir / f"{chamber}_pl94_171.parquet"
    acs_path = demographics_dir / f"{chamber}_acs5_2022.parquet"
    if not pl_path.exists() and not acs_path.exists():
        return {}

    result: dict[str, dict] = {}

    if pl_path.exists():
        pl = pd.read_parquet(pl_path)
        pl["clean_name"] = pl["NAME"].map(_clean_census_name)
        pl = pl[~pl["clean_name"].str.contains("not defined", case=False, na=False)]
        name_match = match_district_names(sorted(pl["clean_name"].unique()), district_names)
        pl["district_name"] = pl["clean_name"].map(name_match)
        for _, row in pl.dropna(subset=["district_name"]).iterrows():
            result[row["district_name"]] = {
                "total_population": int(row["total_population"]),
                "voting_age_population": int(row["voting_age_population"]),
                "hispanic_or_latino_population": int(row["hispanic_or_latino_population"]),
            }

    if acs_path.exists():
        acs = pd.read_parquet(acs_path)
        acs["clean_name"] = acs["NAME"].map(_clean_census_name)
        acs = acs[~acs["clean_name"].str.contains("not defined", case=False, na=False)]
        name_match = match_district_names(sorted(acs["clean_name"].unique()), district_names)
        acs["district_name"] = acs["clean_name"].map(name_match)
        for _, row in acs.dropna(subset=["district_name"]).iterrows():
            entry = result.setdefault(row["district_name"], {})
            income = row["median_household_income"]
            entry["median_household_income"] = (
                int(income) if pd.notna(income) and int(income) != _ACS_SUPPRESSED_SENTINEL else None
            )
            entry["bachelors_degree_count"] = int(row["bachelors_degree_count"]) if pd.notna(row["bachelors_degree_count"]) else None
            entry["median_age"] = float(row["median_age"]) if pd.notna(row["median_age"]) else None
            entry["occupied_housing_units"] = int(row["occupied_housing_units"]) if pd.notna(row["occupied_housing_units"]) else None
            entry["owner_occupied_housing_units"] = (
                int(row["owner_occupied_housing_units"]) if pd.notna(row["owner_occupied_housing_units"]) else None
            )
            entry["total_population_race"] = int(row["total_population_race"]) if pd.notna(row["total_population_race"]) else None
            entry["white_alone_not_hispanic_population"] = (
                int(row["white_alone_not_hispanic_population"]) if pd.notna(row["white_alone_not_hispanic_population"]) else None
            )
            # Fetched but previously dropped on the floor here: a fallback
            # population denominator for districts PL 94-171 failed to
            # match (its own name-matching runs independently of ACS's —
            # a real, live gap, not hypothetical: 15 of 200 current-vintage
            # districts, all Senate seats, have ACS income/education but no
            # PL 94-171 match at all). Lets bachelors_pct still be computed
            # for those districts instead of losing them entirely — see
            # generate_site_data._demographic_covariates' population
            # fallback.
            pop_acs = row["total_population_acs"]
            entry["total_population_acs"] = int(pop_acs) if pd.notna(pop_acs) else None
            entry["acs_year"] = int(row["acs_year"])

    return result
