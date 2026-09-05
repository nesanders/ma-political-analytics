"""Fetch presidential job approval near each even-year MA general election
(2002-2024), from The American Presidency Project (UCSB) — the same Gallup
approval series (plus, since Gallup discontinued the question, AP-NORC/
CNN-SSRS/Marist/Verasight/Pew, per that site's own sourcing note) political
scientists and journalists cite for exactly this "national fundamentals"
purpose. Confirmed live (2026-09): the project's own site is a plain
server-rendered Drupal page, not a JS app — despite a large New Relic
monitoring bundle in its <head> that looks like a SPA shell at a glance, the
actual per-president approval table is already in the HTML `curl` returns,
parseable directly with `pandas.read_html`. One page per president, e.g.
https://www.presidency.ucsb.edu/statistics/data/george-w-bush-public-approval
— found via following /data/popularity.php?pres=45's redirect (an old,
still-live URL alias) to the modern /statistics/data/... path, since the
project's own "all data" landing page just links out to per-president pages
rather than serving one combined table.

This site's own general-election model already has a state-level "tide"
term (the statewide two-party baseline race's own result, see
generate_site_data.compute_statewide_tide_by_year) — approval is a
genuinely different signal: the *national* political environment, not
Massachusetts' own. Distinguishing the two lets the regression ask whether
a bad national approval rating drags down a state's own down-ballot races
beyond what the state's own baseline race already captures.

One row per MA general-election year: the specific poll (Start Date/End
Date/Approving) whose window ends closest to, but not after, that year's
actual Election Day (first Tuesday after the first Monday in November,
computed rather than hardcoded) — the poll's approval reading is what was
actually public knowledge heading into that election, not a full-year
average that would blend in post-election polling no voter had seen yet.
Falls back to the single nearest poll by absolute date distance only if
none exists on or before Election Day (not hit for any of this project's
2002-2024 range, all four presidencies poll far more often than once a
year), logged loudly rather than silently, since it would mean this
citation's own polling record has a real gap.
"""

from __future__ import annotations

import datetime
import io
import logging
import re
from pathlib import Path

import click
import pandas as pd

from ma_politics.util.http import get, make_session

logger = logging.getLogger(__name__)

BASE_URL = "https://www.presidency.ucsb.edu/statistics/data"

# year -> (president's own approval-data page slug, party) — MA's even-year
# general elections always fall within exactly one president's term
# (confirmed against each term's real start/end dates), so there's no
# ambiguity to resolve. Party is plain historical fact (not something that
# needs live sourcing the way the approval *numbers* do), used downstream
# to sign-flip approval onto each candidate's own party the same way
# generate_site_data.py's own statewide-tide term already does.
_PRESIDENT_BY_YEAR = {
    2002: ("george-w-bush-public-approval", "Republican"),
    2004: ("george-w-bush-public-approval", "Republican"),
    2006: ("george-w-bush-public-approval", "Republican"),
    2008: ("george-w-bush-public-approval", "Republican"),
    2010: ("barack-obama-public-approval", "Democratic"),
    2012: ("barack-obama-public-approval", "Democratic"),
    2014: ("barack-obama-public-approval", "Democratic"),
    2016: ("barack-obama-public-approval", "Democratic"),
    2018: ("donald-j-trump-public-approval", "Republican"),
    2020: ("donald-j-trump-public-approval", "Republican"),
    2022: ("joseph-r-biden-public-approval", "Democratic"),
    2024: ("joseph-r-biden-public-approval", "Democratic"),
}


def election_day(year: int) -> datetime.date:
    """First Tuesday after the first Monday in November — federal law (2
    U.S.C. § 7), computed rather than hardcoded so this stays correct for
    any year without a lookup table. Verified against the two real dates
    this project's own OCPF/PD43+ backfill already spans: 2022 -> Nov 8,
    2024 -> Nov 5."""
    nov1 = datetime.date(year, 11, 1)
    days_to_monday = (7 - nov1.weekday()) % 7  # Monday.weekday() == 0
    first_monday = nov1 + datetime.timedelta(days=days_to_monday)
    return first_monday + datetime.timedelta(days=1)


_TRUNCATED_YEAR_RE = re.compile(r"^(\d{1,2}/\d{1,2}/)(2\d{2})$")


def _fix_truncated_year(date_str: str) -> str:
    """A real, live data-entry typo found in this source (Biden's own
    page): a handful of dates read like "2/20/224" instead of "2/20/2024"
    — a dropped "0" right after the century digit, not a parsing
    ambiguity. Recognized (2-3 digit month/day, then a 3-digit "2xx" year
    that's otherwise unparseable as a real date) and repaired by
    reinserting the "0", logged rather than silently guessed at, since a
    truncated year could in principle mean something else."""
    m = _TRUNCATED_YEAR_RE.match(date_str)
    if not m:
        return date_str
    fixed = f"{m.group(1)}20{m.group(2)[1:]}"
    logger.warning("Repaired truncated year in date %r -> %r", date_str, fixed)
    return fixed


def _parse_approval_table(html: str) -> pd.DataFrame:
    # Most president pages have exactly one <table> (the approval series
    # itself); Biden's page also carries a second, small footnote-style
    # table with plain integer column labels — found live, not assumed —
    # so the real one is picked by its actual column names rather than by
    # position.
    tables = [t for t in pd.read_html(io.StringIO(html)) if "Start Date" in t.columns]
    if len(tables) != 1:
        raise ValueError(f"Expected exactly one approval table, found {len(tables)}")
    table = tables[0].dropna(subset=["Start Date", "End Date", "Approving"])
    table["start_date"] = pd.to_datetime(table["Start Date"].map(_fix_truncated_year), format="%m/%d/%Y")
    table["end_date"] = pd.to_datetime(table["End Date"].map(_fix_truncated_year), format="%m/%d/%Y")
    table["approving"] = pd.to_numeric(table["Approving"])
    return table[["start_date", "end_date", "approving"]].sort_values("end_date").reset_index(drop=True)


def fetch_approval_by_year(year_from: int = 2002, year_to: int = 2024, session=None) -> pd.DataFrame:
    session = session or make_session(min_interval_s=1.0)
    pages: dict[str, pd.DataFrame] = {}
    rows = []
    for year in range(year_from, year_to + 1):
        if year % 2 != 0 or year not in _PRESIDENT_BY_YEAR:
            continue  # MA general elections are even years only
        page, party = _PRESIDENT_BY_YEAR[year]
        if page not in pages:
            resp = get(session, f"{BASE_URL}/{page}")
            pages[page] = _parse_approval_table(resp.text)
            logger.info("Fetched %d polls from %s", len(pages[page]), page)

        table = pages[page]
        eday = pd.Timestamp(election_day(year))
        on_or_before = table[table["end_date"] <= eday]
        if len(on_or_before):
            poll = on_or_before.iloc[-1]
        else:
            logger.warning("No poll on/before Election Day %s for %s — using nearest by date instead", eday.date(), page)
            poll = table.iloc[(table["end_date"] - eday).abs().argsort().iloc[0]]

        rows.append(
            {
                "year": year,
                "election_day": eday.date().isoformat(),
                "source_page": page,
                "president_party": party,
                "poll_start_date": poll["start_date"].date().isoformat(),
                "poll_end_date": poll["end_date"].date().isoformat(),
                "approving": float(poll["approving"]),
            }
        )
    return pd.DataFrame(rows)


@click.command()
@click.option("--year-from", type=int, default=2002)
@click.option("--year-to", type=int, default=2024)
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/presidential_approval"))
@click.option("-v", "--verbose", is_flag=True)
def main(year_from: int, year_to: int, out_dir: Path, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    out_dir.mkdir(parents=True, exist_ok=True)
    df = fetch_approval_by_year(year_from, year_to)
    path = out_dir / "approval_by_year.parquet"
    df.to_parquet(path, index=False)
    logger.info("Wrote %d rows to %s", len(df), path)


if __name__ == "__main__":
    main()
