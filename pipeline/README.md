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
  District boundaries — 2012-2020 and 2022-present from Census TIGER/Line,
  2001-2010 from MIT Libraries' GeoData Repository (see the module
  docstring for why, and for a naming trap in the MIT catalog worth reading
  before touching this again). Writes `<chamber>_<vintage>.geoparquet` to
  `--out-dir` (default `data/raw/boundaries`), all reprojected to a common
  CRS (EPSG:4269). Verified live for all three vintages: 40 Senate + 160-161
  House districts each, all valid geometries.

- `python -m ma_politics.fetch.towns --out-dir data/raw/boundaries`
  MA town/municipality boundaries from Census TIGER COUSUB — used for the
  town↔district crosswalk. A single current-vintage layer is used against
  all district vintages, since MA town boundaries are essentially static
  across the redistricting cycles this project covers (see module
  docstring). Writes `towns.geoparquet`. Verified live: 357 towns.

- `CENSUS_API_KEY=... python -m ma_politics.fetch.demographics --chamber both --acs-year 2022`
  District-level demographics (PL 94-171 total/voting-age population, ACS
  5-year income/education) from the Census API. **Requires a free API key**
  (https://api.census.gov/data/key_signup.html) — the API rejects every
  request without one now. Verified live end to end: 161 House + 40 Senate
  districts, MA's total population summing to ~7.03M. Writes
  `<chamber>_pl94_171.parquet` and
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
