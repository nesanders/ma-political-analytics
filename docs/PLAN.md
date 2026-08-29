# MA Political Analytics Dashboard — Design Plan

A static, zero-cost, GitHub Pages–hosted analytics site covering Massachusetts
state-level races (House of Representatives + Senate): a stat-dense,
methodology-transparent presentation layer with a headline metric per
candidate, sortable leaderboards, and full click-through between entities.

> **Note:** by request, no code or page text in this project names or credits
> specific third-party sites as design inspiration. Stylistic direction below
> is described in its own terms.

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
    (§ above); v2 adds incumbency (already in the data model) and OCPF
    campaign finance (now a real, obtained input — see §2/§9) as additional
    fundamentals, same spirit as Split Ticket's model but our own
    regression/weighting, not theirs.
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
  can't express something).
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

| Phase | Deliverable |
|---|---|
| 0 | Repo scaffold, finalize schema, confirm district vintages |
| 1 | Data pipeline: results + boundaries + demographics + campaign finance + crosswalks, back to at least the 2001 vintage (≈24 years) |
| 2 | Jekyll + Actions skeleton, entity pages, navigation, theming |
| 3 | Core interactive charts (map, line, bar, scatter, histogram) with click-through |
| 4 | Derived analytics: WAR (adapted), lean, competitiveness, turnout |
| 5 | AskAI: semantic layer + DuckDB-Wasm + AI SDK (multi-provider) React sidebar |
| 6 | Polish: accessibility, performance, update-script docs |

## Open Questions for You

1. OK with data starting at the 2001/2002 redistricting vintage (~24 years),
   or do you want a push toward 1970 (PD43+'s full range) despite the extra
   scraping/normalization work for older, less-structured records?
2. Provider priority for launch — all four (Anthropic/OpenAI/Gemini/Groq) at
   once, or ship one first and add the rest once the CORS behavior of each
   is confirmed?
