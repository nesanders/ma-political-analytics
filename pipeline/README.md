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
  of requests, roughly a 2-3 hour job.

  **Runs as a GitHub Actions workflow**
  (`.github/workflows/backfill.yml`), not as a local background process —
  it started that way, as a long-lived background process inside an
  interactive Claude Code session, which turned out to be the wrong home
  for it: that sandbox's container gets recycled during idle periods,
  silently killing the process, sometimes hours before anyone noticed. A
  GitHub-hosted runner doesn't have that failure mode and has unrestricted
  network access. The workflow is resumable across both runs and steps
  within a run, with no re-scraping of anything already fetched:
  `fetch_years()` is already idempotent per `election_id` and checkpoints
  per year (see its own docstring), and what's "on disk" persists between
  runs via a dedicated orphan branch, `pd43-raw-cache`, holding only
  `data/raw/pd43` and `data/raw/pd43_statewide` — `data/raw` is gitignored
  on every other branch (a pipeline intermediate, not site content), so
  this cache lives apart from that rule entirely rather than fighting it.
  Every run restores from that branch, then fetches House, Senate,
  Governor, and President as four separate steps, each immediately
  followed by its own save-progress step (a small composite action,
  `.github/actions/save-pd43-progress`) that commits and pushes whatever
  changed, with `if: always()` so a step that fails or times out still
  saves everything fetched before it failed — the next run (manual
  `workflow_dispatch`, or the `schedule` trigger every 6 hours as a safety
  net) just continues from there. Seeded once, from this project's own
  in-progress local backfill, with House already through 2017 and Senate/
  Governor through 2022 at seed time — that data was verified intact
  (readable, correct year coverage) before being committed to the cache
  branch, so the migration itself didn't lose anything already fetched.

- `python -m ma_politics.fetch.pd43 --chamber us-house --year-from 2002 --year-to 2024` /
  `--chamber us-senate --year-from 2002 --year-to 2024`
  MA's federal delegation, from the same PD43+ source and the same
  `fetch_years()` machinery as House/Senate above — `--chamber` now also
  accepts `us-house` (office_id 5, district-based, 9-10 districts
  depending on vintage) and `us-senate` (office_id 6, statewide like
  Governor/President, but on a staggered 6-year term — most even years
  return zero results for it, already handled gracefully by the existing
  per-year empty-search-skips-the-year loop, no special-casing needed).
  Both confirmed live against PD43+'s own search-form `<select
  name="office_id">` before use. `--chamber both` is unchanged (still
  means House+Senate only, not all four chambers) — federal chambers need
  an explicit `--chamber us-house`/`--chamber us-senate` invocation.
  Verified live: 300 U.S. House races and 31 U.S. Senate races fetched
  2002-2024 with zero warnings, including real special elections (a 2007
  and a 2013 U.S. House special in the 5th Congressional District; the
  2009/2010 Kennedy-vacancy and 2013 Kerry-to-Secretary-of-State U.S.
  Senate specials).

- `python -m ma_politics.fetch.congressional_boundaries --vintage all`
  MA's three congressional-district vintages (10 districts 2001-2010, 9
  2012-2020, 9 2022-present), all from TIGER directly — no MIT GeoData
  Repository fallback needed here, unlike the state legislative 2001
  vintage. The 2001 vintage isn't in TIGER's regular per-year directories
  (those are empty for congressional districts before ~2011) but *is*
  available under a per-Congress path,
  `TIGER2010/CD/108/tl_2010_25_cd108.zip` (108th Congress); the 2012-2020
  vintage is only ever published by TIGER as a whole-US file (filtered to
  MA's FIPS code after loading); 2022-present is back to a normal
  per-state file. Reformats each vintage's own native column
  (`CD108FP`/`CD113FP`/`CD118FP`, `NAMELSAD00`/`NAMELSAD`) into this
  site's common `(district_id, district_name)` shape — and, unlike the
  state legislative fetcher, additionally rewrites TIGER's own "Congressional
  District 9" name into "9th Congressional District" (PD43+'s own word
  order) at fetch time: a real matching bug found live, since this site's
  existing ordinal-aware district-name normalizer (`util.names.
  normalize_district_name`) strips ordinal suffixes and the word
  "district" but never reorders tokens, so a same-number reordering like
  this doesn't collide even after normalization — every one of the 9-10
  districts failed to match until this was fixed. Writes
  `us-house_<vintage>.geoparquet` to `--out-dir` (default
  `data/raw/boundaries`), same schema as `fetch.district_boundaries`'s own
  output.

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
  MAPLE's own validated example. Idempotent per year — this ran against
  2022 alone for a long stretch of this project (a proof-of-concept
  fetched alongside the initial 2022-only dataset, never revisited once
  the election-results backfill moved on to the full 2002-2024 range) and
  was only actually backfilled to the full range later: 28,824 total
  filer-years across all 23 years, 2002-2024, once run for real — see the
  WAR v3 campaign-finance diagnostic below for what that unlocked (a
  proper multi-year fit instead of a single cycle's snapshot, and the
  candidate-match rate on candidate pages jumping from ~16% to 70%).

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
  Now also runs a third chamber, `us-house` (unchanged machinery — the
  same area-overlay functions, just given `fetch.congressional_boundaries`'
  output instead of `fetch.district_boundaries`'), producing its own
  town↔district overlap and cross-vintage lineage rows in the same two
  output files. Verified live: 559/518/382 overlap rows and 39/36 lineage
  rows across the three vintages, same sensible-continuity spot-check
  pattern as House/Senate.

- `python -m ma_politics.build.derived_metrics --chamber house --year 2022 --vintage 2022-present`
  (`--chamber` now also accepts `us-house` — fully chamber-agnostic
  already, no code change needed beyond widening the CLI's `Choice` list;
  reuses the same Governor/President statewide baseline as House/Senate,
  apportioned via `us-house`'s own town↔district crosswalk. Run once per
  even year, matching the same even-year-only convention House/Senate
  already follow — see `pipeline/ma_politics/build/derived_metrics.py`'s
  `--year`/`--vintage`/`--baseline-office` combinations for all three
  vintages in the git history for the exact 12-invocation loop used.)
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

  A second real bug, found once the multi-decade backfill actually
  finished and this was run against every vintage/year for the first
  time: PD43+'s CSV export joins a joint ticket's running mates (Governor/
  Lt. Governor, President/VP) with `/` in some years' downloads and
  ` and ` in others — not consistently by office or even by candidate, the
  *same* Baker/Polito ticket is `"Baker/ Polito"` in the 2014 CSV and
  `"Baker and Polito"` in 2018's — while the results table (parsed from
  the race detail page, not the CSV) always uses ` and `. Looking up a
  candidate's town-level votes by that literal name against the CSV's
  columns failed for every year that happened to use `/`.
  `resolve_candidate_column()` fixes the lookup itself by normalizing both
  sides before comparing — but the first version of that fix, tested only
  against a single already-known-good manufactured case, introduced a
  second, worse bug: `fetch.pd43`'s town-results table is one wide, sparse
  frame accumulated across every year's elections, so a repeat candidate
  like Baker/Polito has *both* spellings present as columns somewhere in
  the full table, one of them all-zero for whichever year is actually
  being processed. Searching the *full* column list let the exact-match
  fast path match the wrong year's spelling and silently return zero
  votes — not an error, a District full of computed "Safe D" results
  from a governor's race Baker actually won. Caught only by noticing that
  a 100%-one-label result across every single district in a chamber
  doesn't happen in real election data, not by any warning or exception;
  fixed by narrowing the searched columns to ones with real (nonzero) data
  for that specific election before ever calling the resolver. Re-ran
  every vintage/year/chamber combination after the fix and checked
  systematically, not just by eye, for the same red flag (a single
  competitiveness label or near-zero lean variance across a whole
  chamber) — none remained.

- `python -m ma_politics.build.generate_site_data --chamber both --current-vintage 2022-present --vintages 2001-2010,2012-2020,2022-present --site-data-dir site/_data`
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

  **WAR v2** is fit and applied here too, as a second pass over every
  vintage's district records once `is_incumbent`/`incumbent_terms` are
  known (`fit_war_v2_core`/`apply_war_v2`) — a real multi-term regression
  now, not the single group-mean-difference coefficient an earlier version
  of this fit used:

  ```
  own-party share ~ intercept + district lean + statewide tide
                     + incumbency (1st / 2nd / 3rd-or-later term)
  ```

  `own-party` means every value is flipped to that candidate's own party's
  perspective (Republican's own_lean is `1 - lean_dem_share`, same for
  tide), the same symmetry `compute_war()` already uses, so one pooled fit
  covers both parties. `statewide tide` (`compute_statewide_tide_by_year`)
  is the *unapportioned* two-party Democratic share on that year's
  baseline race statewide — a genuinely different number from
  `lean_dem_share`, which is that same race apportioned to one district —
  letting the fit separate a district's own persistent partisanship from a
  given cycle's overall mood. It's summed from the baseline race's
  *town-level* results, not read off `{office}_results.parquet`'s own vote
  totals: that table's `votes` column turned out to be NaN for the
  statewide total in several older years (2002-2014), a real gap found by
  checking actual output (the first version of this function silently
  produced a 240-row training sample instead of the expected ~1,500,
  caught by noticing the sample size didn't match a prior run's, not by
  any error) — town-level summing doesn't have that gap, reusing
  `derived_metrics.resolve_candidate_column` for the same "/" vs "and"
  ticket-naming fix already documented above. Incumbency is now three
  dummies (1st/2nd/3rd-or-later consecutive term, from a new
  `incumbent_terms` count walked oldest-to-newest through each district's
  own results) rather than v1's plain binary.

  **Fit via a hand-rolled Bayesian Gibbs sampler**
  (`_bayesian_linear_regression`), not OLS and not a PyMC/statsmodels
  dependency (this pipeline's own curated dependency list — see
  pyproject.toml — stays numpy-only): a linear-Gaussian model's Gibbs
  sampler has closed-form conditionals for both blocks (coefficients given
  the noise variance are multivariate normal; the noise variance given the
  coefficients is inverse-gamma), so a plain numpy loop is exact MCMC, not
  an approximation, and fast enough (a few thousand iterations over at
  most a few thousand rows) to run inline on every build. Every
  coefficient gets a weakly informative, regularizing Gaussian prior
  (`_COEFFICIENT_PRIORS`) — real shrinkage where the data needs it most:
  district lean and statewide tide are correlated (same underlying race,
  just apportioned differently), and the incumbency buckets are unevenly
  sized. The fit reports a full posterior (mean, SD, 95% credible interval
  from the actual sampled draws) per coefficient, seeded for
  reproducibility (re-running against the same data gives bit-identical
  coefficients — verified directly: `publish_query_data.py`'s independent
  refit of this same model landed on identical `war_v2` values to
  `generate_site_data.py`'s own run).

  Uncontested races are excluded from the fit (their 100% actual share is
  a known-inflated WAR v1 residual, not a clean training signal — see the
  methodology page's WAR v1 limitation). On the last full run: n=1,494
  contested major-party candidate-races, R²=0.48, district lean's
  coefficient landing at ~0.53 (not the naively-expected ~1.0 — checked
  directly against plain OLS on the same data, which lands in the same
  neighborhood, confirming this is a real finding about the data and not
  a prior-driven artifact), and all three incumbency terms landing close
  together (~14-16 points) — see `site/_data/war_v2.yml` for the live
  figures and the methodology page for the full writeup. Every
  candidate-race dict gets `war_v2`, `intercept_component`,
  `lean_component`, `tide_component`, `incumbency_adjustment`,
  `expected_two_party_share`, and `expected_two_party_share_v2` alongside
  the existing v1 `war`/`actual_two_party_share` — verified live against
  real data across 2,842 candidate-race rows: `intercept_component +
  lean_component + tide_component + incumbency_adjustment` reproduces
  `expected_two_party_share_v2` exactly, and `actual_two_party_share -
  expected_two_party_share_v2` reproduces `war_v2` exactly.
  `build_candidate_records()` carries the same four component fields into
  each race in a candidate's own `races` list (not just the district-page
  candidate dicts they're copied from), so a candidate's own page can
  render the identical 5-component attribution chart broken out by year,
  not just the district/seat pages' single-year snapshot — re-verified
  the same exact-sum property across all 3,142 candidate-race rows in
  `site/_candidates/*.md` after wiring that through.

  **WAR v3** extends the same core model with the remaining fundamentals
  this project's original design called for, as diagnostic fits — not
  threaded into every candidate's WAR the way v2 is, for real coverage
  reasons. Campaign finance (`fit_war_v3_finance`), once OCPF's own bulk
  export was backfilled to the full 2002-2024 range (see the
  `fetch.campaign_finance` bullet above), now fits across every year with
  a real match instead of one cycle alone — `own_tide` is back in this fit
  too, since real cross-year tide variation exists to identify it against,
  unlike the single-year version.

  **Demographics is now two tiers, not one** (`fit_war_v3_demographics_core`/
  `_full`), each falling back gracefully rather than all-or-nothing: a
  district missing some Census fields still gets a simpler diagnostic
  instead of being dropped from WAR v3 entirely. The **core** tier
  (bachelor's-degree % + its tide interaction — the original single-tier
  model) needs only `bachelors_pct`, computable for all 200 current-
  vintage districts thanks to the ACS population-denominator fallback
  above; the **full** tier adds Hispanic-or-Latino population share,
  voting-age population share, and median household income (in $10,000
  units) — three Census fields this project already fetched but had never
  put in a regression — restricted to the 185 districts with a real PL
  94-171 match (the two population-share terms need it specifically).
  `_demographic_covariates()` computes whichever covariates a district's
  own data actually supports; `apply_war_v3_demographics` picks the full
  tier when all four are available, the core tier when only bachelors_pct
  is, or neither (falling back to WAR v2 alone, same as before this
  tiering existed) — verified live: exactly the 15 districts whose PL
  94-171 match failed land in the core tier, the other 185 in the full
  tier, all 200 get *something* rather than nothing.

  Census demographics only cover the current (2022-present) vintage,
  which so far has exactly two election years (2022, 2024) — enough real
  cross-district variation to estimate the bachelor's-degree% × tide
  interaction, but with a deliberately tighter prior than its own main
  effect, since two elections can't support trusting it as a stable trend.
  All three fits write their posterior summaries to `--site-data-dir` —
  `war_v3_demographics.yml` (now `{core: ..., full: ...}`, not a flat
  dict) and `war_v3_finance.yml` — which the methodology page reports as
  labeled diagnostics (coefficients, credible intervals, real sample
  sizes) — not silently dropped, not forced onto data too thin to support
  them.

  **WAR is now null for an uncontested race**, for v2 and both v3
  diagnostics (WAR v1 still isn't — a separate, older computation in
  `derived_metrics.py`, documented on the methodology page as its own
  known, not-yet-fixed limitation): an unopposed candidate's mechanically-
  inflated ~100% share isn't a meaningful gap from expectation. What's
  shown in its place, always defined regardless of contested status since
  it doesn't depend on the actual outcome at all, is **baseline
  expectation** — `expected_two_party_share_v2`/`_v3_finance`/
  `_v3_demographics`, which were already computed as an intermediate value
  but not surfaced directly before this. Verified live across the full
  2002-2024 backfill: all 1,648 uncontested candidate-race rows have
  `war_v2` (and `war_v3_*` where applicable) null and a real, non-null
  baseline expectation; all 1,494 contested rows still have both, summing
  exactly to `actual_two_party_share` as before.

  `build_war_v2_fit_sample()` also writes every contested major-party
  candidate-race's actual vs. WAR v2 expected share (plus party and year)
  to `war_v2_fit_sample.yml` — not a fitted-model output itself, just the
  same rows `fit_war_v2_core` trained on, exported so the methodology page
  can render a real "predicted vs. actual" scatter across all of them
  instead of describing the fit in prose alone. `_bayesian_linear_regression`
  now also returns each coefficient's `prior_mean`/`prior_sd` alongside its
  posterior, so the same page can show a genuine before/after (prior vs.
  posterior density) for one term without hardcoding the prior elsewhere.

  `_bayesian_linear_regression` also now returns a **standardized**
  ("beta weight") version of every non-intercept coefficient: each
  posterior draw scaled by that predictor's own SD in the fitted sample
  (`predictor_sd`/`standardized_mean`/`standardized_sd`/
  `standardized_ci_95_low`/`standardized_ci_95_high`), turning "share
  points per unit of own_lean" and "share points per log-dollar raised"
  into one common "share points per 1 SD of this predictor" unit —
  genuinely comparable across a 0-1 continuous slope, a log-dollar slope,
  and a 0/1 incumbency dummy. The intercept has no such rescaling (its
  covariate is a constant column of 1s, SD 0) and is reported as `None`
  rather than a misleading zero. The methodology page now renders one
  full-parameter standardized forest chart per WAR v3 diagnostic (all of
  that fit's terms, not the trimmed subset the native-unit charts show) —
  which also surfaced and fixed a real doc bug: the finance diagnostic's
  own prose/table had claimed it "drops the incumbency terms," when the
  actual `fit_war_v3_finance` code has always fit them alongside
  lean/tide/log_raised; the full-parameter chart and an updated 6-row
  table now show all six.

  Two new `apply_war_v3_*` functions (mirroring `apply_war_v2`) thread
  each WAR v3 diagnostic's own decomposition into the attribution charts,
  wherever real data actually supports it, using distinctly-suffixed
  field names (`*_v3_demographics`/`*_v3_finance`) so they sit alongside
  v2's own fields rather than overwriting them (v2 and v3 fit different
  coefficients on different samples — clobbering would have been a real
  bug, caught and fixed before shipping). `apply_war_v3_demographics`
  mutates the current-vintage district records `apply_war_v2` already
  updated, adding a combined `education_component` (the bachelor's-degree
  main effect and its tide interaction folded into one slice, so the
  attribution chart's palette only needs one extra color). `apply_war_v3_finance`
  mutates `build_candidate_records`'s already-built race dicts, adding a
  `fundraising_component` for any race with an OCPF-matched total that
  year. Both also compute an approximate per-component uncertainty via
  the delta method (`component_sd ≈ |covariate value| × that coefficient's
  own posterior SD` — a known simplification, since it treats each
  coefficient's posterior as independent of the others rather than
  propagating a full joint posterior) alongside the point estimate, and
  reuse the fit's own `posterior_sigma_mean` as the residual/WAR term's
  own uncertainty. District/seat/candidate page attribution charts now
  use whichever decomposition actually applies (v3 when available, v2
  otherwise) for their existing stacked bar, plus a new companion
  forest-style chart showing the same components with an approximate 95%
  interval — verified live: every affected page's components still sum
  exactly to `actual_two_party_share` (checked across all 3,142 v2
  candidate-race rows, all rows with a real `war_v3_demographics`, and all
  2,325 rows with a real `war_v3_finance` — zero mismatches in any of the
  three), and a real Jekyll build + Playwright sweep across a dozen
  district/seat/candidate/methodology pages came back with zero JS errors.

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

  **A second real matching bug, found later by asking why a specific real
  long-serving senator had zero campaign-finance data**: this module's own
  district-name normalizer just lowercased and stripped punctuation, with
  no ordinal handling, so OCPF's numeral-ordinal district names ("1st
  Essex & Middlesex") never collided with this site's own spelled-out
  ones ("First Essex and Middlesex District") — silently excluding every
  candidate in a numbered district whose OCPF filer entry used digits
  where this site spells them out (which is most of them; MA legislative
  districts are almost all ordinal-numbered). This is the identical
  failure mode `derived_metrics.match_district_names()` already had a
  real fix for in a different join (see below) — rather than duplicate a
  second normalizer with a second, subtly different gap, that ordinal-
  aware normalizer moved to the shared `util/names.py` (alongside
  `normalize_town_name`) as `normalize_district_name()`, and both modules
  now import the one shared implementation. Real, project-wide impact:
  OCPF match rate jumped from 942/1,343 candidates (70%) to **1,105/1,343
  (82%)**, and the WAR v3 finance diagnostic's fitting sample grew from
  1,069 to **1,270 candidate-races** across the same 12 election years —
  verified live via a full pipeline re-run and the specific senator's own
  candidate page now showing a real, non-empty finance table for every
  year 2002-2024.

  **Also stamps `is_redistricting_year`** onto every race in
  `build_candidate_records`, computed from each vintage's own earliest
  tracked election year in this run's actual data (not hardcoded, so it
  can't drift as the backfill's covered range changes): true for the one
  year a candidate's `incumbent_terms` genuinely does reset to 0 purely
  because new maps took effect that cycle, not because they weren't a
  real incumbent (see "Incumbency and open seats" in the methodology
  page). Only `candidate.html`'s two year-spanning charts need it — a
  single district/seat page's own chart never crosses a vintage boundary,
  since a seat is scoped to one vintage — where it renders as a shared
  dashed vertical rule (a `rule` mark with only `x` encoded, so it spans
  the full plot height automatically, same idiom the methodology page's
  forest-chart zero-reference lines already use) behind both the
  replacement-level line chart and the attribution stacked-bar chart.

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
  a genuine data gap, not a matching bug); Senate matched 26 of 40 for PL
  94-171 specifically (a real, larger gap — Census's Senate district names
  diverge more from PD43+'s, e.g. "Second Hampden & Hampshire District"
  vs. this site's "Hampden and Hampshire District", an ordinal-prefix-
  plus-wording difference beyond what the existing ordinal-number-guarded
  fuzzy matcher resolves). ACS matches independently and doesn't have this
  gap (all 200 current-vintage districts, House and Senate, get an ACS
  match) — `load_demographics()` now also surfaces ACS's own
  `total_population_acs` (fetched but previously left unused) as a
  population-denominator fallback for districts PL 94-171 missed, so
  `bachelors_pct` (income/education-only demographics) can still be
  computed for all 200 districts even though `hispanic_pct`/`voting_age_pct`
  (which need PL 94-171 specifically) still can't be — see
  `generate_site_data._demographic_covariates` and the two-tier WAR v3
  demographics fit below for how this gets used.
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

**A full-site review of how WAR was presented** (asked directly: "I don't
want the user to see war v1, v2, v3") found the site showing up to four
separate WAR columns on the same page (v1/v2/v3-demographics/v3-finance),
and — worse — chamber and party leaderboards silently showing the raw v1
number, unlabeled, with no fallback logic at all: the site's most-visited
pages showing its crudest, uncontested-inflated metric. Two new functions,
`apply_resolved_war_district`/`apply_resolved_war_candidate`, resolve each
race to a single `war_resolved` figure — the richest model that specific
race's own data supports (demographics-full > demographics-core > core on
district/seat/chamber/party pages, keyed by each district's own Census
match tier; finance > core on candidate pages, keyed by year, since
finance data is per-candidate-per-cycle rather than a fixed district
property) — never the raw v1 baseline, which stays computed internally
(`war`, still used for `is_incumbent`/open-seat detection) but is no
longer surfaced to readers. Alongside the number, `war_resolved_sd`,
`expected_share_resolved`, and a plain-language `war_factors` list (e.g.
`["District lean", "Statewide tide", "Incumbency", "Demographics"]`, no
"v2"/"v3"/"core"/"full" jargon) travel together, so a template can show
what specifically produced a given number without the reader needing to
know which internal model tier ran. Both null out consistently with the
existing uncontested-race behavior. `apply_resolved_war_district` has to
run after `apply_war_v2`/`apply_war_v3_demographics` but *before*
`write_district_files`/`write_seat_files`, since those serialize the
records immediately rather than lazily; `apply_resolved_war_candidate`
has the same constraint relative to `write_candidate_files` — a subtlety
worth calling out because `write_seat_files` runs before
`candidate_records` even exists in `main()`, which is why this is two
functions rather than one shared pass over both record sets.
`build_party_records()`'s `seats_held` entries and sort key were also
switched from raw `war` to `war_resolved`. Templates (chamber, party,
district, seat, candidate) were rewritten to show one WAR + Expected
share + Factors, in place of the old per-version columns, and the
methodology page's "WAR v2"/"WAR v3" section headers/prose were reframed
as "The core regression model" and "Demographics and campaign finance
extensions" (the underlying fits, coefficients, and forest plots
themselves are untouched — only the branding around them). The candidate
page's attribution-chart year selector was explicitly left alone, per the
request. Verified live: `war_resolved + expected_share_resolved ==
actual_two_party_share` exactly for every non-null row, checked
separately on the district side (3,142 rows) and the candidate side
(3,142 rows) — zero mismatches on either; a Jekyll build plus a grep
sweep of the rendered site confirmed no remaining "WAR v1/v2/v3" text
outside two deliberately-untouched, non-page surfaces — an internal code
comment in `main.css`, and AskAI's `schema.json`/`publish_query_data.py`,
whose `war`/`war_v2` are literal SQL column names a power user
deliberately queries via the site's query tool, not passive page prose,
so they were left as the distinct technical surface they are rather than
renamed to match.

**Asked directly why the candidate attribution chart's Fundraising bar
looked disproportionately large next to lean/tide's** — a real
observation about the raw decomposition, not a bug: `log_raised` runs
7-14 across real candidates, a completely different numeric scale than
lean/tide's natural 0-1 fractions, so even the fit's genuinely small
`log_raised` coefficient (`+0.0343`) multiplied out to a large-looking
bar purely from comparing against an impossible $0-raised baseline. Two
changes fixed the actual decomposition, not just added a caveat:

1. **Reference-centering.** `fit_war_v3_finance` and
   `fit_war_v3_demographics_full` now also export `reference_values`
   (each fit's own sample mean for `log_raised`/`income_10k` — the two
   continuous predictors with no natural zero-effect anchor, unlike
   lean/tide/population-share fractions which already read sensibly at
   `coefficient*value`). `apply_war_v3_finance`/`apply_war_v3_demographics`
   compute those two terms' bar-chart contribution as
   `coefficient*(value - reference)` instead of `coefficient*value`,
   folding the removed constant into a renamed "Baseline" bar (was
   "Intercept," in both v2's and v3's field maps in
   district/seat/candidate.html — accurate for v2 too, since v2's
   intercept always meant "predicted share at lean=tide=0," i.e. already
   a baseline). This is algebraically exact, not an approximation: the
   sum of all components still equals `expected_two_party_share_v3_*` to
   the same value as before — only which bar a given dollar of predicted
   share shows up in changed. Real effect: Aaron Michlewitz's real
   $548k-raised 2024 race now shows an ~11-point Fundraising bar (was
   3-4x that), proportionate to lean/tide/incumbency instead of dwarfing
   them.
2. **Fair interaction splitting.** `bachelors_pct_x_tide` was previously
   credited whole to the Demographics bar — an arbitrary choice, since the
   interaction term is literally the product of bachelors-degree rate and
   tide, a joint property of both. A new `_shapley_pair_split(beta1, x1,
   ref1, beta2, x2, ref2, beta_interaction)` helper computes the standard
   two-player Shapley value (average of both "which feature gets credited
   first" orderings) instead: `phi1 = beta1*(x1-ref1) +
   (beta_interaction/2)*(x1-ref1)*(x2+ref2)`, and symmetrically for
   `phi2` — a closed form that's exact for a linear model (phi1+phi2
   always equals the full interaction's contribution, no residual left
   over) and generalizes to a non-zero reference point on either side,
   should a future interaction ever pair a centered predictor with an
   uncentered one. `apply_war_v3_demographics` now uses it to move half
   of `bachelors_pct_x_tide`'s contribution out of `demographics_component`
   and into `tide_component`.

Both changes are display-only reshaping of an already-computed
prediction, not a refit: the underlying `_bayesian_linear_regression`
coefficients are untouched, and `war_v3_demographics`/`war_v3_finance`
(and everything downstream — `war_resolved`, `expected_share_resolved`)
are numerically identical to before. Verified live: components still sum
exactly to `expected_two_party_share_v3_*` (0 mismatches across 500
district `v3_demographics` rows and 2,325 candidate `v3_finance` rows —
same invariant checked after every previous change to this
decomposition); a Jekyll build + Playwright sweep across a full-tier
district, a core-tier district, a high-fundraising candidate, and the
methodology page came back with zero JS errors.

**A follow-up review asked whether the `bachelors_pct_x_tide` interaction
the Shapley split above had just fairly divided was itself principled —
it wasn't, and it's now removed entirely.** It was the only interaction
term fit anywhere in this module (finance's `log_raised`, with a real 12
distinct election years, had never even been tested for one), chosen
because "diploma divide" is the term the realignment literature
discusses rather than because the data supported it best, and fit on
just 2 distinct election years — thin enough that its own docstring
already flagged the risk. Removed from `_COEFFICIENT_PRIORS`,
`_build_demographics_rows`, and both `fit_war_v3_demographics_core`/
`_full`'s feature lists; `apply_war_v3_demographics` reverted to a plain
per-term decomposition (no more interaction to split between the
Demographics and Statewide tide bars); the now-uncalled
`_shapley_pair_split` helper was deleted rather than left as unused
infrastructure. In its place, a documented policy in the module-level
comment above `_COEFFICIENT_PRIORS`: no tide interaction for any
predictor until it has enough distinct election years to actually
identify one (a rule of thumb, 4+) — so a future contributor sees the
bar this project didn't clear before adding one back, rather than
re-discovering the same thin-identification problem from scratch.

**The methodology page's WAR section was also rewritten this round**
(asked directly, alongside the interaction removal, to replace its
"historical timeseries" framing with a concise description of the
current methodology, and to use visualizations more generously): prose
that read as an incremental build log — "had never threaded into any
regression until now," "no longer collinear the way it was when this was
fit on a single year's races," "as an earlier version of this chart
did" — was rewritten to describe what the models compute today, not how
they got there (that history belongs in this README and `docs/PLAN.md`,
not a public methodology page). A new **model-overview forest chart**
(`war-overview-chart`, in `site/methodology/index.md`) was added right
after the page's WAR intro, before any per-model detail section: every
fitted effect from every model — the core model's lean/tide/incumbency,
the demographics extension's four terms, the finance extension's
fundraising term — plotted together on one standardized scale, colored
by which model fits it, so a reader sees the whole comparative picture
before drilling into any one model's own coefficient table, native-unit
forest plot, or fit-diagnostic chart. Built from three separate
`site.data.war_v2`/`war_v3_demographics`/`war_v3_finance` YAML exports,
each bound to its own local JS `const` once (rather than the same
`{{ ... | jsonify }}` tag re-embedded per data row, which the first draft
of this chart did before being cleaned up). Verified live: re-ran the
full pipeline after the interaction removal and confirmed the same
sum-invariant holds (0 mismatches across 500 district `v3_demographics`
rows and 2,325 candidate `v3_finance` rows); a Jekyll build + Playwright
sweep of the methodology page (including confirming the new chart's
`<canvas>` element actually renders with non-zero dimensions and zero
console errors, not just an empty container) and both a full-tier and a
core-tier district page came back clean.

**Federal election data (U.S. House + U.S. Senate)** — see
`docs/PLAN.md`'s Phase 7 roadmap entry for the full writeup (fetch/build
provenance, the separate-model reasoning, and live verification numbers);
summarized here. `generate_site_data.main()` gained `--us-house/--no-us-house`
(default on) and `--us-senate/--no-us-senate` (default on). U.S. House
runs through the same `build_district_records`/`build_seat_records`/
`build_candidate_records`/`write_*_files` functions every other chamber
uses (all already fully chamber-agnostic — no changes needed there), but
through its own separate Bayesian fit (`fit_us_house_war_model`/
`apply_us_house_war`, new `site/_data/us_house_war_model.yml`/
`us_house_war_fit_sample.yml` exports) — kept in its own
`ush_district_records_by_vintage` dict, entirely apart from the state
model's own training data, until *after* both models have fit and
applied; merged into the shared dict only then, so district/seat/
candidate file-writing and the town/party rollups see one combined roster
without their own chamber-specific branching. U.S. Senate skips the
district/seat/candidate machinery entirely (`build_us_senate_records`,
reading `fetch.pd43`'s `us-senate_races`/`results` directly — no
crosswalk, no apportionment, since there's no district to apportion a
single statewide seat into) and writes a flat `site/_data/us_senate.yml`
for a new, simple `/us-senate/` results-and-history page. New nav links,
a `site/_data/chamber_labels.yml` lookup (replacing five `capitalize`-based
chamber labels that would otherwise have rendered "Us-house"), a new
`/chamber/us-house/` page (the existing `chamber.html` layout, unchanged),
and `publish_district_geo.py --chamber us-house` for the U.S. House
district-map GeoJSON (plus a third map section on `/map/`) round out the
site side.

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

Two more chart types build on the same vendored Vega, filling out the
remaining types docs/PLAN.md §6 named:

- **A true binned histogram** on `chamber.html`, right below the existing
  strip plot: same `seatData` array, a `"bin": { "step": 0.05 }` encoding
  and a `count` aggregate instead of one point per seat — a genuinely
  different view (how many seats at each lean level) from the strip plot
  (each seat as its own point). Deliberately a single flat bar color
  rather than per-bin party coloring: Vega-Lite's binned-field internal
  name depends on the exact bin parameters used, and getting it wrong
  silently produces an uncolored or miscolored chart rather than an error
  — not worth the fragility for a cosmetic choice.
- **A line chart** of a seat/district's own Democratic lean by election
  year, added to both `district.html` and `seat.html` (`results_by_year`,
  already in front matter, reversed to chronological order for the x-axis).
  With only 2022 data currently published for most districts, this renders
  as a single point today — the page says so explicitly rather than
  showing a misleadingly bare chart with no explanation — and needs no
  code change to fill in as the multi-decade backfill lands, since it
  already iterates whatever years are in `results_by_year`.

Verified live (headless browser, both chamber and seat pages): the
histogram renders a real, sensible distribution (House seats cluster
toward the Democratic side, matching the chamber's known composition),
and the trend chart renders a single correctly-valued point at the
district's real 2022 lean.

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
  lean favors. The basemap underneath is a separate concern from the
  district polygon itself and has never been verified live from this
  environment — this session's network policy blocks the tile host the
  same way it blocks jsDelivr for AskAI's DuckDB-Wasm bundles (see
  `site/src/askai/src/duckdb.ts`). What's confirmed instead: the district
  polygon still renders correctly (screenshotted) with the basemap tiles
  failing to load, since it's added as its own MapLibre layer independent
  of the basemap source's own load success.

  **The basemap provider itself changed once, for a real reason.**
  Originally CARTO's free raster tiles (`basemaps.cartocdn.com`), on the
  documented understanding that they didn't require an API key. A real
  screenshot of the deployed site (the one place this could actually be
  checked, given this session can't reach the tile host either way) showed
  every tile as an "API KEY REQUIRED" placeholder image instead of a map —
  CARTO's free tier apparently doesn't cover this project's traffic/
  referrer the way it once did, or the docs this was built against were
  already wrong. Switched to OpenStreetMap's own standard tile server
  (`tile.openstreetmap.org`) in both `district-map.js` and
  `statewide-map.js` — no signup, no key, the most standard "just works"
  XYZ raster tile source there is. Traded away CARTO's light/dark tile
  variants in the process (OSM's standard tiles have no dark-mode
  counterpart), so the basemap no longer adapts to the page's theme — a
  real, accepted regression rather than a silently reintroduced one.
  OSM's own tile usage policy is explicitly scoped to light/moderate use,
  not heavy production traffic; fine for a site this size, worth
  revisiting (dedicated tile hosting, or a paid provider) if that ever
  changes. Still unverified live from this session for the same reason as
  before — the fix can only really be confirmed from a real browser
  reaching the real deployed site.

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

- `site/search/` + `site/assets/js/search.js`: a search/compare tool, no
  new Python pipeline step or server needed — the search index is a plain
  JSON array Jekyll renders straight from `site.seats`/`candidates`/
  `towns`/`parties` at build time, and `search.js` does a case-insensitive
  substring filter over it client-side as the user types. Seats get an
  "+ Compare" button; adding up to two renders a side-by-side table
  (chamber, lean, turnout vs. baseline, most-recent open-seat status,
  population, median household income) pulled from the same index entry,
  so it can't drift from what the seat's own page shows. Reuses the
  `data-site-baseurl` attribute (see the statewide-map bug above) for its
  result/compare links rather than repeating that bug in a third place.
  Verified live: searching "Barnstable" returns all five House Barnstable
  seats with correct competitiveness labels, and comparing 1st vs. 2nd
  Barnstable District renders real, correct numbers for both (60.8%/56.6%
  Democratic lean, $85,958/$81,933 median household income) side by side.

  The index itself is published as its own static asset
  (`site/search/index.json`, a Jekyll page with `layout: null` and an
  explicit `permalink` rather than a Markdown page — Jekyll runs Liquid
  over any file with front matter, HTML or not) fetched with `fetch()`,
  not embedded inline on the search page. That split mattered once a
  second consumer showed up: a **compact search box now sits in the site
  header on every page** (`default.html`, styled in `main.css`), giving
  the site the "consistent search bar across sections" docs/PLAN.md §11's
  theming section calls for. Embedding the index inline (the search
  page's original approach) would have meant shipping the same ~190KB of
  JSON on every one of this site's ~1,000 generated pages instead of
  fetching it once and letting the browser cache it. Verified live: typing
  in the header box on `/town/` (not the search page itself) returns real
  matching seats and candidates from a dropdown, and clicking one
  navigates to the correct page — confirming the index really is shared
  and not duplicated per page.

- **Institutional theming** (`site/assets/css/main.css`,
  `site/_layouts/default.html`, `index.md`, `party/index.md`,
  `chamber.html`): fills out docs/PLAN.md §11's "restrained institutional
  palette" and "member-directory-style listing cards," the last pieces of
  that section. A fixed dark-navy masthead (`--masthead-*` tokens) gives
  every page a persistent civic header that deliberately doesn't flip
  with the light/dark toggle, and deliberately isn't blue or red — this
  site's own chart tokens (`--series-dem`/`--series-rep`) already use
  that exact pair for Democratic/Republican, so a partisan-colored
  masthead on a nonpartisan site would misread as an endorsement. New
  `--surface-page`/`--surface-card` tokens (the dataviz skill's own "page
  plane" vs. "chart surface" roles, not invented here) give cards and
  stat tiles visible depth against the page background. The `/party/`
  index (3 rows) is now a card grid with a party-colored left border
  reusing the existing chart tokens — legitimate there, since the page is
  literally about parties — while `/candidate/` (282 rows) and `/town/`
  (351 rows) deliberately stay sortable tables: this same section of the
  plan also calls for "sortable/searchable leaderboard tables as landing
  views" for stat-dense pages, and a few hundred unsorted cards would be
  a worse way to scan that many rows than the existing sortable table.
  New stat-tile KPI rows replace the homepage's plain paragraph and each
  chamber page's "At a glance" bullet list with headline-metric-first
  tiles. Verified live in both light and dark mode via headless-browser
  screenshots: masthead, cards, and stat tiles all render correctly with
  real numbers (200 seats / 282 candidates / 351 towns on the homepage),
  and a seat page plus the header search dropdown were re-checked for
  regressions from the new header/footer markup — none found.

## The multi-decade backfill, completed

The full House/Senate/Governor/President backfill (2002-2024) described
above under "Runs as a GitHub Actions workflow" finished: House through
2024, Senate through 2024, Governor for its full 2002-2022 quadrennial
cycle, President for its full 2004-2024 cycle (2002 has no presidential
election; MA's own even-year state legislative cycle occasionally skips
an odd year too — both are real calendar facts, not gaps). Every
downstream build step was then re-run across all three vintages for the
first time against real historical data, not just 2022:
`generate_site_data.py` (200 seats, 601 district pages across all three
vintages, 1,343 candidates — up from 282 once a decade of additional
elections' candidates are included), `publish_query_data.py` (2,405
seat-year rows, 3,447 results rows), and `publish_district_geo.py` (602
GeoJSON files). A full `bundle exec jekyll build` succeeded with zero
errors against all of it.

Running `derived_metrics.py` against the full range for the first time
(previously only ever run against 2022) surfaced a real bug that 2022
alone never exercised — and a second, worse bug introduced while fixing
the first — described in the `derived_metrics.py` bullet above
("Fix candidate-name resolution for statewide baseline races" in the
commit history has the full story). After both fixes, every one of the
22 newly-computed chamber/vintage/year lean files was checked
systematically (not just spot-checked) for the telltale sign of that bug
class — a single competitiveness label or near-zero lean variance across
an entire chamber — and none remained. Verified live in a real browser
against the regenerated site, not just the raw numbers: a 2001-2010-
vintage district's trend chart now shows a real 5-point line (2002-2010)
with genuine year-to-year variance instead of the single-point
placeholder it rendered against 2022-only data, and a chamber page's "At
a glance" summary now shows a real incumbent re-election rate (99%,
131/132) instead of the "unknown" state a single year of data always
produced — both exactly the shape of result the earlier synthetic-data
tests for these features predicted, now confirmed against real history
rather than a manufactured test case.

## WAR unified into one regression: structural lean, party interaction, indicator-free extensions

The three-model WAR design described above — a core fit
(`fit_war_v2_core`/`apply_war_v2`) plus two diagnostic extensions
(`fit_war_v3_demographics_core`/`_full`, `fit_war_v3_finance`), resolved
per-race after the fact by `apply_resolved_war_district`/
`apply_resolved_war_candidate` — is gone, replaced by one fit
(`fit_war_model`) and one apply pass (`apply_war`) in
`generate_site_data.py`. Three changes landed together, asked for
directly: sanitize lean vs. tide's collinearity by computing lean per
*district* rather than per *year*; fold the demographics/finance
extensions into terms that zero out for a race without the data instead
of two separate models; and add a party interaction, since a prior round
had found (and only measured, not fixed) a real Democratic-vs-Republican
residual asymmetry in the pooled core fit.

**Structural lean.** `build_district_records` now also computes
`lean_dem_share_structural` — the plain average of `lean_dem_share`
across every year on record for that district within its vintage — right
alongside the existing per-year field. `fit_war_model`'s `own_lean` is
built from this structural value; `own_tide`
(`compute_statewide_tide_by_year`) is unchanged, still per-year and
statewide. Every other use of `lean_dem_share` on the site (district-page
headline stat, the lean-over-time trend chart, competitiveness bucketing)
still uses the plain per-year value — only the regression's own `own_lean`
input changed. This is the standard Gelman & King "normal vote" split
this project's own citations already pointed to, and practically, much
less collinear with tide than two numbers both freshly derived from the
same year's baseline race used to be.

**One regression, extension terms that zero out instead of two more
models.** `fit_war_model` builds its training rows across every vintage
(not just the current one) for the core lean/tide/incumbency terms —
they're always informed, regardless of whether a given race has
demographics or finance data — and attaches `bachelors_pct`/
`hispanic_pct`/`voting_age_pct`/`income_10k` (current-vintage-only) and
`log_raised` (any vintage/year, via a `finance_by_slug` lookup) wherever a
race's own data supports them. Each of those five covariates is centered
on its own mean *among the rows that actually have it*, and a row missing
it gets that same mean substituted, rather than a raw zero or an explicit
indicator/dummy column — so its centered contribution to that term is
exactly 0, and it doesn't move the term's fitted coefficient, while the
row's lean/tide/incumbency values still fully inform the shared core
terms. `reference_values` is exported alongside the fit's coefficients so
`apply_war` can reuse the exact same centering when computing each race's
own component. The genuinely new capability this unlocks, which the old
"resolve to exactly one extension per race" design could never
represent: a single race can now carry both a Demographics and a
Fundraising contribution to its expected share at once — verified live,
29 of a 191-race sample had both non-null simultaneously.
`demographics_tier` (`"full"`/`"core"`/`None`) is still computed the same
way as before (`_demographic_covariates`, unchanged), just inline within
`apply_war` now rather than by choosing between two separately-fitted
tier models.

**Party interaction terms.** Every core term — `intercept`, `own_lean`,
`own_tide`, and each of the three incumbency buckets — gets an
additional `is_dem`-scaled delta term (`is_dem`, `own_lean_x_dem`,
`own_tide_x_dem`, `incumbent_{1,2,3plus}_x_dem`), each with its own
Gaussian prior in `_COEFFICIENT_PRIORS`, centered at 0 with **half** the
width of its corresponding shared term's prior — a partial-pooling
design (assume symmetry by default, let real evidence in the data pull a
term away from it) chosen over both full pooling (the old design, which
produced the earlier-measured +5.3/-5.3-point residual asymmetry) and two
fully separate per-party regressions (which would throw away everything
the two parties' races have in common and double the number of
poorly-identified coefficients). On the last full run: `own_lean_x_dem`'s
95% credible interval excludes zero ([0.025, 0.203]) — a real, found
asymmetry in how strongly Democratic vs. Republican candidates' share
tracks district lean — and both `incumbent_1_x_dem` and
`incumbent_3plus_x_dem` do too, both negative (roughly -0.06), while
`own_tide_x_dem` and `incumbent_2_x_dem` straddle zero. Real effect on
the asymmetry these terms exist to address, verified live from the
refit `war_fit_sample.yml`: Democratic candidates' mean residual dropped
from +5.3 points (the prior round's pooled-only fit) to **+0.02**,
Republicans' from -5.3 to **-0.01**. `own_lean`'s own shared coefficient
also moved, from 0.53 (per-year lean, core-only fit) to 0.73 (structural
lean, one fit absorbing what three separate narrower fits used to) — R²
rose from 0.48 to 0.73 over the same change. Each component's SD in
`apply_war` now combines the shared and `× Democratic` terms as
`sqrt(shared_sd² + (is_dem × delta_sd)²)`, extending the existing
delta-method "treat coefficients as independent" simplification to the
new terms rather than fixing that simplification.

**Feature list** (17 parameters, up from 6): `intercept`, `is_dem`,
`own_lean`, `own_lean_x_dem`, `own_tide`, `own_tide_x_dem`,
`incumbent_1`, `incumbent_1_x_dem`, `incumbent_2`, `incumbent_2_x_dem`,
`incumbent_3plus`, `incumbent_3plus_x_dem`, `bachelors_pct`,
`hispanic_pct`, `voting_age_pct`, `income_10k`, `log_raised` — all fit
through the same unchanged `_bayesian_linear_regression` Gibbs sampler.
`apply_war` sets `war_resolved`/`expected_share_resolved`/`war_factors`
directly (kept under those names for continuity with the earlier
resolved-WAR consolidation round) plus bare component fields
(`intercept_component`, `lean_component`, `tide_component`,
`incumbency_adjustment`, `demographics_component`,
`fundraising_component`, each with a `_sd` sibling) — the old
`_v2`/`_v3_demographics`/`_v3_finance`-suffixed field names and the
`war_model` field (redundant now that there's only one model) are gone.

**`main()`'s orchestration reordered.** `apply_war` needs
`finance_by_slug` (to fit and apply the fundraising term to *any* race,
not just candidate-page ones — a district-page candidate's expected
share can now be informed by their own OCPF match too), which needs a
`build_candidate_records()` call to get slug/district/chamber/year
associations to match against OCPF — so a **preliminary**
`build_candidate_records()` call now runs before OCPF matching and the
fit itself, purely for that lookup (its WAR fields are all still `None`
at that point). `write_district_files`/`write_seat_files`, which
previously ran before `candidate_records` existed at all (the entire
reason the old two-phase `apply_resolved_war_district`/
`apply_resolved_war_candidate` split existed), now run *after*
`fit_war_model`/`apply_war` instead, once every district record's WAR
fields are populated. A **second, final** `build_candidate_records()`
call then rebuilds candidate records from those now-populated district
records, so each candidate's own `races` list inherits the unified
fields via the existing copy-from-district-dict pattern (the
copy list itself was updated to the new bare field names).
`publish_query_data.py`'s independently-fitting `build_results_table`
was updated the same way — it fits its own copy of `fit_war_model`
rather than reading back the written YAML, so it can't go stale relative
to whatever data a given invocation actually has on disk — and gained a
`--current-vintage` option plus its own demographics/OCPF matching
(previously only `generate_site_data.py`'s core v2 fit needed neither).

**Output files renamed**: `war_v2.yml`/`war_v2_fit_sample.yml`/
`war_v3_demographics.yml`/`war_v3_finance.yml` are replaced by
`war_model.yml` (the one fit's full coefficient table, `n`,
`r_squared`, `reference_values`, and diagnostic counts) and
`war_fit_sample.yml` (unchanged shape — `{actual, expected, party,
year}` rows — still exists purely for the methodology page's scatter
and residual-histogram charts).

**Template changes**: all five page templates
(`chamber.html`/`party.html`/`district.html`/`seat.html`/`candidate.html`)
had their `V2_FIELDS`/`V3_FIELDS`/`useV3` dual-map branching collapsed
into one `FIELD_MAP`/`CANONICAL_COMPONENTS` pair, with Demographics and
Fundraising as two always-available slots (previously Demographics only
existed on district/seat pages' field map and Fundraising only on
candidate pages'; both now exist everywhere, since either can now apply
to any race). A new `--war-fundraising` CSS variable (light `#9725d0` /
dark `#a73cdd`) covers the newly-independent Fundraising segment —
picked by running the dataviz skill's own `validate_palette.py` against
the specific pairs it can land adjacent to in the attribution stack
(Incumbency, the existing `--war-extra` Demographics slot, and WAR
residual, in both light and dark mode) until one cleared every gate,
since the existing 8-hue reference palette was already fully claimed
elsewhere across these same pages (the other five `--war-*` slots plus
`series-dem`/`series-rep`) — no free hue existed without going outside
that validated set.

Verified live: components still sum exactly to `expected_share_resolved`
and `war_resolved + expected_share_resolved` to `actual_two_party_share`
across a 191-race sample (zero mismatches); both `generate_site_data.py`
and `publish_query_data.py` run cleanly end to end against the full
2002-2024 backfill; a Jekyll build + Playwright sweep of the methodology
page (all 7 charts render as populated `<canvas>` elements, the
D-vs-R residual-note spans populate with the now-near-zero figures), a
district page and a candidate page each showing simultaneous
Demographics+Fundraising attribution bars, plus chamber/party/seat pages,
came back with zero JS console errors.

## Incumbency simplified to a single term

`fit_war_model`'s three consecutive-term incumbency buckets
(`incumbent_1`/`incumbent_2`/`incumbent_3plus`, each with its own
`_x_dem` interaction — six parameters) were replaced with one
`incumbent`/`incumbent_x_dem` pair (asked for directly, since the three
buckets' posterior means had already landed close enough together in a
prior round's fit to not show a real "sophomore surge" or later-term
fade). `INCUMBENT_TERM_BUCKETS`/`_incumbent_term_dummies` (a dict of
three dummies, keyed by bucket name) are gone, replaced by
`_is_incumbent_dummy(terms) -> float` (`1.0` if `terms >= 1` else
`0.0`); `_COEFFICIENT_PRIORS` dropped from 17 entries to 13. `apply_war`'s
per-race incumbency computation collapsed from a dict-keyed sum over
`INCUMBENT_TERM_BUCKETS` plus an "active bucket" lookup for its SD to a
single `(b_inc + b_inc_dem * dem_flag) * is_incumbent` expression — no
behavior change for a non-incumbent (still 0), and one shared coefficient
instead of three for every incumbent regardless of consecutive-term
count. `incumbent_terms` (the actual consecutive-term count) is
unchanged and still carried on every candidate record for display —
only the regression's own use of it changed, from three dummy buckets to
one `>= 1` test.

Real effect on the fit, re-run against the full 2002-2024 backfill: R²
essentially unchanged (0.7336 → 0.7327 — the three-way split wasn't
buying real explanatory power), `incumbent`'s posterior mean (+13.0 pts)
falls within the old three buckets' own range (+11.1 to +13.5), and
`incumbent_x_dem`'s 95% credible interval ([-7.8, -3.7] pts) stays clear
of zero — a real, if modest, party asymmetry in the incumbency effect
survives the simplification. `fit["n_incumbent_1"]`/`n_incumbent_2`/
`n_incumbent_3plus` are replaced by `fit["n_incumbent"]` (413, the sum of
the old three) alongside the unchanged `n_non_incumbent` (1,081). All
five page templates' formula text, the methodology page's coefficient
table/forest chart/prior-posterior chart/model-overview chart term lists,
and the AskAI schema card's `incumbent_terms`/`incumbency_adjustment`
descriptions were updated to match. Verified live: components still sum
exactly to `expected_share_resolved` across a 191-race sample; the
Democratic/Republican residual fix from the round above still holds
post-simplification (+0.02/-0.00 points, from +0.02/-0.01 before); a
Jekyll build + Playwright sweep of the methodology page (forest and
prior-posterior charts render against the new single-term coefficient
set) and a district page (one Incumbency segment in the attribution
chart, not three) came back with zero JS errors.

## Primary elections modeled

Massachusetts's 2026 state primary happened the week this round of work
started, prompting a direct ask: model primaries with a real regression
(not just display them), give primary-only candidates full pages, keep
special elections, and give the attribution charts shaded colors/special
symbols for primaries and specials.

`fetch.pd43` already fetched primary-stage results every year of this
site's backfill (`STAGE_PRIMARIES` alongside `STAGE_GENERAL`) — that part
was pre-existing infrastructure, just never modeled or shown. The new
work starts in `derived_metrics.compute_primary_results`: results are
merged against `races` and filtered to `stage == "primary"`, then grouped
by `election_id` rather than `(district, year, party)` — a district can
have two primaries for the same party in the same calendar year (a
regular cycle primary and a special filling a vacancy), each with its
own `election_id`, which grouping by the coarser key would silently
merge together. Each candidate's `actual_primary_share` is votes divided
by that race's total; `fair_share` is `1 / n_candidates` — the field-size-
derived "no-information" baseline a primary needs in place of
`lean_dem_share`, since a primary field varies in size year to year in a
way a two-party general never does.

`generate_site_data.py` gained a second, separate Bayesian fit for this:
`fit_primary_war_model`/`apply_primary_war`, using the same
`_bayesian_linear_regression` Gibbs sampler as the general model, on a
new response variable (`excess_share = actual_primary_share - fair_share`)
and five new `primary_*` priors in `_COEFFICIENT_PRIORS`:

```
excess_share ~ primary_intercept
             + primary_incumbent
             + primary_incumbent_x_tide
             + primary_incumbent_x_lean
             + primary_log_raised
```

Incumbency only ever appears interacted with tide and lean here, never as
its own bare main effect — there's no basis for claiming a non-incumbent's
own primary share tracks that year's statewide mood or the district's
general-election partisanship, so those two interaction terms are
deliberately narrower claims than the general model's own tide/lean main
effects. Fit on the full 2002-2024 backfill plus 2026's special-election
primaries: 1,463 contested major-party primary candidate-races, R² =
0.27, 171 of them an incumbent defending their own seat, 1,168 with a
matched OCPF total. The incumbency coefficient alone (+15.5 points) comes
in meaningfully larger than the general model's own incumbent term — a
primary electorate skews toward a party's most engaged voters, among whom
a sitting legislator's name recognition plausibly matters even more.

**A real bug, caught before shipping**: getting "how many terms has this
incumbent completed as of this primary" right isn't the same question the
general model's existing `incumbent_terms` field answers ("terms served
*before* this specific general race"). The first implementation reused
that field directly and undercounted every incumbent's primary by exactly
one term — caught live on Ann-Margaret Ferrante's 2024 primary, which
showed `incumbent_terms: 0` despite her being a genuine 1-term incumbent
by then. Fixed by extending `build_district_records`'s existing
terms-served backward-walk loop to also record `winner_terms_after_year`
(the post-race winner/term-count immediately after each general year is
processed), then looking up the most recent general year strictly before
the primary's own year for that primary's incumbency state.

**Special elections are included for primaries; generals keep their
existing exclusion.** This is a narrower scope than "keep special
elections" alone might suggest, and was reasoned through and flagged to
the user rather than assumed. `compute_war`'s pre-existing `~is_special`
filter (which excludes special generals) is unchanged, because extending
it surfaced a real complication: at least 30 district-years across the
2002-2024 backfill already have *two* general races in the same calendar
year (a special filling a vacancy plus that district's own regular-cycle
election that same year), which the current one-row-per-(district, year)
incumbency-chain logic isn't built to represent safely without risking
the existing, already-shipped general-election logic. Primaries carry no
such collision risk — each is keyed to its own PD43+ `election_id`, so a
regular and a special primary in the same district/party/year simply
become two separate rows — so extending special-election coverage there
was the unambiguous first step.

**Primary-only candidates now get full candidate pages.**
`build_candidate_records` gained a second loop, appending one race entry
per primary candidacy (`stage: "primary"`) alongside the pre-existing
general-race entries, using distinctly-named fields
(`actual_primary_share`, `primary_expected_share`, `primary_war`,
`primary_war_factors`, ...) rather than overloading the general model's
field names, since the two aren't on the same scale — a primary's
expected share is relative to its own N-candidate field, a general's to
a two-party baseline. `latest_info` (a candidate's display name/party for
the page) is only ever set from a primary row as a fallback
(`if slug not in latest_info`), never overriding a general-sourced entry.
Real effect: candidate pages jumped from 1,343 to 2,045.

Templates:

- **`district.html`/`seat.html`** gained a new "Primary results" section,
  parallel to "Election results," rendering `page.primaries` (one
  sub-table per race, votes/share/primary WAR/expected share/factors per
  candidate, special-election races marked). Seat pages inherited this
  for free — `build_seat_records` already spreads the full district
  record dict, `primaries` included.
- **`candidate.html`**'s two year-spanning charts were unified across
  stages, per the explicit ask for "shaded colors and special symbols."
  The WAR-vs-replacement-level chart gained a second, unconnected point
  layer for primary races: a constant `xOffset` nudges them beside that
  year's general point, and a `shape` encoding (diamond for a primary,
  triangle for a special-election primary, with a real Vega-Lite shape
  legend) distinguishes them from the general layer's circles — kept as
  a separate layer rather than folded into the existing connected line,
  since offsetting points that a "line" mark also connects across years
  would produce a misleading zig-zag. The attribution bar chart now
  field-maps a primary race's `primary_baseline_component`/
  `primary_incumbency_component`/`primary_fundraising_component`/
  `primary_war` onto the same canonical Baseline/Incumbency/Fundraising/
  WAR-residual slots the general model already fills (done via Liquid's
  `default` filter at the point each race's JS row is built, so the JS
  itself never needs to know which stage a row came from) — a primary has
  no Lean/Tide/Demographics slice of its own, so those three stay null
  and are skipped the same way an unmatched general race's Demographics/
  Fundraising already were. Primary and general bars for the same year
  are dodged apart with a field-based `xOffset` on `stage`, a primary bar
  renders at reduced opacity, and a special-election primary's bar
  additionally gets a dashed stroke outline — no new CSS colors needed,
  since every primary component reuses an existing `--war-*` variable.
  The Races table gained a Stage column and the same `default`-filter
  unification for its Share/WAR/Expected share/Factors columns. The
  attribution-uncertainty chart's year selector is now keyed by
  `year + "|" + stage` rather than year alone, since a candidate can have
  both a primary and a general in the same year (the ordinary case) and
  year alone can't tell those apart in the dropdown.

The methodology page gained a new "Primary elections" section: the
formula, the excess-share/fair-share framing, a coefficient table plus a
forest plot and an actual-vs-expected scatter (shaped by special-election
status) built from two new `site/_data/primary_war_model.yml`/
`primary_war_fit_sample.yml` exports, the special-election-scope reasoning
above, and one documented, accepted limitation: because excess share has
no natural 0-100% bound the way a two-party share does, an uncontested
incumbent's `primary_expected_share` can come out above 100% (the fitted
intercept and incumbency terms simply add on top of an already-100%
uncontested fair share) — visible directly on that candidate's own Races
table, documented rather than artificially capped, since capping it would
hide, not fix, the real reason it happens. This mirrors the general
model's own already-documented uncontested-race WAR inflation.

`derived_metrics.py`'s `main()` was restructured so primary computation
runs and is written to disk *before* the block that requires that year's
baseline Governor/President race — needed for 2026 specifically, whose
regular-cycle primary/general aren't posted on PD43+ yet but whose two
special-election primaries (5th Essex District house, First Middlesex
District senate) already are; `discover_primary_years` (new) finds
primary years independent of `discover_years` (which requires a same-year
lean file), so 2026's primary data can exist on its own even without that
year's baseline race. Verified live: `fetch.pd43 --year-from 2026
--year-to 2026` pulled the real, currently-posted 2026 special-election
primaries; re-running `derived_metrics.py` for 2026 writes the primary
parquet successfully, then raises (as designed, non-fatal to the
already-written primary data) on the missing baseline lookup. Sum-
invariant checks (component sums equal `primary_expected_share`;
`actual - expected == primary_war`) passed with zero mismatches across
394 sampled candidate-races. A Jekyll build + Playwright sweep covered a
district page with a real 2026 special primary (5th Essex District, both
parties), a candidate with both a primary and a general in the same year
(Ann-Margaret Ferrante), a candidate with a 2026 special-election primary
specifically (Ashley Sullivan), and the methodology page's two new
charts — all came back with zero JS errors and the expected offset/
shape/opacity/dash rendering in each case.

## Statewide map: variable/vintage selectors, WAR-enriched combined GeoJSON

`/map/`'s three chamber maps (asked directly: "add a selector to the maps
so you can visualize any district-level inferred variable, such as
importance of finance... also allow for vintage selection") each gained a
vintage `<select>` (2001-2010/2012-2020/2022-present — the combined
per-vintage GeoJSON already existed for all three chambers/vintages, just
was never wired to a control) and a metric `<select>` recoloring the map
from the default partisan lean to any of: the most recent race's winner's
own resolved WAR, its lean/tide/incumbency/demographics/fundraising
components, or turnout ratio vs. baseline. Both live in `statewide-map.js`
(rewritten, not just extended) alongside a live legend (gradient bar +
min/center/max labels + a plain-language note) inserted as a DOM sibling
of the map container, not a child of it (MapLibre appends its own canvas
as a child, so pre-existing children would sit oddly underneath it).

Building this surfaced a real, previously-latent data gap:
`publish_district_geo.py`'s `publish_combined` built its FeatureCollection
by calling `generate_site_data.build_district_records` directly — which
returns *raw* candidate dicts (name/slug/party/votes/winner/
actual_two_party_share/plain `war`), never the `war_resolved`/
`lean_component`/`tide_component`/`incumbency_adjustment`/
`demographics_component`/`fundraising_component` fields, since those are
only ever set by `apply_war`/`apply_us_house_war`, which run *only* inside
`generate_site_data.py`'s own `main()` (fitting the model needs
statewide tide, OCPF finance matching, and demographics data this
narrowly-scoped geometry-publishing script has no reason to also wire
up). Confirmed live before assuming it: a first pass at the new map
properties came back with `winner_war`/`winner_fundraising_component`
null for all 160 current-vintage House districts — every one of them,
not a handful, which is what gave away that this was a real wiring gap
and not just a lot of uncontested races.

Fixed by splitting `publish_combined` into a pure `_combined_features`
(feature-list builder, takes an already-built `records: list[dict]`) and
`write_combined_from_records` (writes the FeatureCollection from those
records), and having `generate_site_data.py`'s own `main()` call
`write_combined_from_records` directly, once per (chamber, vintage) it
actually processed, right after both the state and U.S. House WAR fits
are applied and merged — so the combined map's WAR fields are always the
same already-resolved values every other page on the site shows, with no
second, independently-maintained computation that could drift from them.
This does mean `publish_district_geo.py` now imports nothing new but
`generate_site_data.py` needs to import *from* `publish_district_geo.py`
too (for `write_combined_from_records`) — a real circular import, since
`publish_district_geo.py` already imports `build_district_records`/
`district_slug`/`district_url` from `generate_site_data.py` at its own
top level. Resolved with a deferred, function-body import inside
`main()` rather than restructuring the shared code into a third module:
by the time `main()` actually runs, both modules are already fully
loaded, so the late import works fine and is the smaller diff.
`publish_district_geo.py`'s own CLI (`publish_combined`) still works
standalone — useful for reproducing the map's lean/competitiveness
coloring without the rest of the pipeline — just with every WAR field
null, which its own docstring now says explicitly rather than leaving a
future reader to rediscover the same gap.

New per-feature GeoJSON properties (all from that district's most recent
tracked year's *winner*, not an average across the whole race — "how did
the person who actually won perform on this factor" is the more legible
statewide-map question, and matches what that same race's own attribution
chart on the district/candidate page already shows for the winner):
`latest_year`, `is_uncontested`, `turnout_ratio`, `winner_name`,
`winner_party`, `winner_war`, `winner_lean_component`,
`winner_tide_component`, `winner_incumbency_adjustment`,
`winner_demographics_component`, `winner_fundraising_component`. A metric
only appears in a given map's own dropdown if at least one loaded feature
actually has a non-null value for it (computed client-side from the
loaded FeatureCollection, not hardcoded per chamber) — so U.S. House's
map never offers "Campaign fundraising" (no FEC data fetched this
project) or "District demographics" outside the current vintage (Census
matching only ever covers the current vintage — see the demographics
section above), rather than showing an option that silently does
nothing.

The diverging color ramp (teal `#0f7a7a`/orange `#c9660a`, light mode;
`#28a3a3`/`#e08a3a`, dark — neutral gray midpoint at each metric's own
"no effect" value, 0 for a WAR component or 1.0 for turnout ratio) was
chosen and validated via the dataviz skill's `validate_palette.js`
(`--pairs all` against the two poles: CVD ΔE 12.6 protan / 24.4 normal,
comfortably clear of the ≥8 floor) specifically to avoid the existing
dem/rep blue-red pair, which would misread a non-partisan magnitude like
"fundraising's contribution to WAR" as a partisan signal — the same
reasoning the pre-existing `--war-*` attribution-chart colors are already
built on. New `--map-diverging-neg`/`--map-diverging-pos` CSS custom
properties (light + dark), reusing the existing `--gridline` token as the
neutral midpoint rather than adding a third dedicated color, since "no
measurable effect" should carry the same visual weight as this page's own
gridlines, not a distinct hue.

Verified live: a full `generate_site_data` run wrote all 9 combined
GeoJSON files (3 chambers × 3 vintages) with real, non-null
`winner_war`/`winner_fundraising_component` values wherever the
underlying race actually supports them — 29/160 current-vintage House
districts have a non-null winner WAR (the rest are uncontested,
correctly null, not a bug); a Playwright sweep of `/map/` confirmed all
three maps render with working toolbars, switching the metric selector
recolors the fill and legend correctly (House's fundraising map showed a
believable ±6.8-point range for the 2022-present vintage), switching the
vintage selector reloads that chamber's older boundaries and correctly
recomputes the metric domain/legend from the newly-loaded data alone
(2001-2010's own fundraising range came back as a different, real ±8.1
points, not a stale copy of the prior vintage's range) while preserving
the current metric selection whenever it's still available in the new
vintage's data — zero non-tile-related console errors throughout (the
sandbox's pre-existing basemap-tile network restriction, unrelated to
this feature, aside).
