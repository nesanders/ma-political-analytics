"""Fetch MA campaign finance data from OCPF's public bulk export.

OCPF (Office of Campaign and Political Finance) publishes real bulk data —
no scraping needed — at https://ocpf2.blob.core.windows.net/downloads/data2/:
`ocpf-filers.zip` (`all_filers.txt`: every filer, candidate committees
included, active and closed, back to the 1970s) and one
`ocpf-{year}-reports.zip` per year (`reports.txt` + `report-items.txt`),
confirmed available back to at least 2002.

The report/record-type handling below — which report types double-count
periodic totals, which carry gross vs. net amounts — is **ported from, and
credited to, Code for Boston's MAPLE project**
(https://github.com/codeforboston/maple, MIT licensed;
`functions/src/ocpf/scrapeOcpfFinance.ts`), whose comments document the
empirical verification behind each exclusion (e.g. summed Bank Report
totals matching a member's Year-End Report to the penny). We independently
confirmed the same file structure and column names live against 2024 data.

Adapted, not copied verbatim: MAPLE keys everything to a hand-curated
mapping of *currently-sitting* members' CPF IDs and produces a rich
per-member breakdown (small donors, in-kind, processing fees) for their
Finance tab UI. We only need enough for the WAR fundamentals baseline (see
docs/PLAN.md §4) — total raised/spent per candidate per year — and we need
it for *every* historical filer, not just current members, so we key
everything by `cpf_id` directly (matched to our own candidate records
later, in build_crosswalks.py) rather than a members-only mapping, and we
skip the parts of MAPLE's breakdown (small-donor counts, in-kind detail)
that only matter for a per-candidate finance-tab UI we're not building.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from pathlib import Path

import click
import pandas as pd

from ma_politics.util.http import get, make_session

logger = logging.getLogger(__name__)

BASE_URL = "https://ocpf2.blob.core.windows.net/downloads/data2"

# See scrapeOcpfFinance.ts for the empirical basis of each set below.
YEAR_END_REPORT_TYPE_IDS = {11, 24, 32, 36, 45, 52, 113}
LIFECYCLE_REPORT_TYPE_IDS = {12, 14, 15}
SUPPLEMENTAL_REPORT_TYPE_IDS = {80, 90}  # Credit Card, Reimbursement
DEPOSIT_REPORT_TYPE_ID = 60
BANK_REPORT_TYPE_ID = 70
NON_CONTRIBUTION_RECEIPT_RECORD_TYPE_ID = 204  # refunds/misc, netted from totalRaised


def _norm_headers(headers: list[str]) -> list[str]:
    return [h.strip().lower().replace(" ", "_") for h in headers]


def fetch_filers(session=None) -> pd.DataFrame:
    session = session or make_session(min_interval_s=0.5)
    resp = get(session, f"{BASE_URL}/ocpf-filers.zip")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        text = zf.read("all_filers.txt").decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    rows = list(reader)
    header = _norm_headers(rows[0])
    df = pd.DataFrame(rows[1:], columns=header)
    for col in df.columns:
        df[col] = df[col].str.strip().str.strip('"')
    df["cpf_id"] = pd.to_numeric(df["cpf_id"], errors="coerce")
    return df


def fetch_reports_and_items(year: int, session=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    session = session or make_session(min_interval_s=0.5)
    resp = get(session, f"{BASE_URL}/ocpf-{year}-reports.zip")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        reports_text = zf.read("reports.txt").decode("utf-8", errors="replace")
        items_text = zf.read("report-items.txt").decode("utf-8", errors="replace")

    reports_rows = list(csv.reader(io.StringIO(reports_text), delimiter="\t"))
    reports_header = _norm_headers(reports_rows[0])
    reports_df = pd.DataFrame(reports_rows[1:], columns=reports_header)
    for col in reports_df.columns:
        reports_df[col] = reports_df[col].str.strip().str.strip('"')

    items_rows = list(csv.reader(io.StringIO(items_text), delimiter="\t"))
    items_header = _norm_headers(items_rows[0])
    items_df = pd.DataFrame(items_rows[1:], columns=items_header)
    for col in items_df.columns:
        items_df[col] = items_df[col].str.strip().str.strip('"')

    return reports_df, items_df


def summarize_year(reports_df: pd.DataFrame, items_df: pd.DataFrame, year: int) -> pd.DataFrame:
    """One row per cpf_id: total_raised/total_spent for `year`, applying the
    same double-counting exclusions as MAPLE's scrapeOcpfFinance.ts."""
    r = reports_df.copy()
    for col in ("report_id", "cpf_id", "report_type_id"):
        r[col] = pd.to_numeric(r[col], errors="coerce")
    for col in ("receipts_total", "expenditures_total", "start_balance", "end_balance"):
        r[col] = pd.to_numeric(r[col], errors="coerce").fillna(0.0)

    # Non-contribution receipts (type 204) net out of totalRaised — compute
    # per report_id from report-items before excluding any reports below.
    it = items_df.copy()
    it["report_id"] = pd.to_numeric(it["report_id"], errors="coerce")
    it["record_type_id"] = pd.to_numeric(it["record_type_id"], errors="coerce")
    it["amount"] = pd.to_numeric(it["amount"], errors="coerce").fillna(0.0)
    non_contrib_by_report = (
        it[it["record_type_id"] == NON_CONTRIBUTION_RECEIPT_RECORD_TYPE_ID]
        .groupby("report_id")["amount"]
        .sum()
    )

    exclude_types = YEAR_END_REPORT_TYPE_IDS | LIFECYCLE_REPORT_TYPE_IDS | SUPPLEMENTAL_REPORT_TYPE_IDS
    countable = r[~r["report_type_id"].isin(exclude_types)].copy()

    # Deposit Reports (60) carry gross pre-fee amounts already reflected net
    # in Bank Reports (70) — exclude from totals, they're not double
    # counted only because we don't sum type-70 and type-60 both here.
    countable_totals = countable[countable["report_type_id"] != DEPOSIT_REPORT_TYPE_ID].copy()
    countable_totals["non_contrib"] = countable_totals["report_id"].map(non_contrib_by_report).fillna(0.0)
    countable_totals["receipts_net"] = countable_totals["receipts_total"] - countable_totals["non_contrib"]

    agg = countable_totals.groupby("cpf_id").agg(
        total_raised=("receipts_net", "sum"),
        total_spent=("expenditures_total", "sum"),
    )

    bank = r[r["report_type_id"] == BANK_REPORT_TYPE_ID].copy()
    bank["end_date_parsed"] = pd.to_datetime(bank["end_date"], errors="coerce")
    bank["start_date_parsed"] = pd.to_datetime(bank["start_date"], errors="coerce")
    latest_bank = bank.sort_values("end_date_parsed").groupby("cpf_id").tail(1)
    earliest_bank = bank.sort_values("start_date_parsed").groupby("cpf_id").head(1)
    cash_on_hand = latest_bank.set_index("cpf_id")["end_balance"]
    start_balance = earliest_bank.set_index("cpf_id")["start_balance"]

    # Office/district/name are embedded per-report (OCPF_Office etc.) —
    # take them from whichever report is most recent for that cpf_id.
    meta_cols = [c for c in r.columns if c.startswith("ocpf_")]
    meta = r.sort_values("filing_date").groupby("cpf_id")[meta_cols].last() if meta_cols else pd.DataFrame()

    out = agg.join(cash_on_hand.rename("cash_on_hand")).join(start_balance.rename("start_balance"))
    if not meta.empty:
        out = out.join(meta)
    out["year"] = year
    return out.reset_index()


@click.command()
@click.option("--year-from", type=int, default=2002)
@click.option("--year-to", type=int, default=2024)
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("data/raw/ocpf"))
@click.option("-v", "--verbose", is_flag=True)
def main(year_from: int, year_to: int, out_dir: Path, verbose: bool):
    """Fetch OCPF filers roster + per-year finance summaries.

    Idempotent per year: skips years already present in
    <out-dir>/finance_summary.parquet.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    out_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(min_interval_s=0.5)

    filers_df = fetch_filers(session=session)
    filers_path = out_dir / "filers.parquet"
    filers_df.to_parquet(filers_path, index=False)
    logger.info("Wrote %d filers to %s", len(filers_df), filers_path)

    summary_path = out_dir / "finance_summary.parquet"
    existing_years: set[int] = set()
    if summary_path.exists():
        existing_years = set(pd.read_parquet(summary_path)["year"].unique())

    new_summaries = []
    for year in range(year_from, year_to + 1):
        if year in existing_years:
            continue
        reports_df, items_df = fetch_reports_and_items(year, session=session)
        summary = summarize_year(reports_df, items_df, year)
        logger.info("%d: %d filers with finance activity", year, len(summary))
        new_summaries.append(summary)

    if not new_summaries:
        logger.info("Nothing new to fetch.")
        return

    combined = pd.concat(new_summaries, ignore_index=True)
    if summary_path.exists():
        combined = pd.concat([pd.read_parquet(summary_path), combined], ignore_index=True)
    combined.to_parquet(summary_path, index=False)
    logger.info("Wrote %d total rows to %s", len(combined), summary_path)


if __name__ == "__main__":
    main()
