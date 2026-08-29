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
