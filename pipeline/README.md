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

## Build steps (`ma_politics.build.*`)

Run after the fetchers above have populated `data/raw/`. Not idempotent in
the same incremental sense as the fetchers — cheap enough to just re-run in
full.

- `python -m ma_politics.build.crosswalks --boundaries-dir data/raw/boundaries --out-dir data/interim/crosswalks`
  Town↔district area-overlap and cross-vintage seat lineage, both from pure
  geometry (no PD43+ name-matching involved — see module docstring for why
  that's a separate step). Writes `town_district_overlap.parquet` and
  `seat_lineage.parquet`. Verified live against the real fetched boundaries:
  every district's town-overlap shares sum to ~1.0 (min 0.998) for all three
  vintages/both chambers, and seat lineage produces sensible continuity
  (e.g. 2001's 1st Barnstable maps 83% into 2012's 1st Barnstable District).

- `python -m ma_politics.build.derived_metrics --chamber house --year 2022 --vintage 2022-present`
  District partisan lean, competitiveness, and WAR (see module docstring
  for the full pipeline and a documented limitation around uncontested
  races). Needs a statewide baseline race already fetched via
  `fetch.pd43`'s `governor`/`president` office (not exposed on that
  module's CLI — call `fetch_years("governor", ...)` directly, see its
  docstring) into `--baseline-dir` (default `data/raw/pd43_statewide`).
  Writes `<chamber>_<vintage>_lean.parquet` and `<chamber>_<year>_war.parquet`
  to `--out-dir` (default `data/interim/derived_metrics`). Verified live
  against real 2022 data for both chambers: apportioned statewide vote
  share reconstructs the true Governor result exactly (0.0pp difference);
  competitiveness matches MA's known partisan lean (27/40 Senate seats
  Safe D); all 160 House + 40 Senate district names matched with zero
  mismatches in either direction (checked both ways) after fixing a real
  wrong-match bug found in the process — see the commit history for
  `derived_metrics.py` for what that was and how it was caught.

- `python -m ma_politics.build.generate_site_data --chamber both --year 2022 --vintage 2022-present`
  Emits one Markdown-with-YAML-frontmatter file per seat (`--seats-out-dir`,
  default `site/_seats`) and per candidate (`--candidates-out-dir`, default
  `site/_candidates`) — Jekyll's own collection mechanism renders these via
  `site/_layouts/seat.html`/`candidate.html`, no separate HTML generator
  needed (see docs/PLAN.md §7). Candidates are keyed by PD43+'s own
  candidate slug (lowercased), not a name re-derived one, to avoid
  collisions between different candidates with similar names; a candidate
  who ran in both chambers the same year (rare, but possible, unlike two
  different people sharing a slug) gets one merged record rather than two
  that would silently overwrite each other. **This is committed site
  content, not a build artifact** — unlike `data/raw`/`data/interim`
  (gitignored), the pipeline is meant to be run manually/periodically per
  the project's requirements, with its output checked in so GitHub Actions'
  Jekyll build (which only runs Jekyll, not Python) has something to
  render. Verified end to end: ran a real `bundle exec jekyll build`
  against the 200 seat + 282 candidate pages, inspected several rendered
  HTML pages including the actual link chain from a seat page's candidate
  link through to that candidate's own page — all correct, including two
  real bugs caught by that inspection: a Liquid filter-chaining bug
  (candidate links were slugifying the whole `/candidate/Name` path instead
  of just the name) and a missing `year` column that only surfaced once
  candidate pages tried to sort by it (the WAR table doesn't carry year as
  a column; it's implicit in the per-year file). A later run also caught a
  real data-serialization bug: a candidate with no parseable party (PD43+
  occasionally has one) came through as a stray float NaN rather than a
  proper null, which crashed Jekyll's `jsonify` filter outright ("NaN not
  allowed in JSON") — fixed by coercing explicitly to `None` before writing
  YAML (`_clean_str` in the module).

## Site chart assets (`site/assets/js/vendor/`)

Vega/Vega-Lite/Vega-Embed, used by `site/_layouts/chamber.html`'s
district-lean chart, are vendored rather than loaded from a CDN — installed
via `npm install vega@5 vega-lite@5 vega-embed@6` and their UMD `.min.js`
builds copied in directly (no bundler yet). Verified live with an actual
headless-browser session (Playwright): the chart renders with real data,
and clicking a point navigates to that seat's page. That verification also
caught a real CSS bug — vega-embed's own stylesheet sets `display:
inline-block` on its container, which collapses to zero width when
combined with a chart spec's `"width": "container"` autosize; fixed with
an explicit override in `site/assets/css/main.css` (`display: block;
width: 100%` on `.vega-embed`).
