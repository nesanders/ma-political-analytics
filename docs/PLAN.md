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
| 4 | Derived analytics: WAR (adapted), lean, competitiveness, turnout, incumbency | Lean, competitiveness, WAR, turnout, and incumbency all **built and verified live**, first against 2022 House+Senate data and now against the complete 2002-2024 backfill (see `pipeline/README.md`) — apportioned statewide share reconstructs the true Governor result exactly, competitiveness matches MA's known partisan lean, all district names matched with zero mismatches after fixing a real wrong-match bug, turnout_ratio computed from data already on hand, and incumbency/open-seat status derived from this site's own accumulated multi-year results. The synthetic two-year test that verified incumbency logic ahead of the real backfill is now confirmed against real data too: a real seat's "At a glance" chamber summary shows a 99% (131/132) incumbent re-election rate, matching MA's well-known high incumbent-retention legislature — not a coincidence the test predicted the right shape of result. Surfaced on seat/district pages, a new chamber-page "At a glance" summary (contested-race rate, incumbent win rate, open-seat count), and in AskAI's queryable tables/example queries. Three documented, not-yet-addressed limitations: WAR v1 is mechanically inflated for uncontested races (flagged via an `is_uncontested` column, not fixed — visible live on a real candidate's WAR-over-time chart, where uncontested years spike); lean and turnout_ratio use area-weighted rather than population-weighted town↔district apportionment; and incumbency isn't chased across a redistricting-vintage boundary (a deliberate scope choice, not an oversight — see the methodology page). **WAR v2 is now built as a Bayesian fundamentals regression**: `own-party share ~ intercept + district lean + statewide tide + incumbency (1st/2nd/3rd+ term)`, fit via a hand-rolled Gibbs sampler (`generate_site_data.fit_war_v2_core`/`apply_war_v2`, no PyMC/statsmodels dependency) with regularizing priors and a full posterior per coefficient, on every contested major-party race in the full 2002-2024 backfill — see §4 above and `site/_data/war_v2.yml` for the live coefficients. Threaded through district, seat, and candidate pages: a "Replacement level over time" chart (lean baseline line + each candidate's actual result, click-through to the candidate), a "What drives replacement level" attribution chart (5 components — intercept, lean, tide, incumbency, and the WAR v2 residual — stacked, click-through to the candidate) on district/seat pages, and, on candidate pages, both a WAR v2-vs-expected-share-over-time chart and the same 5-component attribution chart broken out by year (click-through to the district for each race) — all verified live via Jekyll build + Playwright. Two further diagnostic regressions (**WAR v3**, `fit_war_v3_demographics`/`fit_war_v3_finance`) extend the core model with demographics and campaign finance, reported as labeled coefficients on the methodology page rather than threaded per-candidate — real coverage limits (demographics: current vintage only, 2 election years; finance: only candidates with a confident OCPF match), not an oversight. **OCPF campaign finance is now backfilled to the full 2002-2024 range** (`fetch.campaign_finance`, previously only ever actually run for 2022 despite already defaulting to the full range) — 28,824 filer-years across 23 years; candidate-page finance matches jumped from 219/1,343 (16%) to 942/1,343 (70%), and the WAR v3 finance diagnostic now fits on 1,069 candidate-races across 12 election years (up from 87 in one year) with `own_tide` restored as a real term. **The methodology page now visualizes WAR v2 directly, not just in prose/tables**: a forest plot of all six core coefficients with 95% credible intervals, an actual-vs-expected scatter across all 1,494 fitting-sample races (colored by party, with a 45° reference line), and a prior-vs-posterior density comparison for the 1st-term-incumbency coefficient making the Bayesian regularization concept concrete — all built from new pipeline exports (`site/_data/war_v2_fit_sample.yml`, prior mean/SD now included alongside posterior stats in `war_v2.yml`), verified live via Jekyll build + Playwright. **Both WAR v3 diagnostics got their own forest plots too** (asked directly: "why aren't demographics/finance in the coefficient chart") — the reusable `renderForestChart()` JS helper factored out of the WAR v2 plot now also renders the demographics extension's two added terms (its interval on the interaction term visibly crosses zero, matching the "not enough elections to trust this" caveat already in the text) and the finance extension's fundraising term alone, on its own x-axis scale (mixing it with lean/tide's much larger coefficients would have made a clearly-nonzero effect look like it hugs zero). **Standardized coefficients, full-parameter WAR v3 comparison charts, and v3-aware attribution with uncertainty** (asked directly, four-part: a full standardized parameter comparison across all of WAR v3's terms; candidate pages using v3; a plot type — or a companion one — showing attribution uncertainty; the same for district pages): `_bayesian_linear_regression` now also returns each coefficient's standardized ("beta weight") posterior — scaled by that predictor's own SD in the fitted sample — so a 0-1 continuous slope, a log-dollar slope, and a 0/1 incumbency dummy are all comparable in one "share points per 1 SD of predictor" unit; the methodology page renders one full-parameter standardized forest chart per WAR v3 diagnostic (all terms, not the trimmed subset the native-unit charts show), which also surfaced and fixed a real doc bug — the finance section's own prose/table had wrongly claimed the fit "drops the incumbency terms," when the code has always fit them alongside lean/tide/log_raised. Two new `apply_war_v3_demographics`/`apply_war_v3_finance` functions thread each diagnostic's own decomposition into distinctly-suffixed fields (`*_v3_demographics`/`*_v3_finance`, never overwriting v2's — a real clobbering bug caught before shipping, since v2 and v3 fit different coefficients on different samples) plus an approximate per-component uncertainty (delta method: `|covariate| × that coefficient's own posterior SD`, a documented simplification). District/seat pages' attribution chart now uses the demographics decomposition (with a combined "Education" slice) wherever a current-vintage demographics match exists, falling back to v2; candidate pages do the same with the finance decomposition (a "Fundraising" slice) for any year with a matched OCPF total. Every affected page also gets a new companion forest-style chart right below the existing stacked bar, showing the same components as a point + ~95% interval instead of just a point estimate — the "add both" option, since layering error bars directly onto a stacked bar's segments was judged too fragile to position correctly in Vega-Lite. A new `--war-extra` (violet) CSS variable covers the one shared 6th-component color (Education/Fundraising never coexist on the same chart). Verified live: components still sum exactly to `actual_two_party_share` across all 3,142 v2 rows, every `war_v3_demographics` row, and all 2,325 `war_v3_finance` rows (zero mismatches in any); a Jekyll build + Playwright sweep across a dozen district/seat/candidate/methodology pages came back with zero JS errors; and one honest caveat added to candidate pages — the Fundraising slice's raw log-dollar scale (typically 7-14, unlike lean/tide's natural 0-1 bound) can make it look disproportionately large next to the other segments, which the standardized comparison chart corrects for. **A year selector was added to the candidate uncertainty chart** (reported directly: the chart silently showed one hardcoded, unlabeled race) — it now lists every race with a real decomposition and defaults to the most recent, re-rendering on change. **WAR v3 demographics expanded to Hispanic-or-Latino population share, voting-age population share, and median household income** (asked directly, plus a graceful-fallback requirement: a district missing some Census fields should get a simpler model, not be dropped) — now fit as two tiers, core (bachelors_pct alone, needs only *a* population figure) and full (all four terms, needs a real PL 94-171 match); `demographics_match.py` now also surfaces ACS's own population figure (fetched but previously unused) as a fallback denominator, rescuing exactly the 15 Senate districts a PL 94-171 name-matching gap had excluded from WAR v3 entirely — all 200 current-vintage districts now get *something* (185 full-tier, 15 core-tier) instead of 170 getting everything and 30 getting nothing. **WAR is now null for an uncontested race** (v2 and both v3 diagnostics; asked directly, since it previously computed a mechanically-inflated number for unopposed candidates) — verified live across all 1,648 uncontested candidate-race rows. In its place, a new **baseline expectation** column (asked directly: "another metric that reflects baseline expectation... based on stats") surfaces `expected_two_party_share_v2`/`_v3_*` directly on every district/seat/candidate page's results table — always defined regardless of contested status, since it doesn't depend on the actual outcome, unlike WAR itself. Verified live: components still sum exactly to `expected_two_party_share_*` for every uncontested row and to `actual_two_party_share` for every contested one; a Jekyll build + Playwright sweep across both a full-tier and a core-tier district, the exact seat page a live screenshot had flagged as broken, and a candidate with both contested and uncontested races came back with zero JS errors and the expected visual behavior in each case. **A full-site review (asked directly: "I don't want the user to see war v1, v2, v3") led to consolidating all of this into one resolved WAR figure**, shown identically on chamber, party, district, seat, and candidate pages: two new pipeline functions, `apply_resolved_war_district`/`apply_resolved_war_candidate`, pick the richest model each specific race's own data supports — demographics-full > demographics-core > core on district/seat/chamber/party pages, finance > core on candidate pages, per race, never the raw v1 baseline — and attach a plain-language `war_factors` list (e.g. "Lean, tide, incumbency, demographics") alongside the number, so a reader sees what went into it without needing to know "v2"/"v3"/"core"/"full" internally. Chamber and party leaderboards, which had silently been showing the raw, uncontested-inflated v1 number unlabeled, now show the same resolved figure as every other page — the single worst inconsistency the review found, since those are the site's most-visited pages. District/seat/candidate results tables collapsed from separate WAR (v1)/WAR (v2)/WAR (v3) columns into one WAR + Expected share + Factors, and the methodology page's "WAR v2"/"WAR v3" section headers and prose were reframed as "The core regression model" and "Demographics and campaign finance extensions" (the underlying Bayesian fits, coefficients, and forest plots are unchanged — only the branding). The candidate page's attribution-chart year selector, added earlier for the opposite reason (it previously showed one hardcoded unlabeled race), was explicitly kept as-is per the request. Verified live: 0/3,142 mismatches between `war_resolved + expected_share_resolved` and `actual_two_party_share` on both the district and candidate sides; a Jekyll build + grep sweep confirmed zero remaining "WAR v1/v2/v3" text anywhere in the rendered site outside two intentionally-untouched surfaces — a code comment in `main.css` and AskAI's `schema.json`, whose `war`/`war_v2` are literal SQL column names a power user deliberately queries, not passive page prose. **Asked directly why the Fundraising bar looked disproportionately large next to lean/tide's** (a real observation, not a bug report — the raw log-dollar predictor typically runs 7-14, a completely different numeric scale than lean/tide's natural 0-1 fractions, so even a small fitted coefficient multiplied out to a large-looking bar), the per-race attribution charts were reworked from a raw coefficient*value decomposition to a reference-centered one: a new `_shapley_pair_split` helper fairly divides the bachelors_pct/tide interaction term between the Demographics and Statewide tide bars using the two-player Shapley value (previously the whole interaction was credited to Demographics alone), and `log_raised`/`income_10k` — the two predictors with no natural zero-effect baseline, unlike lean/tide/population-share fractions — are now centered on their own fit's mean, with the removed constant folded into a renamed "Baseline" bar (was "Intercept") instead of left in the fundraising/demographics bar. Real effect: Aaron Michlewitz's real $548k-raised 2024 race now shows an ~11-point Fundraising bar instead of one 3-4x that size, proportionate to lean/tide/incumbency rather than dwarfing them. The math is exact — `intercept_effective + lean + tide_component + incumbency + demographics/fundraising_component` still equals `expected_two_party_share_v3_*` to the same value as before the refactor (verified live: 0 mismatches across 500 district `v3_demographics` rows and 2,325 candidate `v3_finance` rows) — only which bar each dollar of predicted share lands in changed, not any candidate's actual WAR number. |
| 5 | AskAI: semantic layer + DuckDB-Wasm + AI SDK (multi-provider) React sidebar | Built and mostly verified live (see `pipeline/README.md`'s AskAI section): the SQL safety guard and real DuckDB query execution against real published data, and the sidebar UI (toggle, BYOK settings, per-provider key storage, chat loop reaching a real `fetch()` against a provider API) all confirmed in a real headless browser — including two real bugs caught and fixed that way. Not verified: an actual LLM round-trip (no provider API key/network access from this session) and the DuckDB-Wasm browser bundle's jsDelivr/extensions.duckdb.org loading path specifically. |
| 6 | Polish: accessibility, performance, update-script docs | Not started, except one item: **large dollar amounts now render with thousands separators** ("$548,444" instead of "$548444") on candidate campaign-finance tables and district/seat median-household-income lines, via a new `number_with_commas` Liquid plugin (`site/_plugins/`) — Jekyll ships no such filter, but this site's `deploy.yml` runs `bundle exec jekyll build` directly rather than through GitHub Pages' restricted plugin whitelist, so a small custom filter was the simplest fix. Along the way, fixed a related pre-existing bug in `sortable-tables.js`'s numeric-aware column sort: it stripped `%` and `,` but never a leading `$`, so `parseFloat("$105220")` returned `NaN` and dollar columns always sorted lexicographically rather than numerically — confirmed live (a candidate's 8-year finance table now sorts $40,510 → $548,444 correctly both ascending and descending). |

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
