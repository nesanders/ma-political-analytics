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
  Writes `<chamber>_<vintage>_<year>_lean.parquet` and
  `<chamber>_<year>_war.parquet` to `--out-dir` (default
  `data/interim/derived_metrics`) — lean is year-scoped in its filename,
  not just vintage-scoped, since it's recomputed against a different
  statewide baseline race every cycle; a vintage spans several election
  years (e.g. 2022-present covers both 2022 and 2024), and a shared
  filename would have one year's run silently overwrite another's. Also
  computes `turnout_ratio` per race (two-party vote total over the
  district's apportioned two-party baseline-race total — see the
  methodology page for the full definition and its caveats); incumbency
  is computed downstream in `generate_site_data.py`, not here, since it
  needs multiple years' results at once, which this module (one
  chamber/year/vintage per invocation) doesn't have.
  Verified live
  against real 2022 data for both chambers: apportioned statewide vote
  share reconstructs the true Governor result exactly (0.0pp difference);
  competitiveness matches MA's known partisan lean (27/40 Senate seats
  Safe D); all 160 House + 40 Senate district names matched with zero
  mismatches in either direction (checked both ways) after fixing a real
  wrong-match bug found in the process — see the commit history for
  `derived_metrics.py` for what that was and how it was caught.

- `python -m ma_politics.build.generate_site_data --chamber both --current-vintage 2022-present --vintages 2001-2010,2012-2020,2022-present`
  Emits one Markdown-with-YAML-frontmatter file per district, seat,
  candidate, town, and party (`--districts-out-dir`/`--seats-out-dir`/
  `--candidates-out-dir`/`--towns-out-dir`/`--parties-out-dir`, defaulting
  to `site/_districts`/`_seats`/`_candidates`/`_towns`/`_parties`) —
  Jekyll's own collection mechanism renders these via one Liquid layout per
  type, no separate HTML generator needed (see docs/PLAN.md §7).

  **Two-tier district/seat model**, added for the multi-decade backfill
  (a single year's snapshot per seat, the original design, doesn't survive
  more than one year of data without overwriting itself): a **district**
  (`/district/...`) is scoped to one (chamber, district_name, vintage) and
  accumulates every election year available within that vintage — which
  years exist is *discovered* from the year-scoped lean filenames on disk
  (`discover_years()`), not a hardcoded list, so backfilling more years and
  re-running this script is all that's needed to pick them up. A **seat**
  (`/seat/...`) is the *current* vintage's district record plus a
  `history` list walking backward through `build.crosswalks`' seat_lineage
  (best area-overlap predecessor, however many vintage hops that reaches —
  currently up to two) to the districts it evolved from, each with a link
  to that district's own page. This matches the two-tier
  `/seat/{chamber}/{district}/` (persistent, vintage-switching) vs.
  `/district/{chamber}/{district}/{vintage}/` (vintage-specific) split
  docs/PLAN.md always specified in §7, just not built until now.

  **Incumbency and open-seat status** are also computed here, once
  `results_by_year` is fully assembled for a district: a candidate is
  `is_incumbent` if they won that same district's immediately preceding
  election *within the same vintage* (deliberately not chased across a
  redistricting boundary via seat_lineage — that link is an area-overlap
  best guess, not a confirmed identity; see the methodology page), and a
  year's `is_open_seat` is true when the prior winner isn't among that
  year's candidates. Both stay `None`/unknown rather than a guessed value
  when there's no prior year to compare against at all — a district's
  first election on record isn't a confirmed open seat, it's an unknown.
  Verified with a synthetic two-year test (temporarily duplicating 2022's
  already-fetched data under a second, fake year) before waiting on the
  real backfill: same winner across both years correctly flips
  `is_incumbent` to true and `is_open_seat` to false for the later year,
  and a from-scratch year correctly leaves both at their "unknown"
  defaults.

  Candidates are keyed by PD43+'s own candidate slug (lowercased), not a
  name re-derived one, to avoid collisions between different candidates
  with similar names; every race a candidate ran across every year and
  chamber this run has data for is now built in a single pass over all
  years at once (not one CLI invocation per year, which — like the old
  single-year seat design — would have silently overwritten each
  candidate's file with only that run's year on every subsequent run).

  Also matches candidates to **OCPF campaign-finance** data (`--ocpf-dir`,
  default `data/raw/ocpf` — skipped with a warning, not an error, if
  missing) via `ma_politics.build.campaign_finance_match`: a real matching
  problem, not a join, since OCPF's filer roster carries no PD43+
  candidate identifier and names don't always agree exactly (OCPF's own
  roster had "Nick Boldyga" where PD43+'s ballot name is "Nicholas A.
  Boldyga" — found checking a real case). Matched on last name + district +
  chamber against every race a candidate is known to have run, deliberately
  not first name — that combination is already a strong enough constraint
  that nickname/initial variation doesn't need to factor in, and this
  design errs toward a missing match over a wrong one. Verified live: 210
  of 282 real 2022 candidates matched; the top matched fundraiser is Aaron
  M. Michlewitz (House Ways & Means chair) at $471,692.12 raised and
  Ronald Mariano (House Speaker) second at $202,496.28 — both real,
  sensible results for who'd actually raise the most. Caught and fixed a
  real bug in the process: PD43+ appends " (W)" to write-in candidates'
  names, which the naive last-name extraction was grabbing as the surname
  itself before this was found and excluded.

  Also matches districts to **Census demographics** (`--demographics-dir`,
  default `data/raw/demographics` — skipped, not an error, if missing) via
  `ma_politics.build.demographics_match`: 2020 Census PL 94-171
  (population, voting-age population, Hispanic/Latino population) and ACS
  5-year 2022 (median household income, bachelor's-degree-or-higher count),
  matched to this site's own district names after stripping Census's
  trailing `"(YYYY), Massachusetts"` suffix, reusing
  `derived_metrics.match_district_names()` rather than a second fuzzy
  matcher. Only ever populates the *current* (2022-present) vintage — see
  `demographics_match.py`'s module docstring for why (PL 94-171 is only
  published against current district boundaries). Verified live: House
  matched 159 of 160 districts (the one miss, 19th Worcester District,
  simply has no corresponding entry in Census's own house district list —
  a genuine data gap, not a matching bug); Senate matched 26 of 40 (a real,
  larger gap — Census's Senate district names diverge more from PD43+'s,
  e.g. "Second Hampden & Hampshire District" vs. this site's "Hampden and
  Hampshire District", an ordinal-prefix-plus-wording difference beyond
  what the existing ordinal-number-guarded fuzzy matcher resolves).
  Accepted as a documented limitation rather than building further
  matching sophistication, consistent with the missing-over-wrong-match
  philosophy above. Also caught a real Census API convention live: ACS
  encodes suppressed/unavailable estimates as the sentinel `-666666666`,
  not a null — found in one district's real fetched median household
  income and excluded explicitly rather than published as a wildly wrong
  number.

  **This is committed site content, not a build artifact** — unlike
  `data/raw`/`data/interim` (gitignored), the pipeline is meant to be run
  manually/periodically per the project's requirements, with its output
  checked in so GitHub Actions' Jekyll build (which only runs Jekyll, not
  Python) has something to render. Verified end to end: ran a real `bundle
  exec jekyll build` against the 200 seat + 200 district + 282 candidate +
  351 town + 3 party pages (still 2022-only at the time of this note — see
  below for the in-progress multi-decade backfill), inspected several
  rendered HTML pages including the actual link chain from a seat page's
  candidate link through to that candidate's own page, a seat's "Before
  redistricting" history section correctly walking back through two prior
  vintages by lineage (a real district's 2022-present name matching its
  2012-2020 name exactly, then diverging slightly in 2001-2010 — a real,
  correctly-surfaced naming change, not a bug), and the four new top-level
  index pages (`/district/`, `/candidate/`, `/town/`, `/party/`) all
  listing the expected row counts with working click-through — all
  correct, including two real bugs caught by that inspection: a Liquid
  filter-chaining bug (candidate links were slugifying the whole
  `/candidate/Name` path instead of just the name) and a missing `year`
  column that only surfaced once candidate pages tried to sort by it (the
  WAR table doesn't carry year as a column; it's implicit in the per-year
  file). A later run also caught a real data-serialization bug: a
  candidate with no parseable party (PD43+ occasionally has one) came
  through as a stray float NaN rather than a proper null, which crashed
  Jekyll's `jsonify` filter outright ("NaN not allowed in JSON") — fixed
  by coercing explicitly to `None` before writing
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

- `python -m ma_politics.build.publish_query_data --chamber both --vintages 2001-2010,2012-2020,2022-present`
  Publishes flat, SQL-queryable Parquet tables (`seats.parquet`,
  `results.parquet`, `towns.parquet`, `finance.parquet`) plus a JSON schema card
  (`site/assets/data/schema.json`) for the AskAI feature's client-side
  DuckDB-Wasm instance — see docs/PLAN.md §8. Same underlying numbers as
  `generate_site_data.py`'s per-entity pages, reshaped flat for SQL instead
  of nested per-entity documents; takes a list of vintages rather than one
  fixed year/vintage pair for the same reason `generate_site_data.py`
  does — years actually present are discovered per vintage from what
  `derived_metrics.py` has written, not assumed. Its `seats`/`results`
  table builders now call `generate_site_data.build_district_records()`
  directly instead of re-reading the lean/WAR parquet in a second,
  parallel pass — the same records the Jekyll pages render, so this
  table (and by extension AskAI's answers) can't drift from what the
  site itself shows, and `turnout_ratio`/`is_incumbent` are picked up for
  free rather than needing their own separate computation here.
  `seats.parquet` also carries the same Census demographics columns as the
  district/seat pages (`total_population`, `voting_age_population`,
  `hispanic_or_latino_population`, `median_household_income`,
  `bachelors_degree_count`), matched via `demographics_match.py` once per
  (chamber, vintage) and repeated onto every year's row for a district
  since Census figures don't vary by election year the way this table's
  grain does — null outside the current vintage and for the districts
  `demographics_match.py` couldn't match (see above). Verified
  live: loaded the actual published files with DuckDB's Python bindings
  and ran all six of the schema card's own example queries (including
  the turnout/incumbency ones and a new income-vs-lean one) against them —
  correct results, including one that reproduces an earlier-verified
  figure exactly (Jeffrey L. Raymond's 2022 House WAR of 0.6017).

- `python -m ma_politics.build.publish_district_geo --chamber both --vintages 2001-2010,2012-2020,2022-present`
  Publishes one small GeoJSON file per (chamber, district_name, vintage) to
  `site/assets/data/geo/` for the district map (`site/_layouts/district.html`
  and `seat.html`, via `site/assets/js/district-map.js`) — see docs/PLAN.md
  §6. Reuses `build.crosswalks`' `load_district_vintage()` for the
  (district_id, district_name, geometry) roster, and `generate_site_data.py`'s
  `district_slug()` for the output filename, rather than re-deriving either,
  so a district page's `geo_slug` front-matter field always resolves to a
  file that actually exists. Geometry is reprojected to EPSG:4326 (the
  source files are EPSG:4269/NAD83) and simplified (~11m tolerance at MA's
  latitude), which cut per-file size by roughly 80% (31KB -> 6KB for a
  representative district) with no visible loss at the zoom levels a
  single-district map renders at — measured, not assumed, before picking
  that tolerance. 602 files, 7.6MB total, verified live: every district
  page's map fetches and renders its own file (not another district's) as
  a MapLibre GeoJSON fill/outline layer, colored by which party the seat's
  lean favors. The basemap underneath (CARTO's free raster tiles, no API
  key) is a separate concern from the district polygon itself and is
  **not verified live from this environment** — this session's network
  policy blocks `basemaps.cartocdn.com` the same way it blocks jsDelivr
  for AskAI's DuckDB-Wasm bundles (see `site/src/askai/src/duckdb.ts`).
  What's confirmed instead: the district polygon still renders correctly
  (screenshotted) with the basemap tiles failing to load, since it's added
  as its own MapLibre layer independent of the basemap source's own
  load success — real end-user browsers reach the CDN directly.

  The same command also writes one **combined** FeatureCollection per
  (chamber, vintage) — `<chamber>-<vintage>-all.geojson`, every district's
  geometry plus its lean/competitiveness/URL in one file — for the
  statewide overview map (`site/map/`, via `site/assets/js/statewide-map.js`).
  A district with geometry but no results data yet (derived_metrics.py
  hasn't run for any year in that vintage) is skipped rather than shown
  colorless. Verified live: real Massachusetts geography renders (the
  outline is unmistakable), Republican-leaning districts cluster correctly
  in western MA and south of Boston matching the state's actual political
  geography, and `queryRenderedFeatures` at the canvas center returns a
  real district (18th Worcester District, Lean R) with all its properties
  intact. Caught and fixed a real bug via an actual click-through test —
  the district `url` each feature carries is a site-root-relative path
  computed in Python (`district_url()`) with no knowledge of Jekyll's
  `site.baseurl`, and the click handler was using it directly; navigating
  landed on `/district/...` (a 404 on this deployment) instead of
  `/ma-political-analytics/district/...`. Fixed by reading the same
  `data-site-baseurl` attribute default.html already stashes on `<body>`
  for AskAI (renamed from `data-askai-baseurl`, since it's page-wide
  infrastructure now, not AskAI-specific) and prefixing the URL with it
  before navigating — re-verified live, lands on the real district page.

## AskAI sidebar (`site/src/askai/`)

React app (query_data + render_chart tools, BYOK settings, a manual
`streamText`-driven chat loop — see docs/PLAN.md §8) built with esbuild into
`site/assets/js/askai.bundle.js`, which is committed like the other build
outputs under `site/`, since the deploy workflow only runs Jekyll, not npm.
Rebuild with `npm install && npm run build` inside `site/src/askai/` after
changing anything under `src/`.

What's verified live, and how:
- `assertSafeSelect()` (the SQL guard) and real DuckDB query execution
  against the real published parquet: `scripts/verify_query_guard.mjs`,
  via `@duckdb/duckdb-wasm`'s Node bindings — see the script's own comment
  for what it does and doesn't cover (the browser-only jsDelivr and
  extensions.duckdb.org CDN dependencies aren't reachable from this
  session's network policy).
- The sidebar UI end-to-end in a real headless browser (Playwright): toggle
  open/close, Settings panel, per-provider API key persisted separately in
  `localStorage`, sending a message with no key blocked with the expected
  inline error, and sending a message *with* a key driving `getModel()` →
  `streamText()` all the way to a real `fetch()` attempt against
  `api.anthropic.com` — which fails in this sandbox (network policy /
  invalid test key) but surfaces correctly as an inline error banner rather
  than hanging or crashing. The actual LLM round-trip (a real model
  response, a real tool call being executed and rendered) is **not**
  verified — this session has no provider API key and can't reach any
  provider's API host.
- That same browser pass caught and fixed two real bugs: (1) the floating
  toggle button's `z-index` sat above the open panel and intercepted clicks
  on the input row — fixed by moving "Close" into the panel header instead
  of leaving a floating button overlapping the panel; (2) a much more
  serious one — see "the chamber-page fetch storm" below.

### The chamber-page fetch storm

Loading Vega site-wide (`default.html`, needed so `render_chart` can draw a
chart on any page) turned a pre-existing latent landmine in
`chamber.html` into a real, live bug: `{{ seats | jsonify }}` serializes
*all* of a Jekyll Document's properties, including its fully rendered HTML
`output` — so each seat's own `<script src="...vega...">` tags ended up
embedded inside chamber.html's own `<script>` block as a JSON string. HTML
tag parsing doesn't respect JS string boundaries, so the browser's
tokenizer closed that script element early at the first embedded closing
tag and re-parsed the rest as live markup — actually fetching and running
those embedded tags. Caught live: a real browser test showed hundreds of
malformed repeated requests for the vendor Vega files on a single page
load. Fixed by building the chart's data array field-by-field in Liquid
instead of jsonify-ing the whole Document (`chamber.html`) — confirmed
fixed live (exactly 3 requests, chart still renders with real data,
click-through to a seat page still works). One more round: the first fix's
own explanatory comment described the bug by literally spelling out a
closing script tag, reproducing the exact same failure from inside the
comment — a reminder that this class of bug is triggered by the literal
character sequence appearing anywhere in a `<script>` block, comments
included, not by "real" versus "string" content.

## Site polish (sortable tables, methodology page)

- `site/assets/js/sortable-tables.js`: a small vanilla-JS utility (no
  framework, plain `<script>` tag like the chart-building scripts already
  inline elsewhere) that makes every `<table>` inside `<main>` sortable by
  clicking a column header — scoped to `<main>` specifically so it doesn't
  touch AskAI's own dynamically-inserted query-result tables in the
  sidebar. Numeric-aware: strips `%`/`,` before comparing, so percentage
  and vote-count columns sort as numbers, not lexicographically (which
  would otherwise put "9" after "10"). Verified live: clicking the "Lean"
  header on a chamber page's seat table re-orders rows ascending then
  descending, confirmed against the actual rendered values, not just that
  a click handler fired.

- `site/methodology/index.md`: a real methodology page (not a stub)
  explaining district lean and WAR, built from the citations and
  provenance already written into docs/PLAN.md §4 and
  `derived_metrics.py`'s own docstring rather than re-derived from
  scratch — including the same "this is adapted from Split Ticket's
  method, not identical to it" caveats and the uncontested-race WAR
  inflation limitation. Linked from the site nav and from every WAR table
  footnote (seat/district pages), replacing what had been a link straight
  to the design plan's raw GitHub markdown.
