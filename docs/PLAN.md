# MA Political Analytics Dashboard — Design Plan

A static, zero-cost, GitHub Pages–hosted analytics site covering Massachusetts
state-level races (House of Representatives + Senate): a stat-dense,
methodology-transparent presentation layer with a headline metric per
candidate, sortable leaderboards, and full click-through between entities.

## 1. Goals & Scope

- All MA state legislative seats (160 House districts, 40 Senate districts),
  current and historical, across at least 3 redistricting cycles (≥20 years).
- Entities: Candidate, Race, Seat, District (vintage-specific), Chamber,
  Party, Town.
- Core analyses: WAR (wins above replacement, adapted — see §4), vote share
  over time, district partisan lean over time, lean-distribution histograms,
  competitiveness, incumbency effects, turnout.
- Interactive, click-through charts and maps; per-entity pages.
- "AskAI" BYOK assistant, sidebar, context-aware, chart-generating.
- $0 operating cost, hosted entirely on GitHub Pages.

## 2. Data Sources

| Data | Source | Notes |
|---|---|---|
| Election results (candidate, vote counts, party, stage) | [PD43+ / electionstats.state.ma.us](https://electionstats.state.ma.us) | Official Secretary of the Commonwealth DB, covers 1970–present, stable per-election URLs, no bulk API → needs a polite scraper. Pre-1970 available as scanned PD43 volumes if we want to push past 1970 later. |
| Cross-check / standardized format | [MEDSL / OpenElections](https://github.com/MEDSL) | Use to validate scraped totals where coverage overlaps. |
| District boundaries | [MassGIS Legislative Districts](https://www.mass.gov/info-details/massgis-data-massachusetts-house-legislative-districts-2021) | Separate House/Senate shapefiles per redistricting cycle: **2001** (used 2002–2010), **2012** (2012–2020), **2021** (2022–present). This is our natural "vintage" boundary. |
| Precincts (for lean baselines) | MassGIS Voting Precincts + town-level general election returns | Needed to build a partisan-lean baseline independent of legislative results (see §4). |
| Demographics | Census PL 94-171 redistricting data (population by state legislative district, published per vintage) + ACS 5-year for finer-grained attributes | PL 94-171 gives exact totals for the *current* vintage; historical vintages require areal interpolation of block-level census data onto old district polygons (GeoPandas overlay). |
| Towns / municipal boundaries | MassGIS Community Boundaries (351 municipalities) | Town↔district crosswalk built per vintage via GIS overlay (a town can span multiple districts, especially Boston). |
| Candidate bios / incumbency | Official state legislature member directory, Wikipedia, Ballotpedia (light touch, respect ToS) | Enrichment only; election results remain authoritative for outcomes. |
| Campaign finance | OCPF bulk data (`ocpf2.blob.core.windows.net/downloads/data2/`) — `ocpf-{year}-reports.zip` (report + line-item detail) and `ocpf-filers.zip` (`all_filers.txt`: every House/Senate filer, active and closed, with a `cpfId`) | This is a real public bulk export, not a scrape — no auth, tab-delimited. No longer a "stretch" source; promoted to core (see §9 for the parsing gotchas). |

## 3. Data Model / Semantic Layer

Redistricting is the central modeling challenge. Design:

- `district_vintage`: `{2002-2010, 2012-2020, 2022-present}` (extendable).
- `District(chamber, district_name, vintage)` — geometry + demographics are
  vintage-scoped; never mutate a past vintage's shape.
- `SeatLineage`: best-effort mapping of a district in one vintage to its
  nearest successor(s) by population/area overlap (computed once via
  GeoPandas overlay, stored as a static crosswalk table with an overlap
  %). Powers "seat over time" trend charts across redistricting boundaries,
  with a visible caveat where continuity is approximate.
- `Race(seat, vintage, year, stage)` where `stage ∈ {primary, general}`.
- `Candidacy(race, candidate, party, votes, incumbent_flag)`.
- `Candidate(id, name, ...)` — one durable identity across all their races.
- `Town`, and `TownDistrictOverlap(town, district, vintage, pop_share)`.

Everything is precomputed at build time into flat **Parquet + JSON** files
(no live database), partitioned by vintage/chamber/year to keep per-page
payloads small.

## 4. Analytics Definitions

- **District partisan lean**: two-party Democratic share of a blended
  top-of-ticket baseline (Governor, President, AG in on-years) aggregated
  from town/precinct returns into each district's geography per vintage.
  Kept independent of the legislative race itself so it can serve as a
  "replacement level."
- **WAR (wins above replacement) — adapted for MA state legislative races.**
  This is not an original idea: it follows the "fundamentals-based expected
  margin vs. actual margin" approach published as **WAR** by the independent
  election-analytics outlet Split Ticket (federal races, since ~2022), which
  is itself the applied/journalistic descendant of a real academic
  literature — Gelman & King (1990, *AJPS*, "Estimating Incumbency Advantage
  Without Bias") on decomposing vote share into normal-vote (district
  partisanship) + incumbency + national-tide terms; Ansolabehere, Snyder &
  Stewart (2000, *AJPS*) on isolating the "personal vote"; Squire (1989,
  1995) and Jacobson on candidate-quality effects specifically in
  (state) legislative races; and the "candidate valence" literature (Stone &
  Simas 2010) that treats this residual as a measurable quantity.
  **We are explicitly adapting, not replicating, Split Ticket's method** —
  differences worth tracking as assumptions, not hidden:
  - *Different population*: state legislative (House/Senate), not federal —
    smaller electorates, more uncontested races, thinner polling/finance
    data per race.
  - *Different baseline inputs*: **v1** baseline = district partisan lean
    only (§ above). **v2** (built — see `generate_site_data.fit_war_v2_core`/
    `apply_war_v2`) is now a real multi-term regression, fit *Bayesian*
    rather than by OLS (a hand-rolled Gibbs sampler, `_bayesian_linear_regression`
    — no PyMC/statsmodels dependency): `own-party share ~ intercept +
    district lean + statewide tide + incumbency (1st/2nd/3rd+ term)`,
    with weakly informative, regularizing priors on every coefficient —
    real regularization for a correlated lean/tide pair and unevenly-sized
    incumbency buckets, and a full posterior (mean, SD, 95% credible
    interval), not just a point estimate. Fit on every contested
    major-party race in the full 2002-2024 backfill — see
    `site/_data/war_v2.yml` for the live coefficients and the methodology
    page for the full writeup, including a real, checked-against-plain-OLS
    finding (lean's coefficient sits well below 1.0, not assumed away).
    Two further diagnostic extensions — **v3** — add demographics and
    campaign finance on top of the same core model, but aren't threaded
    into every candidate's WAR the way v2 is: demographics only cover the
    current (2022-present) vintage's two election years, and even after
    backfilling OCPF's finance export to the full 2002-2024 range (see §4
    row below), only a fraction of candidate-races have a confident OCPF
    match — both reported as labeled diagnostics on the methodology page
    instead (coefficients + posterior uncertainty + real sample sizes),
    not silently dropped, not forced onto data too thin to support them.
    The finance diagnostic itself got substantially stronger from that
    backfill: n=1,069 candidate-races across 12 election years (up from
    87 in one year), `own_tide` restored as a real term now that genuine
    cross-year variation exists to identify it against, and a clearly
    nonzero, positive coefficient on logged fundraising. Both WAR v1 and v2 are shown
    throughout the site (district/seat/candidate pages), not just v1.
  - *Different redistricting handling*: our lean baseline has to cross three
    MA redistricting vintages; Split Ticket's federal-district baseline
    doesn't face this problem at the same scale.
  `WAR = actual two-party vote share − expected share from the fundamentals
  baseline` (in margin terms, doubled). Reported per-race and as a
  career/percentile aggregate. The methodology page ships with this
  provenance and the citations above — never presented as a novel invention.
- **Vote share over time**: per-candidate line/bar across cycles.
- **District lean over time**: per-district line, annotated at
  redistricting boundaries (dashed/break in the line between vintages).
- **Lean histogram by seat**: distribution of all seats' lean for a given
  chamber/year — surfaces packing/cracking patterns.
- **Competitiveness index**: e.g. Cook PVI–style bucketing (Safe/Likely/
  Lean/Tossup) derived from lean + margin volatility.
- **Incumbency & turnout**: contested-race rate, open-seat vs. incumbent
  win rate, turnout by district/town relative to statewide.

## 5. Site Structure (per-entity pages)

`/chamber/{house|senate}/`, `/seat/{chamber}/{district}/` (with a vintage
switcher), `/district/{chamber}/{district}/{vintage}/`, `/candidate/{id}/`,
`/party/{party}/`, `/town/{town}/`, plus a statewide map landing page and a
search/compare tool. All pages generated at build time — thousands of
static HTML files is fine on Pages.

## 6. Visualization Stack

- **Charts**: Vega-Lite (declarative, built-in selections, and a mark can
  carry an `href` so a click natively navigates to the candidate/seat page
  — no custom JS needed for the common case; custom D3 only where Vega-Lite
  can't express something). **Implemented and verified live** for the
  chamber pages' district-lean strip plot: real click-through confirmed
  with an actual browser (Playwright) — clicking a point navigates to that
  seat's page. Vega/Vega-Lite/Vega-Embed are vendored (`npm install`, UMD
  builds copied into `site/assets/js/vendor/`) rather than loaded from a
  CDN at runtime — found live that a CDN dependency is one more thing that
  can go down or get blocked (this session's own network policy blocked
  `cdn.jsdelivr.net` while `registry.npmjs.org` was already allowed), and a
  self-hosted static asset is simpler to reason about for a site with no
  build-time bundler yet anyway. Found and fixed a real CSS gotcha in the
  process: vega-embed's own stylesheet sets `display: inline-block` on its
  container, which collapses to zero width when combined with a chart
  spec's `"width": "container"` autosize — needs an explicit `display:
  block; width: 100%` override (see `site/assets/css/main.css`).
- **Maps**: MapLibre GL JS + precomputed TopoJSON per vintage (simplified
  with `mapshaper` to keep files small), choropleth by lean/competitiveness,
  click → seat page.
- **Ad hoc querying**: DuckDB-Wasm loaded client-side over the same Parquet
  files, so both the AskAI feature and any "explore the data yourself"
  widgets run real SQL in-browser with zero server.

## 7. Static Site Framework (GitHub Pages, $0)

Recommend **Jekyll + GitHub Actions build** (rather than the Pages-native
Jekyll build) because generating thousands of entity pages and shipping
Vega-Lite/DuckDB-Wasm assets needs plugins/build steps the native Pages
Jekyll build won't allow. A `deploy.yml` Actions workflow that runs `bundle
exec jekyll build` then `actions/deploy-pages` is free and unlimited-minute
for a public repo. (Astro/Eleventy would also work and arguably template
data-driven pages more naturally — worth a quick spike before committing,
but Jekyll satisfies the ask and keeps the toolchain simple.)

## 8. AskAI (BYOK) Feature

- Hidden sidebar, toggle always available, persists across pages. Built as a
  small **React island** (an isolated component tree mounted into an
  otherwise plain Jekyll page) — the only part of the site that needs a
  component framework and a client-side agent loop; the rest of the site
  stays static HTML.
- **Provider abstraction — Vercel AI SDK (`ai` npm package).** Rather than
  hand-rolling per-provider request/response shapes, use `ai` core
  (`generateText`/`streamText`) with the official adapter packages:
  `@ai-sdk/anthropic`, `@ai-sdk/openai`, `@ai-sdk/google` (Gemini), and
  `@ai-sdk/groq`. Each adapter exposes the same `LanguageModel` interface, so
  the app picks a factory at runtime from the user's provider + key choice —
  this *is* the abstraction layer, we don't need to write one. User pastes
  their own key into a settings panel; stored **only** in `localStorage`,
  never touches any server we control. Requests go **directly from the
  browser to the provider**.
  - **CORS caveat to verify per provider before launch, not assume**:
    Anthropic supports direct browser calls via the
    `anthropic-dangerous-direct-browser-access` header; OpenAI's SDK exposes
    a `dangerouslyAllowBrowser` flag for the same. Google's Generative AI API
    and Groq's OpenAI-compatible API need to be checked directly — if either
    blocks browser-origin requests, the AI SDK's provider abstraction doesn't
    change that (it's a response-header issue on their end, not a client
    library issue). Fallback if needed: a minimal stateless relay on a
    separate free tier (e.g. a Cloudflare Worker) that only forwards
    bytes and never stores the key — still $0, just not GitHub Pages itself.
- **Agent / tool-calling loop — also the AI SDK, not a hand-written loop.**
  `streamText`/`generateText` accept a `tools` map plus a step limit and
  natively run the think → call tool → observe → continue cycle (a ReAct-
  style loop) until the model returns a final answer — no custom
  orchestration code needed. On the UI side, `@ai-sdk/react`'s `useChat`
  hook wires that loop straight into the sidebar's message list and handles
  in-flight tool-call state. (LangChain.js/LangGraph.js is the heavier
  alternative if we ever need multi-agent graphs; not needed for this
  single-assistant sidebar, and its bundle weight is a worse fit for a
  static site.)
- **Semantic layer**: a compact JSON data dictionary (entities, fields,
  metric definitions, current district vintages) plus the current page's
  context (which candidate/district/year the user is looking at) is
  injected as system context on every request.
- **Tools exposed to the model**: `query_data` (executes SQL via the
  in-browser DuckDB-Wasm instance over the prebuilt Parquet files, read-only
  connection, row cap, timeout, `SELECT`-only) and `render_chart` (emits a
  Vega-Lite spec that the page validates and renders inline). This lets
  "AskAI" answer with both data and a fresh plot, grounded in real numbers
  rather than hallucinated ones.

## 9. Data Pipeline

Python scripts under `/pipeline`, run manually (per requirement, no
scheduled automation required, though a manual `workflow_dispatch` Action
is a nice free convenience later):

1. `fetch_election_results.py` — scrape/update PD43+.
2. `fetch_district_boundaries.py` — pull MassGIS shapefiles per vintage.
3. `fetch_demographics.py` — Census PL 94-171 / ACS, interpolate to
   historical vintages.
4. `fetch_campaign_finance.py` — pull OCPF's bulk `ocpf-{year}-reports.zip`
   (report + line-item detail, tab-delimited) and `ocpf-filers.zip`
   (`all_filers.txt` — full candidate roster with `cpfId`, incl. closed/past
   filers, which is what makes matching *historical* candidates possible,
   not just current officeholders). Port (Python, MIT-license-compatible,
   credited in the script header) the report/record-type handling
   established by Code for Boston's MAPLE project
   (`codeforboston/maple`, `functions/src/ocpf/`) — their scraper encodes
   real, empirically-verified pitfalls we'd otherwise rediscover the hard
   way: Year-End and lifecycle (dissolution/transition) reports double-count
   periodic Bank Report totals if not excluded; Deposit Reports carry
   gross/pre-fee amounts already counted net in Bank Reports; non-
   contribution receipts (refunds) need netting out to match OCPF's own
   published totals; Credit Card/Reimbursement reports are supplemental and
   already reflected elsewhere. We do **not** read from MAPLE's live
   Firestore — it only holds the current 2-year cycle for sitting members,
   too narrow for our ≥20-year, all-candidates scope — we hit the same OCPF
   endpoint ourselves and match candidates via `all_filers.txt`
   (name + district + office, adapting their last-name/first-name/branch
   matching with ambiguity flagging, tightened using our race-level
   year/district data which they don't have).
5. `build_crosswalks.py` — town↔district and seat-lineage overlays.
6. `build_derived_metrics.py` — lean, WAR, competitiveness, turnout.
7. `generate_site_data.py` — emit per-entity Parquet/JSON + Jekyll data
   files consumed by page templates.

Each script is idempotent and accepts `--since-year`, so re-running after a
future election only touches new rows.

## 10. Cost Constraints — how we stay at $0

- Static HTML/JSON/Parquet only, no database, no server functions.
- GitHub Actions on a public repo: free, effectively unlimited standard
  runner minutes for the build+deploy workflow.
- Maps/tiles: MapLibre with self-hosted vector tiles (no third-party key or
  usage-based map API).
- AskAI inference cost is the user's own (BYOK) — we never proxy or pay for
  model calls.
- Watch payload size: lazy-load per-page data rather than one global bundle;
  keep total repo comfortably under Pages' size guidance.

## 11. Theming

Restrained institutional palette (civic, not flashy), a clear House/Senate
chamber split as the top-level nav, member-directory-style listing cards,
and a consistent search bar across sections, layered with a stat-dense
presentation on the analytics pages themselves: headline metric first,
methodology disclosed near the fold, small multiples preferred over single
large charts, sortable/searchable leaderboard tables as landing views, and a
visible per-metric methodology page throughout.

**Status**: all of §11 is now built. The House/Senate chamber split,
sortable leaderboard tables, headline-metric-first layout, and per-metric
methodology page were built earlier (see the Phased Roadmap below). A
**consistent search bar across sections** is built too: a compact search
box sits in the header on every page (`site/_layouts/default.html`),
backed by one shared JSON index (`/search/index.json`, generated once at
build time from `site.seats`/`candidates`/`towns`/`parties` rather than
embedded inline on every page — that would have added ~190KB to each of
this site's ~1,000 generated pages) and fetched lazily on first use, not
on every page load. Verified live: typing in the header box on a page
that isn't `/search/` itself (`/town/`) returns real matching seats and
candidates, and clicking one navigates correctly.

The **restrained institutional palette** and **member-directory-style
listing cards** are now built too. A fixed dark-navy masthead (`site/
_layouts/default.html`, `--masthead-*` tokens in `main.css`) gives every
page a persistent civic "letterhead" that deliberately does *not* flip
with the light/dark toggle — and deliberately isn't blue or red, since
this site's own chart palette already uses that exact pair to mean
Democratic/Republican; a partisan-colored masthead on a nonpartisan
analytics site would misread as an endorsement. A new page-plane/card-
surface distinction (`--surface-page`/`--surface-card`, both drawn from
the dataviz skill's own "page plane" vs. "chart surface" roles, not
invented) gives cards and stat tiles visible depth against the page.
**Member-directory-style cards** now replace the `/party/` index's table
(3 parties, each with a party-colored left border using the same
`--series-dem`/`--series-rep` chart tokens — legitimate here, since the
page is literally about parties) — deliberately *not* applied to the
282-candidate or 351-town listings, which stay sortable/searchable tables
per this same section's other instruction ("sortable/searchable
leaderboard tables as landing views" for stat-dense pages); a few hundred
unsorted cards would be a worse way to scan that many rows. New **stat-
tile KPI rows** (also `main.css`) replace the homepage's plain paragraph
and each chamber page's "At a glance" bullet list with headline-metric-
first tiles, matching §11's own "headline metric first" instruction.
Verified live in both light and dark mode (headless browser screenshots):
masthead, cards, and stat tiles all render correctly, real numbers
throughout (200 seats / 282 candidates / 351 towns on the homepage; a
seat/district page and the search dropdown both re-verified with no
regressions from the new header/footer markup).

## 12. Phased Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Repo scaffold, finalize schema, confirm district vintages | **Done** — Python pipeline package + Jekyll site skeleton + Actions build/deploy workflow, all verified to actually build. |
| 1 | Data pipeline: results + boundaries + demographics + campaign finance + crosswalks, back to at least the 2001 vintage (≈24 years) | Fetchers + crosswalks **verified against live data** for all three vintages (see `pipeline/README.md` for exact numbers: elections, boundaries incl. the MIT-sourced 2001 vintage, PL94-171/ACS demographics, OCPF finance, town↔district overlap, seat lineage). Demographics and campaign finance are **surfaced on the site**, not just fetched — see rows 2 and 4 below. The full multi-decade election-results backfill (House/Senate/Governor/President, 2002-2024) is **complete**: it moved from a local background process (which kept dying to sandbox idle-recycling) to a resumable GitHub Actions workflow (`.github/workflows/backfill.yml`) partway through, finished there in under an hour, and every downstream build step has been re-run against the full result — see `pipeline/README.md` for both the migration and a real candidate-name-resolution bug the full historical range surfaced (and fixed) that 2022-only data never exercised. |
| 2 | Jekyll + Actions skeleton, entity pages, navigation, theming | Seat, district, candidate, town, and party entity pages **done and verified live**, including a top-level index page for each (`/district/`, `/candidate/`, `/town/`, `/party/`, alongside the existing `/chamber/{house,senate}/`), a `/methodology/` page explaining lean and WAR, and site-wide sortable tables — real jekyll build, walked the actual link chain in a browser. Seats now carry a `history` section linking back through prior redistricting vintages via seat_lineage. District and seat pages now show a **Demographics** section (2020 Census population + ACS 5-year income/education, current vintage only — see `pipeline/README.md`), and candidate pages show a **Campaign finance** section (OCPF totals by year). **Real theming is now built** — see §11 below for the full writeup (institutional masthead, page/card surface distinction, member-directory cards, stat-tile KPI rows), verified live in both light and dark mode. |
| 3 | Core interactive charts (map, line, bar, scatter, histogram) with click-through | Scatter/strip plot **done and verified live**: district-lean-by-seat chart on each chamber page, click-through confirmed with an actual browser (Playwright) — clicking a point navigates to that seat's page, screenshotted for both chambers. District/seat pages render a **map** of the district's own boundary (MapLibre GL JS, GeoJSON published per district-vintage), colored by favored party. A **statewide overview map** (`/map/`, docs/PLAN.md §5's "statewide map landing page") now shows every district in a chamber at once, colored by lean/competitiveness, click-through to that district's page — verified live: real Massachusetts geography renders correctly (Republican-leaning districts cluster in western MA and south of Boston, matching the state's actual political geography), and a real click-through test caught and fixed a genuine bug (a district URL missing the deployment's baseurl prefix, landing on a 404 — see `pipeline/README.md`). The basemap tiles underneath both map types aren't reachable from this session's network policy to verify directly (real browsers reach them) — this already caught one real bug live: CARTO's free tiles, originally used on the documented assumption they needed no API key, turned out to require one in production (a real deployed screenshot showed "API KEY REQUIRED" placeholders), so both map scripts now use OpenStreetMap's own standard tile server instead — see `pipeline/README.md` for the full story and the light/dark-mode trade-off that came with it. A **search/compare tool** (`/search/`, §5) is now built and verified live: substring search across every seat, candidate, town, and party (a Jekyll-rendered JSON index, filtered client-side — no server or DuckDB needed for this), with an "Add to compare" flow on seats that renders a side-by-side table (lean, turnout, open-seat status, demographics) for up to two — real numbers confirmed for 1st vs. 2nd Barnstable District. A true **binned histogram** of district lean (5-point buckets, distinct from the existing strip plot) is now on every chamber page, and a **line chart** of a seat/district's own lean over time is now on every seat/district page — both verified live. The line chart was built while only 2022 data existed (one point per district, with an on-page note saying more would come) and needed no code change once the full backfill landed: a real 2001-2010-vintage district now shows a genuine 5-point line (2002-2010) with real year-to-year variance, confirmed live. |
| 4 | Derived analytics: WAR (adapted), lean, competitiveness, turnout, incumbency | Lean, competitiveness, WAR, turnout, and incumbency all **built and verified live**, first against 2022 House+Senate data and now against the complete 2002-2024 backfill (see `pipeline/README.md`) — apportioned statewide share reconstructs the true Governor result exactly, competitiveness matches MA's known partisan lean, all district names matched with zero mismatches after fixing a real wrong-match bug, turnout_ratio computed from data already on hand, and incumbency/open-seat status derived from this site's own accumulated multi-year results. The synthetic two-year test that verified incumbency logic ahead of the real backfill is now confirmed against real data too: a real seat's "At a glance" chamber summary shows a 99% (131/132) incumbent re-election rate, matching MA's well-known high incumbent-retention legislature — not a coincidence the test predicted the right shape of result. Surfaced on seat/district pages, a new chamber-page "At a glance" summary (contested-race rate, incumbent win rate, open-seat count), and in AskAI's queryable tables/example queries. Three documented, not-yet-addressed limitations: WAR v1 is mechanically inflated for uncontested races (flagged via an `is_uncontested` column, not fixed — visible live on a real candidate's WAR-over-time chart, where uncontested years spike); lean and turnout_ratio use area-weighted rather than population-weighted town↔district apportionment; and incumbency isn't chased across a redistricting-vintage boundary (a deliberate scope choice, not an oversight — see the methodology page). **WAR v2 is now built as a Bayesian fundamentals regression**: `own-party share ~ intercept + district lean + statewide tide + incumbency (1st/2nd/3rd+ term)`, fit via a hand-rolled Gibbs sampler (`generate_site_data.fit_war_v2_core`/`apply_war_v2`, no PyMC/statsmodels dependency) with regularizing priors and a full posterior per coefficient, on every contested major-party race in the full 2002-2024 backfill — see §4 above and `site/_data/war_v2.yml` for the live coefficients. Threaded through district, seat, and candidate pages: a "Replacement level over time" chart (lean baseline line + each candidate's actual result, click-through to the candidate), a "What drives replacement level" attribution chart (5 components — intercept, lean, tide, incumbency, and the WAR v2 residual — stacked, click-through to the candidate) on district/seat pages, and, on candidate pages, both a WAR v2-vs-expected-share-over-time chart and the same 5-component attribution chart broken out by year (click-through to the district for each race) — all verified live via Jekyll build + Playwright. Two further diagnostic regressions (**WAR v3**, `fit_war_v3_demographics`/`fit_war_v3_finance`) extend the core model with demographics and campaign finance, reported as labeled coefficients on the methodology page rather than threaded per-candidate — real coverage limits (demographics: current vintage only, 2 election years; finance: only candidates with a confident OCPF match), not an oversight. **OCPF campaign finance is now backfilled to the full 2002-2024 range** (`fetch.campaign_finance`, previously only ever actually run for 2022 despite already defaulting to the full range) — 28,824 filer-years across 23 years; candidate-page finance matches jumped from 219/1,343 (16%) to 942/1,343 (70%), and the WAR v3 finance diagnostic now fits on 1,069 candidate-races across 12 election years (up from 87 in one year) with `own_tide` restored as a real term. **The methodology page now visualizes WAR v2 directly, not just in prose/tables**: a forest plot of all six core coefficients with 95% credible intervals, an actual-vs-expected scatter across all 1,494 fitting-sample races (colored by party, with a 45° reference line), and a prior-vs-posterior density comparison for the 1st-term-incumbency coefficient making the Bayesian regularization concept concrete — all built from new pipeline exports (`site/_data/war_v2_fit_sample.yml`, prior mean/SD now included alongside posterior stats in `war_v2.yml`), verified live via Jekyll build + Playwright. **Both WAR v3 diagnostics got their own forest plots too** (asked directly: "why aren't demographics/finance in the coefficient chart") — the reusable `renderForestChart()` JS helper factored out of the WAR v2 plot now also renders the demographics extension's two added terms (its interval on the interaction term visibly crosses zero, matching the "not enough elections to trust this" caveat already in the text) and the finance extension's fundraising term alone, on its own x-axis scale (mixing it with lean/tide's much larger coefficients would have made a clearly-nonzero effect look like it hugs zero). **Standardized coefficients, full-parameter WAR v3 comparison charts, and v3-aware attribution with uncertainty** (asked directly, four-part: a full standardized parameter comparison across all of WAR v3's terms; candidate pages using v3; a plot type — or a companion one — showing attribution uncertainty; the same for district pages): `_bayesian_linear_regression` now also returns each coefficient's standardized ("beta weight") posterior — scaled by that predictor's own SD in the fitted sample — so a 0-1 continuous slope, a log-dollar slope, and a 0/1 incumbency dummy are all comparable in one "share points per 1 SD of predictor" unit; the methodology page renders one full-parameter standardized forest chart per WAR v3 diagnostic (all terms, not the trimmed subset the native-unit charts show), which also surfaced and fixed a real doc bug — the finance section's own prose/table had wrongly claimed the fit "drops the incumbency terms," when the code has always fit them alongside lean/tide/log_raised. Two new `apply_war_v3_demographics`/`apply_war_v3_finance` functions thread each diagnostic's own decomposition into distinctly-suffixed fields (`*_v3_demographics`/`*_v3_finance`, never overwriting v2's — a real clobbering bug caught before shipping, since v2 and v3 fit different coefficients on different samples) plus an approximate per-component uncertainty (delta method: `|covariate| × that coefficient's own posterior SD`, a documented simplification). District/seat pages' attribution chart now uses the demographics decomposition (with a combined "Education" slice) wherever a current-vintage demographics match exists, falling back to v2; candidate pages do the same with the finance decomposition (a "Fundraising" slice) for any year with a matched OCPF total. Every affected page also gets a new companion forest-style chart right below the existing stacked bar, showing the same components as a point + ~95% interval instead of just a point estimate — the "add both" option, since layering error bars directly onto a stacked bar's segments was judged too fragile to position correctly in Vega-Lite. A new `--war-extra` (violet) CSS variable covers the one shared 6th-component color (Education/Fundraising never coexist on the same chart). Verified live: components still sum exactly to `actual_two_party_share` across all 3,142 v2 rows, every `war_v3_demographics` row, and all 2,325 `war_v3_finance` rows (zero mismatches in any); a Jekyll build + Playwright sweep across a dozen district/seat/candidate/methodology pages came back with zero JS errors; and one honest caveat added to candidate pages — the Fundraising slice's raw log-dollar scale (typically 7-14, unlike lean/tide's natural 0-1 bound) can make it look disproportionately large next to the other segments, which the standardized comparison chart corrects for. **A year selector was added to the candidate uncertainty chart** (reported directly: the chart silently showed one hardcoded, unlabeled race) — it now lists every race with a real decomposition and defaults to the most recent, re-rendering on change. **WAR v3 demographics expanded to Hispanic-or-Latino population share, voting-age population share, and median household income** (asked directly, plus a graceful-fallback requirement: a district missing some Census fields should get a simpler model, not be dropped) — now fit as two tiers, core (bachelors_pct alone, needs only *a* population figure) and full (all four terms, needs a real PL 94-171 match); `demographics_match.py` now also surfaces ACS's own population figure (fetched but previously unused) as a fallback denominator, rescuing exactly the 15 Senate districts a PL 94-171 name-matching gap had excluded from WAR v3 entirely — all 200 current-vintage districts now get *something* (185 full-tier, 15 core-tier) instead of 170 getting everything and 30 getting nothing. **WAR is now null for an uncontested race** (v2 and both v3 diagnostics; asked directly, since it previously computed a mechanically-inflated number for unopposed candidates) — verified live across all 1,648 uncontested candidate-race rows. In its place, a new **baseline expectation** column (asked directly: "another metric that reflects baseline expectation... based on stats") surfaces `expected_two_party_share_v2`/`_v3_*` directly on every district/seat/candidate page's results table — always defined regardless of contested status, since it doesn't depend on the actual outcome, unlike WAR itself. Verified live: components still sum exactly to `expected_two_party_share_*` for every uncontested row and to `actual_two_party_share` for every contested one; a Jekyll build + Playwright sweep across both a full-tier and a core-tier district, the exact seat page a live screenshot had flagged as broken, and a candidate with both contested and uncontested races came back with zero JS errors and the expected visual behavior in each case. **A full-site review (asked directly: "I don't want the user to see war v1, v2, v3") led to consolidating all of this into one resolved WAR figure**, shown identically on chamber, party, district, seat, and candidate pages: two new pipeline functions, `apply_resolved_war_district`/`apply_resolved_war_candidate`, pick the richest model each specific race's own data supports — demographics-full > demographics-core > core on district/seat/chamber/party pages, finance > core on candidate pages, per race, never the raw v1 baseline — and attach a plain-language `war_factors` list (e.g. "Lean, tide, incumbency, demographics") alongside the number, so a reader sees what went into it without needing to know "v2"/"v3"/"core"/"full" internally. Chamber and party leaderboards, which had silently been showing the raw, uncontested-inflated v1 number unlabeled, now show the same resolved figure as every other page — the single worst inconsistency the review found, since those are the site's most-visited pages. District/seat/candidate results tables collapsed from separate WAR (v1)/WAR (v2)/WAR (v3) columns into one WAR + Expected share + Factors, and the methodology page's "WAR v2"/"WAR v3" section headers and prose were reframed as "The core regression model" and "Demographics and campaign finance extensions" (the underlying Bayesian fits, coefficients, and forest plots are unchanged — only the branding). The candidate page's attribution-chart year selector, added earlier for the opposite reason (it previously showed one hardcoded unlabeled race), was explicitly kept as-is per the request. Verified live: 0/3,142 mismatches between `war_resolved + expected_share_resolved` and `actual_two_party_share` on both the district and candidate sides; a Jekyll build + grep sweep confirmed zero remaining "WAR v1/v2/v3" text anywhere in the rendered site outside two intentionally-untouched surfaces — a code comment in `main.css` and AskAI's `schema.json`, whose `war`/`war_v2` are literal SQL column names a power user deliberately queries, not passive page prose. **Asked directly why the Fundraising bar looked disproportionately large next to lean/tide's** (a real observation, not a bug report — the raw log-dollar predictor typically runs 7-14, a completely different numeric scale than lean/tide's natural 0-1 fractions, so even a small fitted coefficient multiplied out to a large-looking bar), the per-race attribution charts were reworked from a raw coefficient*value decomposition to a reference-centered one: a new `_shapley_pair_split` helper fairly divides the bachelors_pct/tide interaction term between the Demographics and Statewide tide bars using the two-player Shapley value (previously the whole interaction was credited to Demographics alone), and `log_raised`/`income_10k` — the two predictors with no natural zero-effect baseline, unlike lean/tide/population-share fractions — are now centered on their own fit's mean, with the removed constant folded into a renamed "Baseline" bar (was "Intercept") instead of left in the fundraising/demographics bar. Real effect: Aaron Michlewitz's real $548k-raised 2024 race now shows an ~11-point Fundraising bar instead of one 3-4x that size, proportionate to lean/tide/incumbency rather than dwarfing them. The math is exact — `intercept_effective + lean + tide_component + incumbency + demographics/fundraising_component` still equals `expected_two_party_share_v3_*` to the same value as before the refactor (verified live: 0 mismatches across 500 district `v3_demographics` rows and 2,325 candidate `v3_finance` rows) — only which bar each dollar of predicted share lands in changed, not any candidate's actual WAR number. **A follow-up review of that fix asked whether the `bachelors_pct_x_tide` interaction it had just fairly split was itself principled** — it wasn't: it was the only interaction term anywhere in these models (finance's `log_raised`, with 12 real distinct election years, had never been tested for one at all), hand-picked because "diploma divide" is the term the realignment literature discusses rather than because the data supported it, and fit on just 2 distinct election years — thin enough that its own docstring already flagged it. **Removed entirely** (`_COEFFICIENT_PRIORS`, `_build_demographics_rows`, both `fit_war_v3_demographics_*` functions, and the now-dead `_shapley_pair_split` helper and its call site in `apply_war_v3_demographics`, deleted rather than left unused) in favor of a documented policy: no interaction with tide for any predictor until it has enough distinct election years to actually identify one (a rule of thumb, 4+), spelled out in a module-level comment above `_COEFFICIENT_PRIORS` so a future contributor sees the bar before adding one back. **The methodology page's WAR section was also rewritten** (asked directly, alongside the interaction removal): the old text read as an incremental build log — "had never threaded into any regression until now," "no longer collinear the way it was," "as an earlier version of this chart did" — replaced with a concise description of the current methodology only (that framing belongs here in PLAN.md, not on a public methodology page). A new **model-overview forest chart** (`war-overview-chart`) was added right after the intro, before any of the per-model detail sections: every fitted effect from every model — core lean/tide/incumbency, demographics' four terms, finance's fundraising term — plotted together on one standardized scale, colored by which model fits it, so a reader sees the whole picture before drilling into any one model's own coefficients/table/forest-plot/scatter (the page already had 6 charts; this is the 7th, and the one genuinely new one this round, built from three separate `site.data.war_v2`/`war_v3_demographics`/`war_v3_finance` sources bound to local JS consts once each rather than re-embedded per row). Verified live: pipeline re-run produced 0 mismatches on the same 500-district/2,325-candidate sum-invariant check as the prior round; a Jekyll build + Playwright sweep of the methodology page (confirming the new chart actually draws — canvas element present, non-zero dimensions, zero console errors) and both a full-tier and a core-tier district page came back clean. **Asked why some candidate-page attribution bars show no Incumbency slice, using a real long-serving senator (Bruce Tarr) as the example**: the answer was already correct and already documented (`incumbency_adjustment` is genuinely `0` for a race that's the first election under new redistricting maps — the methodology page's "Incumbency and open seats" section explains why incumbency isn't chased across a vintage boundary even for a real continuous incumbent), but nothing on the page itself pointed a reader at *why* a specific year looked that way. **Added a `is_redistricting_year` marker**: `build_candidate_records` now computes each vintage's own first tracked election year from the actual data (not hardcoded) and stamps it onto every race; `candidate.html`'s two year-spanning charts (the only charts on the site that can cross a vintage boundary within one page — a single district/seat page never does) now draw a shared dashed vertical rule at those years, with a tooltip and one sentence of prose pointing at the methodology page. The same follow-up asked **why Bruce Tarr had no campaign-finance data at all** despite being a real, long-serving, well-funded senator — investigated live rather than assumed: OCPF's own filer roster has him (cpf_id 11916, "1st Essex & Middlesex", exact last name and chamber match), but `campaign_finance_match.py`'s own district-name normalizer just lowercased and stripped punctuation, with no ordinal handling — so OCPF's numeral ordinal ("1st Essex & Middlesex") never collided with any of this site's three spelled-out vintage spellings ("First Essex and Middlesex District" / "First Essex & Middlesex District" / "First Essex and Middlesex"), silently excluding him across all 12 backfilled years. This is the same ordinal-mismatch failure mode `derived_metrics.match_district_names` already had a real fix for (found independently, in a different join, earlier in this project) — so rather than duplicate a second normalizer with a second subtly different gap, that ordinal-aware normalizer moved to the existing shared `util/names.py` (alongside `normalize_town_name`) as `normalize_district_name`, and both `derived_metrics.py` and `campaign_finance_match.py` now import the one shared implementation. Real, project-wide impact, not just Tarr: OCPF match rate jumped from 942/1,343 candidates (70%) to **1,105/1,343 (82%)**, and the WAR v3 finance diagnostic's fitting sample grew from 1,069 to **1,270 candidate-races** across the same 12 election years. Verified live: Tarr's own candidate page now shows a real, non-empty Campaign finance table for every year 2002-2024; the redistricting markers land exactly at 2002/2012/2022 on both his charts, with the Incumbency slice visibly absent only in those three years and present everywhere else; a Jekyll build + Playwright sweep of his candidate page came back with zero JS errors. **Also asked why incumbency's fitted effect looks like it decays after the first term** (term1 +15.65pts vs. term2 +14.61 vs. term3+ +14.36, from `war_v2.yml`): answered from the real posterior SDs rather than the point estimates alone — each term's 95% credible interval overlaps the others substantially (term1 [13.96,17.37], term2 [12.09,17.09], term3+ [12.1,16.61]), so the apparent decline isn't something this data actually distinguishes from noise, consistent with the methodology page's own existing conclusion that the three terms read as "fairly flat" rather than a real sophomore-surge-then-fade pattern — no code change, a real answer grounded in the fitted uncertainty rather than the raw numbers. **A follow-up round of methodology-page questions, three explained and one built.** (1) Why no orange "Statewide tide" bar ever appears on the forest charts: the demographics forest charts are colored `--war-tide` (amber) as a per-*chart* accent, unrelated to which *term* it is — they never include a "Statewide tide" row at all (only the added demographics terms), while the core regression's own forest chart, which does include the actual Statewide tide coefficient, is colored `--war-incumbency` (pink) instead. The methodology page's single-color forest charts use one accent per chart, not the district/candidate attribution charts' per-component legend — a real inconsistency between the two chart families, not fixed this round. (2) Why Bachelor's degree % appears on two plots: it's two different fitted values from two different regressions on two different samples — the core tier (bachelors_pct alone, n=200) and the full tier (bachelors_pct + 3 more terms, n=170) each re-estimate it independently rather than one borrowing the other's posterior, by design (documented on the page). (3) Why incumbency's point estimate differs across plots: each diagnostic (core, demographics, finance) re-estimates lean/tide/incumbency on its own sample rather than reusing the core model's coefficients — also already documented, but the page didn't call out that this means every table on the page can legitimately show a different number for "Incumbent, 1st term." (4) **Asked to plot Democratic vs. Republican model residuals**, suspecting systematic under-prediction of Democratic share from the existing scatter chart — confirmed, not imagined: computed live from `war_v2_fit_sample.yml` (Liquid can't do this kind of aggregate, so it's computed in the chart's own JS, same as the page's other derived numbers), Democratic candidates' residuals average **+5.3 points**, Republicans' average **-5.3 points** — equal and opposite, so the pooled mean is still exactly zero (guaranteed by the intercept), but the *within-party* means aren't. A new overlaid histogram (`war-v2-residual-histogram`) makes this visible directly, with per-party mean-lines and the live-computed point figures injected into the surrounding prose via two `<span>` placeholders. This isn't a break in the model's own-party symmetry (`own_lean`/`own_tide`/`actual_two_party_share` are each already computed from that specific candidate's own party's perspective) — it's a real limitation of pooling both parties into one shared coefficient set: a quick unpublished breakdown by party × incumbency (own_lean/own_tide/actual_two_party_share pulled directly from the district records, not from the trimmed fit-sample export) showed the bias concentrated in non-incumbents specifically — Democratic non-incumbents averaged +8.1 points, Republican non-incumbents -5.6, while incumbents of both parties were much closer to zero (+1.4 / -3.8) — and Massachusetts' real, lopsided legislative composition means those two subgroups make up very different shares of each party's races here (Democrats are incumbents 42% of the time in this sample, Republicans 13%). That incumbency-composition angle is stated on the page qualitatively (a true, well-known fact about MA's legislature), not as a numbered claim, since it isn't yet backed by its own pipeline-exported, reproducible figure the way every other number on this page is — a natural next step if this gets formalized further. **The three-model design (core + two diagnostic extensions) was replaced with one unified regression, closing the residual-asymmetry gap the round above had only measured** (asked directly, three-part: drop one of lean/tide and compute lean per-district instead of per-year; fold demographics/finance into terms that "zero out" for races without the data instead of separate models; then "do the thorough version"). `build_district_records` now also computes `lean_dem_share_structural` — the plain average of `lean_dem_share` across every year on record for that district within its vintage — and `fit_war_model`'s `own_lean` is built from this structural value instead of that specific year's own apportioned lean (own_tide is unchanged: still per-year, statewide, unapportioned), the Gelman & King "normal vote" split this page's own citations already point to, and less collinear with tide than two numbers both derived from the same year's baseline race used to be. `fit_war_v2_core`/`fit_war_v3_demographics_core`/`_full`/`fit_war_v3_finance` and their matching `apply_*`/`apply_resolved_war_*` functions are gone, replaced by one `fit_war_model`/`apply_war` pair: demographics (bachelors_pct/hispanic_pct/voting_age_pct/income_10k) and finance (log_raised) are now ordinary terms in the single fit, each centered on its own mean *among the rows that actually have it*, with a missing row filled with that same mean rather than a raw zero or an explicit indicator dummy — mathematically equivalent to "this term doesn't apply here," and, as a genuinely new capability the old three-separate-models design couldn't represent, lets one race carry both a Demographics and a Fundraising contribution at once (verified live: 29 of 191 sampled current-vintage candidate-races have both non-null simultaneously). Every core term (intercept, own_lean, own_tide, each incumbency bucket) also gets a `× Democratic` interaction term with its own prior, centered at 0 with half the width of its shared term's prior — a partial-pooling design chosen over either full pooling (the old design, which produced the +5.3/-5.3-point residual asymmetry measured above) or two fully separate per-party regressions. Real effect on that asymmetry, verified live from the refit `war_fit_sample.yml`: Democratic candidates' mean residual dropped from +5.3 points to **+0.02**, Republicans' from -5.3 to **-0.01**. `own_lean`'s own coefficient moved from 0.53 to 0.73 (structural lean is a cleaner signal than a single noisy year), and the fit's R² rose from 0.48 (core-only) to 0.73 (one model now absorbing what three separate, narrower fits used to). `main()`'s orchestration was reordered: a preliminary `build_candidate_records` call now runs before OCPF matching (needed to look up `finance_by_slug`, which `fit_war_model`/`apply_war` both need before `write_district_files`/`write_seat_files` can run), then a second, final `build_candidate_records` call after `apply_war` has populated every district record's WAR fields, so candidate pages inherit them via the existing copy-from-district-dict pattern; `publish_query_data.py`'s independent `build_results_table` was updated the same way (it fits its own copy of the model rather than reading back the written YAML, so it can't go stale relative to whatever data a given invocation has on disk) and gained `--current-vintage`/now uses `--ocpf-dir`/`--demographics-dir` for its own fit. All five templates' `V2_FIELDS`/`V3_FIELDS`/`useV3` branching collapsed into one `FIELD_MAP`/`CANONICAL_COMPONENTS` pair per page, with Demographics and Fundraising as two always-available (not mutually-exclusive) slots; a new `--war-fundraising` CSS color (light `#9725d0`/dark `#a73cdd`) was picked for the newly-independent Fundraising segment by running the dataviz skill's own `validate_palette.py` against the specific adjacent pairs it can land next to in the attribution stack, since the existing 8-hue reference palette was already fully spoken for elsewhere on these same pages (`--war-extra` plus the other five `--war-*` slots plus `series-dem`/`series-rep`). The methodology page's "The core regression model" and "Demographics and campaign finance extensions" sections were merged into one "The regression model" section (with a new "Party interaction terms" subsection) describing the single fit; the old three-source `war_v2`/`war_v3_demographics`/`war_v3_finance` YAML exports and `war-v2-forest-chart`/`war-v3-*` chart IDs were replaced by one `war_model.yml`/`war_fit_sample.yml` pair and matching `war-model-forest-chart`/`war-demographics-forest-chart`/`war-finance-forest-chart` IDs, and the model-overview forest chart now colors by term *family* (Core/Party interaction/Demographics/Campaign finance) within the one fit rather than by which of three separate models a term came from. Verified live: components still sum exactly to `expected_share_resolved` and `war_resolved + expected_share_resolved` to `actual_two_party_share` across a 191-race sample with zero mismatches; both `generate_site_data.py` and `publish_query_data.py` run cleanly end to end against the full 2002-2024 backfill; a Jekyll build + Playwright sweep of the methodology page (all 7 charts render, dem/rep residual notes populate), a district and a candidate page each showing simultaneous Demographics+Fundraising bars, plus chamber/party pages, came back with zero JS errors. **The three-bucket incumbency term (1st/2nd/3rd-or-later consecutive term) was simplified to a single incumbent/non-incumbent term** (asked directly — the 1st/2nd/3rd+ posterior means had already been observed, in an earlier round, to land close enough together that the split wasn't showing a real "sophomore surge" or later-term fade). `_incumbent_term_dummies`/`INCUMBENT_TERM_BUCKETS` (three dummies) replaced by `_is_incumbent_dummy` (one dummy, terms >= 1); `fit_war_model`'s feature list dropped from 17 parameters to 13 (`incumbent_1/2/3plus` + their `_x_dem` deltas, six terms, collapsed to `incumbent` + `incumbent_x_dem`, two); `apply_war`'s per-bucket coefficient lookup and "active bucket" branching collapsed to one coefficient pair. Real effect on the fit: R² essentially unchanged (0.7336 → 0.7327), `incumbent`'s posterior mean (+13.0 pts) sits within the old three buckets' own range (+11.1 to +13.5), and `incumbent_x_dem`'s 95% CI ([-0.078, -0.037]) stays clear of zero — the simplification didn't cost real explanatory power, consistent with the "small differences" observation motivating it. All five templates, the methodology page's formula/table/forest-chart/prior-posterior-chart term lists, and the AskAI schema card's incumbency-term prose were updated to match; `n_incumbent_1/2/3plus` replaced by `n_incumbent`/`n_non_incumbent` in `war_model.yml`. Verified live: components still sum exactly to `expected_share_resolved` across a 191-race sample; the Democratic/Republican residual fix from the round above still holds post-simplification (+0.02/-0.00, from +0.02/-0.01 before); a Jekyll build + Playwright sweep of the methodology page (forest/prior-posterior charts render with the new single-term list) and a district page's attribution chart (one Incumbency segment, not three) came back with zero JS errors. **Primary elections are now modeled, not just a display-only addition** (asked directly, prompted by the 2026 primary happening that week, with explicit direction: model it with incumbency/incumbency×tide/incumbency×lean/financials, give primary-only candidates full pages, keep special elections, and give the attribution charts shaded colors/special symbols for primaries and specials). `derived_metrics.compute_primary_results` is new: PD43+'s primary-stage races (`pd43.py` already fetched these every year — pre-existing, just unused) are grouped by `election_id` (not `(district, year, party)`, since a district can have both a regular and a special primary for the same party in the same year) and given `actual_primary_share = votes / field_total` against `fair_share = 1 / n_candidates` — a primary's own field-size-derived "no-information" baseline, playing the role `lean_dem_share` plays for the general model. `generate_site_data.fit_primary_war_model`/`apply_primary_war` fit a second, separate Bayesian regression (same `_bayesian_linear_regression` Gibbs sampler, five new `primary_*` priors): `excess_share ~ intercept + incumbency + incumbency × statewide tide + incumbency × district lean + campaign fundraising`, on 1,463 contested major-party primary candidate-races (R² = 0.27, 171 incumbent rows, 1,168 with a matched OCPF total) — incumbency alone here (+15.5 pts) reads meaningfully larger than the general model's own incumbency term, and, unlike the general model, tide/lean appear *only* as incumbency interactions, never as bare main effects, since there's no basis for claiming a non-incumbent's own primary share tracks statewide mood or district partisanship. Getting incumbency right at time-of-primary required a real bug fix: the first attempt reused the general model's own `incumbent_terms` field (which means "terms served *before* this general race"), which undercounted a sitting incumbent's own primary by exactly one term (caught live: Ann-Margaret Ferrante's 2024 primary showed `incumbent_terms: 0` despite being a genuine 1-term incumbent by then) — fixed by having `build_district_records`' existing terms-served backward walk also capture `winner_terms_after_year` (post-race state) and looking up the most recent general year strictly before the primary's own year. **Special elections are included for primaries, not (yet) for generals** — a deliberate, narrower scope than "keep special elections" alone might suggest, reasoned through and flagged to the user rather than assumed: a general already excludes specials (`compute_war`'s pre-existing `~is_special` filter, unchanged), and extending that to generals hit a real complication found live — 30-plus district-years across the 2002-2024 backfill already have *two* general races in the same calendar year (a special filling a vacancy plus that year's own regular-cycle election), which the current one-row-per-(district, year) incumbency-chain logic isn't built to represent safely; a primary has no such collision risk, since each is keyed to its own PD43+ `election_id`. **Primary-only candidates now get full candidate pages** — `build_candidate_records` gained a second loop appending primary race entries (`stage: "primary"`, distinctly-named fields like `actual_primary_share`/`primary_war`/`primary_war_factors` rather than overloading the general model's field names, since the two aren't on the same scale) alongside the pre-existing general-race entries, with `latest_info` (a candidate's display name/party) only ever set from a primary row as a fallback, never overriding a general-sourced one; real effect, candidate pages jumped from 1,343 to 2,045. District and seat pages gained a new "Primary results" section (parallel to "Election results," one sub-table per race, special-election races marked) — seat pages inherited it for free, since `build_seat_records` already spreads the full district-record dict. Candidate pages' two year-spanning charts were unified across stages per the explicit ask: the WAR-vs-replacement-level chart gained a second, unconnected point layer for primary races (constant `xOffset` next to that year's general point, `shape` encoding — diamond for a primary, triangle for a special-election primary — a real Vega-Lite shape legend, not just a color), and the attribution bar chart now field-maps a primary's `primary_baseline_component`/`primary_incumbency_component`/`primary_fundraising_component`/`primary_war` onto the same canonical Baseline/Incumbency/Fundraising/WAR-residual slots the general model already uses (no Lean/Tide/Demographics slice, since a primary has none of its own), dodged via a field-based `xOffset` on the `stage` field, shaded at reduced opacity for a primary bar, and outlined with a dashed stroke for a special-election one — no new CSS colors needed, since every primary component reuses an existing `--war-*` variable. The methodology page gained a new "Primary elections" section (formula, the excess-share/fair-share framing, the fitted coefficients as a table + forest plot + actual-vs-expected scatter from two new `site/_data/primary_war_model.yml`/`primary_war_fit_sample.yml` exports, the special-election-scope reasoning above, and one documented, accepted limitation: because excess share has no natural 0-100% bound, an uncontested incumbent's `primary_expected_share` can come out above 100%, visible directly on that candidate's own Races table — not capped, since capping it would hide rather than fix why it happens). Verified live: a real 2026 fetch (`pd43.py --year-from 2026 --year-to 2026`) pulled the actual special-election primaries already posted for the 5th Essex House and First Middlesex Senate seats; sum-invariant checks (component sums equal `primary_expected_share`; `actual − expected == primary_war`) passed with zero mismatches across 394 sampled candidate-races; a Jekyll build + Playwright sweep of a district page with a real 2026 special primary, a candidate with both a primary and general in the same year (Ann-Margaret Ferrante) and one with a 2026 special-election primary specifically (Ashley Sullivan), and the methodology page's two new charts came back with zero JS errors and the expected offset/shape/opacity/dash rendering in each case. |
| 5 | AskAI: semantic layer + DuckDB-Wasm + AI SDK (multi-provider) React sidebar | Built and mostly verified live (see `pipeline/README.md`'s AskAI section): the SQL safety guard and real DuckDB query execution against real published data, and the sidebar UI (toggle, BYOK settings, per-provider key storage, chat loop reaching a real `fetch()` against a provider API) all confirmed in a real headless browser — including two real bugs caught and fixed that way. Not verified: an actual LLM round-trip (no provider API key/network access from this session) and the DuckDB-Wasm browser bundle's jsDelivr/extensions.duckdb.org loading path specifically. |
| 6 | Polish: accessibility, performance, update-script docs | Not started, except one item: **large dollar amounts now render with thousands separators** ("$548,444" instead of "$548444") on candidate campaign-finance tables and district/seat median-household-income lines, via a new `number_with_commas` Liquid plugin (`site/_plugins/`) — Jekyll ships no such filter, but this site's `deploy.yml` runs `bundle exec jekyll build` directly rather than through GitHub Pages' restricted plugin whitelist, so a small custom filter was the simplest fix. Along the way, fixed a related pre-existing bug in `sortable-tables.js`'s numeric-aware column sort: it stripped `%` and `,` but never a leading `$`, so `parseFloat("$105220")` returned `NaN` and dollar columns always sorted lexicographically rather than numerically — confirmed live (a candidate's 8-year finance table now sorts $40,510 → $548,444 correctly both ascending and descending). |
| 7 | Federal election data: U.S. House + U.S. Senate | Added directly on request ("add in federal election data, Congressional and Senate votes... for ma specifically"), scoped via three explicit user choices: full district/seat/candidate treatment for U.S. House, a simpler results-only page for U.S. Senate (no WAR model — a single, staggered-term statewide seat has no "replacement level" the way a multi-seat chamber does), and no FEC campaign-finance fetcher this round (OCPF, this site's only finance source, doesn't cover federal filers). **Fetch**: `fetch.pd43` extended with `office_id` 5 (U.S. House, district-based, confirmed live against PD43+'s own search form) and 6 (U.S. Senate, statewide, staggered 6-year term — most even years return zero results, already handled gracefully by the existing per-year empty-search-skips-the-year logic); a new `fetch.congressional_boundaries` pulls MA's three congressional-district vintages directly from TIGER (10 districts 2001-2010 via a per-Congress `TIGER2010/CD/108/` archive not TIGER's regular per-year directories, 9 districts 2012-2020 via a whole-US per-Congress file filtered to MA's FIPS code, 9 districts 2022-present via a per-state file) — reformatted at fetch time from TIGER's own "Congressional District N" naming into PD43+'s own "Nth Congressional District" word order, a real matching bug found live (every one of the 9-10 districts failed to match under TIGER's native order even after this site's existing ordinal-aware name normalizer, since that normalizer strips ordinals but never reorders tokens). **Build**: `build.crosswalks` extended to a third chamber (`us-house`, town↔district overlap + cross-vintage lineage, reusing the same area-overlay machinery unchanged); `build.derived_metrics`'s `--chamber` choice widened the same way (its lean/WAR computation was already fully chamber-agnostic — no code change needed beyond the CLI). **U.S. House gets its own, separate Bayesian WAR fit** (`fit_us_house_war_model`/`apply_us_house_war` in `generate_site_data.py`) — the user's explicit choice over pooling it into the state House/Senate model, reasoned through directly: nine large, incumbent-dominated congressional districts are a different kind of race from 160+40 small state-legislative ones, and pooling a few hundred congressional rows into a fit trained on 1,500+ state rows would let the far larger sample dominate a coefficient meant to describe a different electorate. Same core-term shape as the state model (own-party lean/tide/incumbency with `× Democratic` interactions) with no demographics or fundraising extension (both real, documented gaps — no congressional-district Census crosswalk built, no FEC fetcher). Kept in a fully separate `district_records_by_vintage`-shaped dict from the state model's own training data until *after* both models have fit and applied, merged only afterward so every downstream consumer that doesn't care about the model split (district/seat/candidate file writers, town/party rollups) sees one combined roster; `main()`'s preliminary OCPF-matching pass runs before that merge specifically so a congressional candidate's name can never accidentally match a state filer. On the last full run: n=116 contested candidate-races (2002-2024), R²=0.89, own-lean +0.50, own-tide -0.01, incumbency +0.04 — sensible given MA's federal delegation is almost entirely safe Democratic seats with long-serving incumbents (little room for lean/tide to move outcomes, and modest measured incumbency advantage since serious challengers are rare). No separate primary model for U.S. House this round (same documented-gap reasoning as demographics/finance) — primary candidates on a congressional district page still show raw `actual_primary_share`/`fair_share`, no fitted overlay. **U.S. Senate** gets a dedicated `build_us_senate_records` (reads `fetch.pd43`'s `us-senate_races`/`results` parquet directly, no crosswalk or apportionment — there's no district to apportion into) rendering a new `/us-senate/` page (general + primary results tables, 2002-2024, real MA history including the 2009/2010 Kennedy-vacancy and 2013 Kerry-to-State special elections) from a new `site/_data/us_senate.yml` export. **Site**: `district.html`/`seat.html`/`candidate.html` needed zero changes (already fully chamber-agnostic, no hardcoded chamber assumptions found); `chamber.html` reused as-is for a new `/chamber/us-house/` page; three pages had a hardcoded `"house,senate"` chamber list that needed widening (`/district/`, and the `/map/` and `/party/`/`/candidate/` templates' own chamber-specific rendering) — a new shared `site/_data/chamber_labels.yml` (`house`/`senate`/`us-house`/`us-senate` → display label) replaces five separate `{{ x.chamber \| capitalize }}` call sites that would otherwise have rendered "Us-house" (`capitalize` only uppercases the first letter of whatever string it's piped, so a naive `default: x.chamber \| capitalize` fallback chain applied *after* a correct lookup was a real bug caught live — it was silently lowercasing an already-correct "U.S. House" label into "U.s. house" before the `\| capitalize` was removed from the found-in-lookup path). `publish_district_geo.py`'s chamber choice widened and re-run for `us-house`, and the statewide `/map/` page gained a third U.S. House map section (reusing `statewide-map.js` unchanged). Verified live via a full pipeline re-run (fetch → crosswalks → derived_metrics × 12 years → generate_site_data → publish_district_geo → Jekyll build) plus a Playwright sweep: `/chamber/us-house/` (9 seat rows), `/us-senate/` (10 general + 21 primary races, real candidate names/shares), a U.S. House seat page (Richard Neal's 1st Congressional District, full WAR trend/attribution/uncertainty charts and a real 2002-2024 race table), `/map/` (3 concurrent maps, no blank-second/third-map regression), `/district/` and a town page (both now listing Congressional districts alongside House/Senate) — zero console/page errors on any of them (the sandbox's pre-existing basemap-tile network restriction aside, unrelated to this feature). |
| 8 | Nav/design pass + statewide map variable & vintage selectors | Asked directly, two-part: "reorganize menu and generally check and update design, make it clear what context search bar applies to" and "add a selector to the maps so you can visualize any district-level inferred variable... also allow for vintage selection." **Nav**: the header had grown to 11 flat links (Home, House, Senate, U.S. House, U.S. Senate, Map, Districts, Candidates, Towns, Parties, Search & Compare, Methodology) plus a search box, wrapping to two rows even at 900px — screenshotted live before touching anything, confirming the problem rather than assuming it. Regrouped into two click-toggle dropdowns (`nav.js`, plain click/keyboard, not CSS `:hover` — a touch device has no hover state to trigger a hover-only menu, and this matches the click-to-open/click-outside-to-close pattern `search.js`'s own header-dropdown already uses rather than introducing a second convention): "Chambers" (State House/State Senate/U.S. House/U.S. Senate) and "Browse" (Statewide map/Districts/Candidates/Towns/Parties), leaving "Search & Compare" and "Methodology" as direct top-level links — down to 5 top-level items, confirmed to fit on one row even at 900px wide. **Search-bar clarity**: the header quick-search box had only a generic "Quick search…" placeholder, giving no indication it searches sitewide across seats/candidates/towns/parties (real ambiguity next to the separate `/search/` "Search & Compare" page and the floating "Ask AI" chat widget) — fixed with a persistent small label above the input ("Site search — seats, candidates, towns & parties," visible before *and* after typing, unlike a placeholder) and a concrete example placeholder ("e.g. '4th Middlesex' or a candidate name"). **Homepage** still described only "Massachusetts state legislative races" and its stat-row/quicklink-grid never mentioned U.S. House/Senate at all (added in row 7, but the homepage copy was never revisited) — updated prose, stat label, and quicklink grid to include both. **Statewide map** (`/map/`): each of the three chamber maps gained a "Redistricting vintage" selector (2001-2010/2012-2020/2022-present — geometry for all three was already published per chamber, just never wired to a control) and a "Color districts by" selector recoloring from the default partisan lean to any of seven district-level inferred variables — the most recent race's winner's own resolved WAR, its lean/tide/incumbency/demographics/fundraising components, and turnout ratio vs. baseline — with a live legend (gradient bar + min/center/max labels + a plain-language note) below each map. A metric only appears in a given map's own dropdown if at least one loaded feature actually has a non-null value for it, so e.g. U.S. House's map never offers "Campaign fundraising" (no FEC data fetched) or "District demographics" outside the current vintage, rather than showing an option that does nothing. The diverging color ramp (teal↔orange, neutral gray midpoint at each metric's own "no effect" value — 0 for a WAR component, 1.0 for turnout ratio) was chosen and validated via the dataviz skill's `validate_palette.js` (CVD ΔE 12.6 protan / 24.4 normal between the two poles, comfortably over the ≥8 floor) specifically to avoid the dem/rep blue-red pair, which would misread a non-partisan magnitude like "fundraising's contribution" as a partisan signal — a new `--map-diverging-neg`/`--map-diverging-pos` CSS token pair, validated separately for light and dark surfaces. Building this surfaced a real, previously-latent data gap: `publish_district_geo.py`'s combined-map GeoJSON was built by calling `build_district_records` directly, which never runs `apply_war`/`apply_us_house_war` (those live only inside `generate_site_data.py`'s own `main()`) — so every winner-WAR-component field this round added would have shipped permanently null. Fixed by splitting `publish_combined` into a pure `_combined_features`/`write_combined_from_records` pair that accepts already-built records from any caller, and having `generate_site_data.py`'s own `main()` call `write_combined_from_records` directly after both WAR fits are applied, once per (chamber, vintage) actually processed (a deferred, function-body import breaks the resulting circular import, since `publish_district_geo.py` already imports `build_district_records`/`district_slug`/`district_url` from `generate_site_data.py` at its own top level) — `publish_district_geo.py`'s own CLI (`publish_combined`) still works standalone for reproducing the map's lean/competitiveness coloring, just with null WAR fields, since it has no reason to also wire up tide/OCPF/demographics itself, and its own docstring says so. Verified live: a full `generate_site_data` run wrote all 9 combined GeoJSON files (3 chambers × 3 vintages) with real, non-null `winner_war`/`winner_fundraising_component` values wherever the underlying race actually supports them (e.g. 29/160 current-vintage House districts have a non-null winner WAR — the rest are uncontested, correctly null); a Playwright sweep of `/map/` confirmed all three maps render with working toolbars, switching a metric recolors the fill and legend correctly (a real House district's fundraising map showed a believable ±6.8-point range), switching a vintage reloads that chamber's older boundaries and correctly recomputes the metric domain/legend for the new data (2001-2010's own fundraising range came back as ±8.1 points, a different real number, not a stale copy) while preserving the current metric selection when it's still available; the nav dropdowns open/close on click and via Escape/click-outside, and the header search's persistent label and dropdown results both render correctly — zero non-tile-related console errors throughout (the sandbox's pre-existing basemap-tile network restriction is unrelated and unchanged). **Two follow-up fixes, both asked directly.** (1) The five component metrics were labeled "X's contribution to WAR," which is backwards: `apply_war`'s own arithmetic sums lean/tide/incumbency/demographics/fundraising into `expected_share_resolved` (the model's *prediction*), then `war_resolved = actual_two_party_share - expected_share_resolved` — WAR is exactly what those components leave unexplained, not a quantity they add up to (the existing district-page attribution chart already gets this right, labeling them "Lean"/"Tide"/"Incumbency"/"Demographics"/"Fundraising" as distinct from "WAR (residual)"). Relabeled all five to "X's contribution to expected vote share," fixed the same misstatement in the page's own prose and inline code comments, and simplified a legend-note string that had been redundantly concatenating "Most recent winner's own" in front of a label that itself started with "Most recent winner's." (2) A third selector, **Election year**, was added — its own options computed from whichever vintage is currently loaded (2001-2010/2012-2020 each offer 5 general-election years, 2022-present offers 2 so far), so a viewer can recolor the map from any specific past race, not just each district's most recent one. Required extending `publish_district_geo.py`'s `_combined_features` to emit a `years` list per district (one entry per election year on record for that vintage, each with its own lean/competitiveness/turnout/winner-WAR-component values — not just the latest year, which is all it emitted before) alongside the existing top-level fields (kept, mirroring the latest year, so any consumer that doesn't care about year selection still gets sensible defaults). `statewide-map.js` gained a client-side `flattenForYear(rawCollection, year)` that re-projects one year's own entry onto each feature's top-level properties, producing the FeatureCollection actually pushed to the map source — switching **Election year** re-flattens and calls `setData()` (no new fetch, no bounds refit, since geometry doesn't change within a vintage); switching **Redistricting vintage** re-fetches, repopulates the year dropdown from the new vintage's own `years` union, and preserves the selected year only if it's still valid for the new vintage's range (defaulting to its most recent year otherwise). Verified live: switching Election year on a House map recolors districts to that specific year's own lean (a real, visible change — e.g. one district that read Democratic-favored in 2024 came back closer to even in 2022); switching Redistricting vintage from "2022-present" to "2001-2010" correctly reset the year dropdown from `[2024, 2022]` to `[2010, 2008, 2006, 2004, 2002]` and re-rendered the older district boundaries with 2010's real, more Republican-favoring pattern (consistent with that year's actual midterm result) — zero console errors throughout. |

## Open Questions for You

1. OK with data starting at the 2001/2002 redistricting vintage (~24 years),
   or do you want a push toward 1970 (PD43+'s full range) despite the extra
   scraping/normalization work for older, less-structured records?
2. Provider priority for launch — all four (Anthropic/OpenAI/Gemini/Groq) at
   once, or ship one first and add the rest once the CORS behavior of each
   is confirmed?

## Appendix: Domains to Allowlist for Network Access

This session's outbound network is allowlisted, and none of the domains
below are on it yet — confirmed by both direct `curl` (blocked at the
container network policy level) and the WebFetch tool (blocked at a
separate layer; note WebFetch and in-container `curl`/`requests` go through
*different* egress paths — WebFetch reached `github.com` and, at one point,
`malegislature.gov` successfully even though this container's `curl` cannot
reach either directly, so "worked in chat via WebFetch" is not evidence a
pipeline script running in this container will be able to reach the same
host). The pipeline scripts (`requests`/`geopandas` running as plain
outbound HTTPS from this container) need the domains in the first group;
the last group is only relevant if you want to test the AskAI feature's
live provider calls from inside this environment — in production those
calls come from each end user's own browser, not from this container.

**Data sources (required to run `/pipeline` scripts):**
- `electionstats.state.ma.us` — PD43+ election results
- `www.mass.gov` — reachable, but its MassGIS dataset *pages* 403 every
  request regardless of allowlisting (Akamai bot-blocking, not our proxy) —
  don't rely on it as a fetch source, landing-page links only.
- `gis.data.mass.gov`, `maps-massgis.opendata.arcgis.com`,
  `geo-massdot.opendata.arcgis.com` — reachable for the HTML item pages, but
  **every actual download click on all three redirects to `hub.arcgis.com`**
  (confirmed live: `.../datasets/{id}_0.geojson` 302s to
  `hub.arcgis.com/api/download/v1/items/...`) — this is how the ArcGIS Hub
  product works regardless of which branded domain fronts it, not something
  a different MassGIS host works around. **Still needed: `hub.arcgis.com`**
  (and likely `www.arcgis.com` and `*.arcgis.com` service hosts — Esri
  shards feature services across per-org subdomains, so a single added host
  may not be enough; a wildcard is safer if your policy tooling supports
  one) for the shapefile bytes themselves.
- `arcgisserver.digital.mass.gov` and `hub.arcgis.com` — now reachable (both
  added). But live exploration turned up a real dead end, not just a
  network issue: **MassGIS's live catalog (both the self-hosted ArcGIS
  Server and the ArcGIS Hub search) no longer lists the 2001 vintage at
  all** — only 2012 and 2021 show up (confirmed via
  `AGOL/Legislative_Districts` on the self-hosted server and a
  `hub.arcgis.com` dataset search); it's been retired from both live
  catalogs, not just hard to find.
- `geodata.libraries.mit.edu` and `cdn.libraries.mit.edu` — **done**: both
  added and it worked. The catalog lives on the former; the actual
  shapefile zips are served from the latter, a separate host, found by
  reading the catalog page's own download link rather than guessing a
  pattern. One correction from the last pass: `gisogm:edu.harvard:b07d39bbd8fe`
  (found by web search) turned out to be the *wrong* House vintage — its own
  page says "Chapter 273 of the Acts of 1993," the redistricting *before*
  2001's — a trap since the title alone reads as generic. The right one,
  found via the site's own `/results` search, is `gismit:US_MA_F7HOUSE_2002`
  (MIT-hosted directly). District boundaries are now complete for all three
  vintages: 40 Senate + 160-161 House districts each, verified live.
- `api.census.gov` — Census API (PL 94-171 redistricting data, ACS). Domain
  is reachable, but **the API now rejects every request without a key**,
  confirmed live — even trivial ones. Free, instant signup at
  https://api.census.gov/data/key_signup.html; set the result as
  `CENSUS_API_KEY` (a GitHub Actions secret for CI runs). This needs you
  specifically, not something addable by network policy.
- `www2.census.gov` — Census bulk downloads (TIGER/Line). No key needed —
  confirmed live, and ended up solving district boundaries too (see below):
  TIGER/Line publishes the same SLDU/SLDL district shapefiles MassGIS does,
  as plain zip downloads, no ArcGIS dependency. Verified for the 2012 and
  2022 vintages; the 2001 vintage isn't available in this per-state zip
  form pre-2012 and needs more digging (or MassGIS, once unblocked).
- `ocpf2.blob.core.windows.net` — OCPF bulk campaign finance data (Azure
  Blob Storage, no auth)
- `raw.githubusercontent.com` and `objects.githubusercontent.com` — MEDSL/
  OpenElections cross-check data pulled from GitHub-hosted files/releases
  (`github.com` itself already appears reachable from this session)
- `en.wikipedia.org` — candidate bio enrichment
- `ballotpedia.org` — candidate bio enrichment
- `malegislature.gov` — current member directory

**Toolchain (required to install dependencies / build the site):**
- `registry.npmjs.org` — npm packages (AI SDK, Vega-Lite, MapLibre GL JS,
  DuckDB-Wasm, bundler)
- `rubygems.org` — Jekyll and its gem dependencies
- `pypi.org` and `files.pythonhosted.org` — Python packages (geopandas,
  pandas, requests, duckdb, etc.)

**Only if you want to test AskAI's live calls from this environment (not
needed for the pipeline or the site build):**
- `api.anthropic.com`
- `api.openai.com`
- `generativelanguage.googleapis.com` (Gemini)
- `api.groq.com`
