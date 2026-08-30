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
  - *Different baseline inputs*: v1 baseline = district partisan lean only
    (§ above), and is still what WAR's *expected*-share calculation
    actually uses today. Incumbency and OCPF campaign finance are now both
    tracked and matched to candidates (see `pipeline/README.md` — a
    candidate's own accumulated results, and a real name/district match
    against OCPF's filer roster, respectively) and shown throughout the
    site, but neither is folded into WAR's expected-value formula itself
    yet — that "v2" regression, same spirit as Split Ticket's model but
    this project's own weighting, not theirs, is still a real next step,
    not done.
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

## 12. Phased Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Repo scaffold, finalize schema, confirm district vintages | **Done** — Python pipeline package + Jekyll site skeleton + Actions build/deploy workflow, all verified to actually build. |
| 1 | Data pipeline: results + boundaries + demographics + campaign finance + crosswalks, back to at least the 2001 vintage (≈24 years) | Fetchers + crosswalks **verified against live data** for all three vintages (see `pipeline/README.md` for exact numbers: elections, boundaries incl. the MIT-sourced 2001 vintage, PL94-171/ACS demographics, OCPF finance, town↔district overlap, seat lineage). Demographics and campaign finance are now **surfaced on the site**, not just fetched — see rows 2 and 4 below. The full multi-decade election-results backfill (2002-2024, both chambers, plus statewide governor/president baselines) is running as a long background job — see `pipeline/README.md` for status once it completes. |
| 2 | Jekyll + Actions skeleton, entity pages, navigation, theming | Seat, district, candidate, town, and party entity pages **done and verified live**, including a top-level index page for each (`/district/`, `/candidate/`, `/town/`, `/party/`, alongside the existing `/chamber/{house,senate}/`), a `/methodology/` page explaining lean and WAR, and site-wide sortable tables — real jekyll build, walked the actual link chain in a browser. Seats now carry a `history` section linking back through prior redistricting vintages via seat_lineage. District and seat pages now show a **Demographics** section (2020 Census population + ACS 5-year income/education, current vintage only — see `pipeline/README.md`), and candidate pages show a **Campaign finance** section (OCPF totals by year). Real theming (beyond the placeholder palette) not started. |
| 3 | Core interactive charts (map, line, bar, scatter, histogram) with click-through | Scatter/strip plot **done and verified live**: district-lean-by-seat chart on each chamber page, click-through confirmed with an actual browser (Playwright) — clicking a point navigates to that seat's page, screenshotted for both chambers. District/seat pages render a **map** of the district's own boundary (MapLibre GL JS, GeoJSON published per district-vintage), colored by favored party. A **statewide overview map** (`/map/`, docs/PLAN.md §5's "statewide map landing page") now shows every district in a chamber at once, colored by lean/competitiveness, click-through to that district's page — verified live: real Massachusetts geography renders correctly (Republican-leaning districts cluster in western MA and south of Boston, matching the state's actual political geography), and a real click-through test caught and fixed a genuine bug (a district URL missing the deployment's baseurl prefix, landing on a 404 — see `pipeline/README.md`). The free CARTO basemap tiles underneath both map types aren't reachable from this session's network policy to verify directly (real browsers reach them). Line and a true (binned) histogram form not started; a search/compare tool (also named in §5) not started. |
| 4 | Derived analytics: WAR (adapted), lean, competitiveness, turnout, incumbency | Lean, competitiveness, WAR, turnout, and incumbency all **built and verified live** against real 2022 House+Senate data (see `pipeline/README.md`) — apportioned statewide share reconstructs the true Governor result exactly, competitiveness matches MA's known partisan lean, all 200 district names matched with zero mismatches after fixing a real wrong-match bug, turnout_ratio computed from data already on hand (no new fetching needed), and incumbency/open-seat status derived from this site's own accumulated multi-year results (verified with a synthetic two-year test ahead of the real backfill). Surfaced on seat/district pages, a new chamber-page "At a glance" summary (contested-race rate, incumbent win rate, open-seat count), and in AskAI's queryable tables/example queries. Three documented, not-yet-addressed limitations: WAR is mechanically inflated for uncontested races (flagged via an `is_uncontested` column, not fixed); lean and turnout_ratio use area-weighted rather than population-weighted town↔district apportionment; and incumbency isn't chased across a redistricting-vintage boundary (a deliberate scope choice, not an oversight — see the methodology page). Not yet built: incumbency/finance as actual WAR regression inputs (the "v2" baseline). |
| 5 | AskAI: semantic layer + DuckDB-Wasm + AI SDK (multi-provider) React sidebar | Built and mostly verified live (see `pipeline/README.md`'s AskAI section): the SQL safety guard and real DuckDB query execution against real published data, and the sidebar UI (toggle, BYOK settings, per-provider key storage, chat loop reaching a real `fetch()` against a provider API) all confirmed in a real headless browser — including two real bugs caught and fixed that way. Not verified: an actual LLM round-trip (no provider API key/network access from this session) and the DuckDB-Wasm browser bundle's jsDelivr/extensions.duckdb.org loading path specifically. |
| 6 | Polish: accessibility, performance, update-script docs | Not started. |

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
