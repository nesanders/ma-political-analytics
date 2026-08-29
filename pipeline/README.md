# Data pipeline

Python package (`ma_politics`) that fetches and transforms the raw data
behind the site. See `docs/PLAN.md` for the overall design; this covers
running it.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Fetchers (`ma_politics.fetch.*`)

Each fetcher is idempotent — safe to re-run; already-fetched records are
skipped, so re-running after a future election only pulls new rows.

- `python -m ma_politics.fetch.pd43 --chamber both --year-from 2002 --year-to 2024`
  Election results from PD43+ (electionstats.state.ma.us). Writes
  `<chamber>_races.parquet`, `<chamber>_results.parquet`,
  `<chamber>_town_results.parquet` to `--out-dir` (default `data/raw/pd43`).
  Polite by default (0.5s min spacing between requests, retries with
  backoff); a full multi-decade backfill across both chambers is thousands
  of requests and will take a while — run it in the background.

- `python -m ma_politics.fetch.district_boundaries --chamber both --vintage all`
  District boundaries from Census TIGER/Line (not MassGIS — see the module
  docstring for why). Writes `<chamber>_<vintage>.geoparquet` to `--out-dir`
  (default `data/raw/boundaries`). Only the 2012-2020 and 2022-present
  vintages are wired up; the 2001 vintage (2002-2010) isn't yet — see the
  module docstring and `docs/PLAN.md`'s network appendix.

- `CENSUS_API_KEY=... python -m ma_politics.fetch.demographics --chamber both --acs-year 2022`
  District-level demographics (PL 94-171 total/voting-age population, ACS
  5-year income/education) from the Census API. **Requires a free API key**
  (https://api.census.gov/data/key_signup.html) — the API rejects every
  request without one now. Written against the API's stable, documented
  format but not yet exercised against a live response (no key available
  in the environment this was built in) — verify against a small request
  before trusting a full run. Writes `<chamber>_pl94_171.parquet` and
  `<chamber>_acs5_<year>.parquet` to `--out-dir` (default
  `data/raw/demographics`). PL 94-171 only covers the current
  (2022-present) vintage — see the module docstring for why.

- `python -m ma_politics.fetch.campaign_finance --year-from 2002 --year-to 2024`
  Campaign finance from OCPF's public bulk export (no scraping, no key).
  Report/record-type handling (which report types double-count periodic
  totals, gross-vs-net amounts) is ported from and credited to Code for
  Boston's MAPLE project — see the module docstring. Writes `filers.parquet`
  (the full OCPF filer roster, all offices, active and closed) and
  `finance_summary.parquet` (total raised/spent per `cpf_id` per year) to
  `--out-dir` (default `data/raw/ocpf`). Verified live against 2024 data
  (10,162 filers, 2,012 with finance activity) and cross-checked against
  MAPLE's own validated example. Idempotent per year.
