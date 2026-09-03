---
layout: default
title: Methodology
description: How district partisan lean and WAR (wins above replacement) are calculated on this site.
permalink: /methodology/
---

# Methodology

## District partisan lean

Each district's lean is the Democratic share of the two-party vote on a
statewide top-of-ticket race — Governor in gubernatorial years, President
in presidential years — apportioned down to the district. MA's state
legislative elections and its top-of-ticket races don't share a ballot
geography (towns split across districts, especially in denser areas), so
each town's baseline-race vote is apportioned to every district it
overlaps, in proportion to the **land area** of the overlap.

This lean is computed independently of the legislative race itself, so it
can serve as a "replacement level" — what a generic candidate of either
party would be expected to get in that district, absent anything specific
about who's actually running.

**A known simplification, not yet fixed**: apportionment is area-weighted,
not population-weighted. A town that's 10% of a district's land area
could hold anywhere from a sliver to a majority of its population — this
site currently treats those the same.

## WAR (wins above replacement)

**WAR = actual two-party vote share − expected share from a fitted
regression.** Positive means a candidate outperformed what the model
expected; negative means they underperformed it. It's reported per
contested race, for Democratic and Republican candidates only — a
minor-party candidate has no meaningful two-party baseline to compare
against, and an uncontested race has no meaningful "actual" side (an
unopposed candidate's near-100% share is mechanically inflated, not
earned against real competition) — so WAR is null in both cases.

The site always shows **one WAR figure per race, computed by the
richest model that race's own data supports**: a core regression on
district lean, statewide tide, and incumbency, extended with local
demographics or a candidate's own campaign fundraising wherever the
district or candidate has data for it. Every page's own **Factors**
column says which pieces actually went into that specific number.

Whether or not a race was contested, the model's **expected share** is
always defined — what a generic candidate of that party would be
expected to get here, from the same factors, without depending on the
actual outcome. It's shown in its own column everywhere WAR itself
would be, and it's the one number on this site that answers "how strong
should this seat's environment be for this party" even when the race
gave no real signal.

WAR here is **adapted from, not identical to,** the WAR metric published
by the election-analytics outlet
[Split Ticket](https://split-ticket.org/) for federal races, itself the
applied descendant of an academic literature on decomposing vote share
into a normal-vote (partisan baseline) component and a residual
attributable to the candidate:

- Gelman, A. & King, G. (1990). "Estimating Incumbency Advantage Without
  Bias." *American Journal of Political Science*, 34(4).
- Ansolabehere, S., Snyder, J. M., & Stewart, C. (2000). "Old Voters, New
  Voters, and the Personal Vote: Using Redistricting to Measure the
  Incumbency Advantage." *American Journal of Political Science*, 44(1).
- Squire, P. (1989, 1995) and Jacobson, G. — candidate-quality effects in
  (state) legislative races specifically.
- Stone, W. J. & Simas, E. N. (2010). "Candidate Valence and Ideological
  Positions in U.S. House Elections." *American Journal of Political
  Science*, 54(2) — the "candidate valence" framing this residual fits
  into.

Two differences from Split Ticket's own method, worth naming rather than
hiding: this fits **Massachusetts state legislative races** (House and
Senate), not federal — smaller electorates, more uncontested races, and
much thinner public polling/finance data per race than a Congressional
race has, and this project's own fit throughout, not theirs; and this
site's lean baseline has to cross **three Massachusetts redistricting
vintages** (2001-2010, 2012-2020, 2022-present), where Split Ticket's
federal-district baseline doesn't face that at the same scale.

**Every fitted effect below, on one comparable scale** — standardized to
vote-share points per 1 standard deviation of that predictor (see "Why
Bayesian, not ordinary least squares" below for why), so a 0-1 lean, a
0/1 incumbency term, and a log-dollar fundraising total all read side by
side:

<div id="war-overview-chart" role="img" aria-label="Forest plot of every model's standardized coefficients, colored by which model fits it, with 95% credible intervals"></div>

## The core regression model

**WAR = actual two-party vote share − a fitted regression's expected
share**, where the regression is:

> *own-party share ~ intercept + district lean + statewide tide +
> incumbency (1st / 2nd / 3rd-or-later term)*

"Own-party" means every value is already flipped to the candidate's own
party's perspective (a Republican's own_lean is `1 − lean_dem_share`,
same for tide) — the same symmetry the plain lean-only definition above
already uses, so one fit covers both parties.

**Statewide tide** is a new fundamental beyond district lean itself: the
*unapportioned*, whole-state two-party Democratic share on that year's
baseline race (Governor or President), as opposed to `lean_dem_share`,
which is that same race apportioned down to one district. Splitting them
apart lets the model separate a district's own persistent partisanship
from a given cycle's overall national/state mood — the same normal-vote-
plus-national-tide idea behind Gelman & King (1990), cited above, rather
than lean alone conflating the two.

**Incumbency** is three terms — 1st, 2nd, and 3rd-or-later consecutive
term already served (see "Incumbency and open seats" below) — rather
than a plain incumbent/non-incumbent split, so the fit can show whether a
second or third term brings a bigger or smaller edge than the first
instead of assuming they're identical.

### Why Bayesian, not ordinary least squares

This is fit as a **Bayesian linear regression** (a hand-rolled Gibbs
sampler, not a plug-in library — see `generate_site_data.py`'s
`_bayesian_linear_regression`), with a weakly informative, regularizing
prior on every coefficient, rather than plain least squares. Two real
properties of this data make that matter, not just a methodological
preference:

- District lean and statewide tide are **correlated** (a district's own
  apportioned share and the state's overall result on the same race move
  together), which unregularized least squares can split unstably between
  the two.
- The incumbency buckets are **unevenly sized** — far fewer candidates
  have served 3+ consecutive terms than 1 — and the diagnostic extensions
  below fit on samples small enough that an unconstrained estimate would
  be mostly noise.

A Gaussian prior on each coefficient shrinks it toward a substantively
reasonable value in proportion to how little the data actually pins it
down — real regularization, not an ad hoc penalty — and the fit reports a
full posterior (mean, standard deviation, and a 95% credible interval
taken directly from the sampled draws), not just a point estimate.

**Concretely, here's what that regularization does to one term.** Before
seeing any data, the prior for a first-term incumbent's edge was a wide,
weakly-informed guess (mean {{ site.data.war_v2.coefficients.incumbent_1.prior_mean | times: 100 | round: 0 }}
points, standard deviation {{ site.data.war_v2.coefficients.incumbent_1.prior_sd | times: 100 | round: 0 }}
points — that shape, below). After fitting on
{{ site.data.war_v2.n_incumbent_1 }} real 1st-term-incumbent races, the
posterior is both narrower and shifted to
{{ site.data.war_v2.coefficients.incumbent_1.posterior_mean | times: 100 | round: 1 }}
points — the data had enough to say something much more specific than the
prior alone did, which is exactly what "the data pins it down" should
look like:

<div id="prior-posterior-chart" role="img" aria-label="Density chart comparing the prior and posterior distributions for the first-term incumbency coefficient"></div>

As of the last full pipeline run, on
{{ site.data.war_v2.n }} contested major-party candidate-races
(R² = {{ site.data.war_v2.r_squared }}), every coefficient's posterior
mean and 95% credible interval:

<div id="war-v2-forest-chart" role="img" aria-label="Forest plot of the core regression's coefficients with 95% credible intervals"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| Intercept | {{ site.data.war_v2.coefficients.intercept.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_v2.coefficients.intercept.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_v2.coefficients.intercept.ci_95_high | times: 100 | round: 1 }}] |
| District lean | {{ site.data.war_v2.coefficients.own_lean.posterior_mean | round: 3 }} | [{{ site.data.war_v2.coefficients.own_lean.ci_95_low | round: 3 }}, {{ site.data.war_v2.coefficients.own_lean.ci_95_high | round: 3 }}] |
| Statewide tide | {{ site.data.war_v2.coefficients.own_tide.posterior_mean | round: 3 }} | [{{ site.data.war_v2.coefficients.own_tide.ci_95_low | round: 3 }}, {{ site.data.war_v2.coefficients.own_tide.ci_95_high | round: 3 }}] |
| Incumbent, 1st term | +{{ site.data.war_v2.coefficients.incumbent_1.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_v2.coefficients.incumbent_1.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_v2.coefficients.incumbent_1.ci_95_high | times: 100 | round: 1 }}] |
| Incumbent, 2nd term | +{{ site.data.war_v2.coefficients.incumbent_2.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_v2.coefficients.incumbent_2.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_v2.coefficients.incumbent_2.ci_95_high | times: 100 | round: 1 }}] |
| Incumbent, 3rd+ term | +{{ site.data.war_v2.coefficients.incumbent_3plus.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_v2.coefficients.incumbent_3plus.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_v2.coefficients.incumbent_3plus.ci_95_high | times: 100 | round: 1 }}] |

District lean's coefficient sitting well below 1.0 is a real finding, not
a fitting artifact — checked directly against plain least squares on the
same data, which lands in the same neighborhood. It means a district's
own apportioned lean, once that year's statewide tide is already in the
model, only partially carries through to actual legislative vote share —
plausibly some mix of the area-weighted apportionment noise documented
above and real candidate-to-candidate variation legislative races carry
that a top-of-ticket baseline can't see. The three incumbency terms
landing close to each other says this site's data doesn't show a strong
"sophomore surge" or a fading effect in later terms — an incumbent's edge
looks fairly flat across term number so far.

**What that fit actually looks like against every one of those races**:
each point is one contested major-party candidate-race, this model's
expected share (x) against what actually happened (y). A point sitting
exactly on the dashed diagonal means the model called it perfectly; above
the line is a real overperformance (positive WAR), below is an
underperformance — the same information the site's own WAR numbers
carry, just all {{ site.data.war_v2.n }} of them at once instead of one
race at a time.

<div id="war-v2-fit-scatter" role="img" aria-label="Scatter plot of the core regression's expected two-party share against each candidate's actual share, colored by party"></div>

**Split by party, that scatter hides a real pattern the pooled fit doesn't
correct for**: Democratic candidates' residuals (actual share minus
expected) average <span id="dem-residual-note">…</span>; Republican
candidates' average <span id="rep-residual-note">…</span> — close to
equal and opposite, so the intercept still zeros out the residual
*pooled* across every race (that's guaranteed by construction), but not
the residual *within* each party:

<div id="war-v2-residual-histogram" role="img" aria-label="Histogram of the core regression's residuals (actual minus expected share), separately for Democratic and Republican candidates"></div>

This isn't a failure of the own-party symmetry above — `own_lean`,
`own_tide`, and `actual_two_party_share` are each already computed from
that specific candidate's own party's perspective, so the fit literally
can't tell a Democrat in a D+10 district from a Republican in an R+10
one. What it *does* assume is that one shared set of coefficients (one
`own_lean` slope, one `own_tide` slope, one set of incumbency terms)
describes both parties' relationship between district fundamentals and
actual performance equally well. In Massachusetts specifically, that
assumption looks shaky: the legislature's real, well-documented
Democratic supermajority is larger than the state's own top-of-ticket
vote share alone would predict, and this backfill's own composition
reflects it — most Democratic candidates in it are incumbents, while
most Republicans are non-incumbent challengers running in a chamber their
party rarely controls. If incumbent and non-incumbent candidates don't
relate to lean/tide identically between the two parties (a real
possibility a single pooled model can't represent), a shared coefficient
set will land closer to whichever pattern is more common in the data —
and leave same-direction residuals within each party even though the
overall average comes out to zero. A real, open limitation of pooling
both parties into one regression rather than fitting party-specific
slopes or a party interaction term — not yet addressed here.

Every district and seat page has a "What drives replacement level" chart
breaking a race's most recent contested year into these pieces (intercept,
lean, tide, incumbency, and the WAR residual) for each candidate, and a
candidate's own page charts their actual share against this model's
expected share, and the same decomposition, across every year they ran —
the gap between the two lines on the first chart *is* WAR, made visible.

**A related, worth-naming property**: in `own_lean`/`own_tide`'s own
terms, the two candidates in a race are exact mirrors
(`own_lean` + the other candidate's `own_lean` = 1, always) — the
"Lean" and "Statewide tide" bars for both candidates in the attribution
chart are both genuinely positive because a district's baseline splits
into two positive shares, not because the model favors both sides at
once. The **intercept**, though, is a single fitted constant applied
identically to both candidates' own expected share, not split between
them — so unlike a plain lean-only baseline (where the two opposing
candidates' expected shares always summed to exactly 100%, and their WAR
values were exact opposites), **this model's two expected shares in a
race don't sum to 100%**, and the two WAR values aren't required to
cancel out. That's an accepted consequence of letting the regression fit
its own intercept rather than assuming a lean-only "coefficient on lean =
1, no intercept" structure — not an error in the numbers, but a real
change in what the model guarantees.

## Demographics and campaign finance extensions

Two further regressions, built the same Bayesian way as the core model
above, extend it with local demographics and campaign fundraising — the
remaining fundamentals this project's design calls for (same spirit as
Split Ticket's approach, this project's own fit, not theirs). **Each
extension folds into a candidate's actual WAR number only where that
specific district or candidate has the data to support it** — both fit
on real but genuinely thin slices of this site's data, a coverage limit
rather than an oversight; where the data falls short, the site falls
back to the core model above and the Factors column says so.

{% if site.data.war_v3_demographics.core or site.data.war_v3_demographics.full %}
**Demographics** adds district-level Census fields (2020 PL 94-171 +
2022 ACS 5-year, current 2022-present vintage only), fit in **two
tiers that fall back gracefully rather than all-or-nothing** — a
district missing some Census fields still gets a simpler version of
this extension instead of being dropped entirely:

{% if site.data.war_v3_demographics.core %}
- **Core** ({{ site.data.war_v3_demographics.core.n }} candidate-races,
  R² = {{ site.data.war_v3_demographics.core.r_squared }}): bachelor's-
  degree-or-higher share of population alone — the "diploma divide"
  variable most associated with recent-era partisan realignment. This is
  the fallback every current-vintage district with *any* Census match
  can use, including ones a PL 94-171 name-matching gap keeps out of the
  full tier (Census's own district-name spelling doesn't always match
  this project's boundary data cleanly, especially for Senate seats
  spanning multiple counties — see `pipeline/README.md`).
{% endif %}
{% if site.data.war_v3_demographics.full %}
- **Full** ({{ site.data.war_v3_demographics.full.n }} candidate-races,
  R² = {{ site.data.war_v3_demographics.full.r_squared }}): adds
  Hispanic-or-Latino population share, voting-age population share, and
  median household income (per $10,000) — restricted to districts with a
  real PL 94-171 match, since the two population-share terms need it
  specifically (a district with only ACS data, like the core tier's
  fallback districts, can't compute them).
{% endif %}

Both tiers re-estimate lean, tide, and incumbency on their own
(current-vintage-only) samples rather than borrowing the core model's
coefficients:

{% if site.data.war_v3_demographics.core %}
<div id="war-v3-demographics-forest-chart" role="img" aria-label="Forest plot of the demographics extension's core tier's added coefficient with a 95% credible interval"></div>
{% endif %}
{% if site.data.war_v3_demographics.full %}
<div id="war-v3-demographics-full-forest-chart" role="img" aria-label="Forest plot of the demographics extension's full tier's added coefficients with 95% credible intervals"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| Bachelor's degree % | {{ site.data.war_v3_demographics.full.coefficients.bachelors_pct.posterior_mean | round: 3 }} | [{{ site.data.war_v3_demographics.full.coefficients.bachelors_pct.ci_95_low | round: 3 }}, {{ site.data.war_v3_demographics.full.coefficients.bachelors_pct.ci_95_high | round: 3 }}] |
| Hispanic or Latino % | {{ site.data.war_v3_demographics.full.coefficients.hispanic_pct.posterior_mean | round: 3 }} | [{{ site.data.war_v3_demographics.full.coefficients.hispanic_pct.ci_95_low | round: 3 }}, {{ site.data.war_v3_demographics.full.coefficients.hispanic_pct.ci_95_high | round: 3 }}] |
| Voting-age % | {{ site.data.war_v3_demographics.full.coefficients.voting_age_pct.posterior_mean | round: 3 }} | [{{ site.data.war_v3_demographics.full.coefficients.voting_age_pct.ci_95_low | round: 3 }}, {{ site.data.war_v3_demographics.full.coefficients.voting_age_pct.ci_95_high | round: 3 }}] |
| Median household income (per $10k) | {{ site.data.war_v3_demographics.full.coefficients.income_10k.posterior_mean | round: 4 }} | [{{ site.data.war_v3_demographics.full.coefficients.income_10k.ci_95_low | round: 4 }}, {{ site.data.war_v3_demographics.full.coefficients.income_10k.ci_95_high | round: 4 }}] |

Every term the full tier fits, on the same standardized scale as the
overview chart above:

<div id="war-v3-demographics-standardized-chart" role="img" aria-label="Forest plot of all nine of the demographics extension's full tier's non-intercept coefficients, standardized to a common per-1-SD-of-predictor scale, with 95% credible intervals"></div>
{% endif %}

Neither tier's Demographics slice is chosen per-race — it's chosen per
**district**: a district with a full Census match uses the full tier's
combined effect everywhere on that district's own pages; a district with
only a partial match uses the core tier's bachelors-only effect instead;
a district with no match at all falls back to the core model alone.

Neither tier fits an interaction with tide (e.g. "does a district's
education level swing more or less with the national mood than average")
— an interaction is only as identified as the number of distinct
election years in the fit, and demographics only covers **{{ site.data.war_v3_demographics.full.n_distinct_years | default: site.data.war_v3_demographics.core.n_distinct_years }}
election years on record** (the current, 2022-present vintage), nowhere
near enough to trust one over just two elections' worth of noise.
{% endif %}

{% if site.data.war_v3_finance %}
**Campaign finance** ({{ site.data.war_v3_finance.n }} candidate-races
across {{ site.data.war_v3_finance.n_distinct_years }} election years,
R² = {{ site.data.war_v3_finance.r_squared }}) adds a candidate's own OCPF
total raised that cycle (log-transformed — fundraising totals are heavily
right-skewed), restricted to candidates `campaign_finance_match` actually
matched to an OCPF filer (see "Campaign finance" below). Unlike the
demographics extension above, this fit re-estimates lean, tide, **and**
incumbency too, alongside the new fundraising term — it doesn't drop any
of the core model's terms, just adds one:

<div id="war-v3-finance-forest-chart" role="img" aria-label="Forest plot of the campaign finance extension's fundraising coefficient with a 95% credible interval"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| District lean | {{ site.data.war_v3_finance.coefficients.own_lean.posterior_mean | round: 3 }} | [{{ site.data.war_v3_finance.coefficients.own_lean.ci_95_low | round: 3 }}, {{ site.data.war_v3_finance.coefficients.own_lean.ci_95_high | round: 3 }}] |
| Statewide tide | {{ site.data.war_v3_finance.coefficients.own_tide.posterior_mean | round: 3 }} | [{{ site.data.war_v3_finance.coefficients.own_tide.ci_95_low | round: 3 }}, {{ site.data.war_v3_finance.coefficients.own_tide.ci_95_high | round: 3 }}] |
| Incumbent, 1st term | {{ site.data.war_v3_finance.coefficients.incumbent_1.posterior_mean | round: 3 }} | [{{ site.data.war_v3_finance.coefficients.incumbent_1.ci_95_low | round: 3 }}, {{ site.data.war_v3_finance.coefficients.incumbent_1.ci_95_high | round: 3 }}] |
| Incumbent, 2nd term | {{ site.data.war_v3_finance.coefficients.incumbent_2.posterior_mean | round: 3 }} | [{{ site.data.war_v3_finance.coefficients.incumbent_2.ci_95_low | round: 3 }}, {{ site.data.war_v3_finance.coefficients.incumbent_2.ci_95_high | round: 3 }}] |
| Incumbent, 3rd+ term | {{ site.data.war_v3_finance.coefficients.incumbent_3plus.posterior_mean | round: 3 }} | [{{ site.data.war_v3_finance.coefficients.incumbent_3plus.ci_95_low | round: 3 }}, {{ site.data.war_v3_finance.coefficients.incumbent_3plus.ci_95_high | round: 3 }}] |
| log(total raised + 1) | {{ site.data.war_v3_finance.coefficients.log_raised.posterior_mean | round: 4 }} | [{{ site.data.war_v3_finance.coefficients.log_raised.ci_95_low | round: 4 }}, {{ site.data.war_v3_finance.coefficients.log_raised.ci_95_high | round: 4 }}] |

A positive, clearly-nonzero coefficient on logged fundraising (95%
credible interval entirely above zero) says money and vote share move
together in this data even after accounting for lean, tide, and
incumbency, across two decades of races:

<div id="war-v3-finance-standardized-chart" role="img" aria-label="Forest plot of all six of the campaign finance extension's coefficients, standardized to a common per-1-SD-of-predictor scale, with 95% credible intervals"></div>

**On a candidate page's own per-race attribution chart, the Fundraising
bar is centered on this fit's own mean log-dollar total, not on $0.**
`log(total raised + 1)`'s coefficient above is genuinely small, but its
predictor lives on a log-dollar scale (typically 7–14 across real
candidates) rather than the 0–1 fraction lean, tide, and the demographics
terms use — multiplying that small coefficient by a raw value in the
7–14 range, rather than by how far it sits from a *typical* matched
candidate's total, would make the bar disproportionately large purely
from comparing against an impossible $0-raised baseline. Centering it
avoids that: the bar reads as "how this candidate's fundraising compares
to a typical matched candidate's," in real vote-share points, with the
removed constant folded into the chart's Baseline bar instead — the
total predicted share for the race is unchanged.
{% endif %}

Neither extension is folded into every candidate's WAR the way the core
model is — campaign finance only where `campaign_finance_match` found a
confident OCPF match, demographics only for the current redistricting
vintage — but both **are** threaded into their attribution charts
wherever they apply: a candidate page's "What drives replacement level,
by year" chart uses the finance extension for any year with a matched
OCPF total (falling back to the core model otherwise), and a district or
seat page's chart does the same with the demographics extension for
districts with a current-vintage match. Each of those pages also has a
companion forest-style chart, right below the stacked bar, showing the
same components as a point plus an approximate 95% interval — the
stacked bar is good at showing what a share is made of, not at showing
how confidently. Those intervals use the same delta-method shortcut as
everywhere else on this page: each component's uncertainty approximated
as `|covariate value| × that coefficient's own posterior SD`, treating
coefficients as independent of each other rather than propagating their
full joint posterior — a known simplification, not a full solution.

## Turnout

**Turnout ratio = this race's two-party vote total ÷ the district's
apportioned two-party vote total on the statewide baseline race.**

This reads as a "roll-off" measure — what share of the people who cast a
two-party vote in the baseline race also cast a two-party vote in this
legislative race — not a share of eligible or registered voters (there's
no population denominator here). A value below 1.0 means the legislative
race drew relatively fewer two-party voters than the baseline; above 1.0
means it drew relatively more. It can exceed 1.0, and does: a hot,
contested legislative race can outdraw a lopsided top-of-ticket result in
that particular district.

Turnout ratio inherits the same area-weighted apportionment simplification
as district lean (see above) — a dense, small-area urban district can show
an unusually extreme ratio purely from that simplification, not necessarily
a real turnout story. Treat any single extreme value with that in mind.

## Incumbency and open seats

A candidate is marked **incumbent** if they won the *immediately preceding*
election for that same district, within the same redistricting vintage.
This is derived entirely from this site's own accumulated results — no
separate incumbency data source — so it only becomes meaningful once a
second election exists for a district: a district's first election on
record (in a given vintage, or before enough years have been backfilled)
shows no incumbents, which is a "not yet known" state, not a claim that
the race was genuinely open.

**Deliberately not chased across a redistricting boundary**: even where
`build.crosswalks`' seat-lineage links a district to a predecessor in an
earlier vintage (see "Seats vs. districts" below), that link is an
area-overlap best guess, not a guarantee the same electorate — or even
district name — carried over. Treating whoever won the predecessor
district as "the incumbent" would overstate what's actually known, so
incumbency resets at each vintage boundary.

An **open seat** is a race where the prior winner isn't among this year's
candidates at all (and only ever computed when a prior year is known —
otherwise it's left unknown, same reasoning as incumbency above).

## Campaign finance

Candidate pages show OCPF (MA Office of Campaign and Political Finance)
totals — raised and spent per year — when a candidate could be matched to
an OCPF filer. This is genuinely a best-effort match, not a join on a
shared ID: OCPF's public filer roster has no PD43+ candidate identifier,
and names don't always agree exactly (OCPF sometimes has a nickname —
"Nick" — where PD43+'s ballot name is the formal one — "Nicholas A.").

The match key is **last name + district + chamber**, checked against every
race a candidate is known to have run — deliberately *not* first name,
since a shared last name and the exact same numbered district is already a
strong-enough constraint that nickname/initial variation in the first name
doesn't need to factor in. This design errs toward **missing** a real match
over risking a **wrong** one: a candidate simply won't show a finance
section rather than showing someone else's numbers.
{% assign finance_matched = site.candidates | where_exp: "c", "c.ocpf_finance" | size %}
{% assign candidate_total = site.candidates | size %}
**{{ finance_matched }} of {{ candidate_total }} candidates**
({{ finance_matched | times: 100.0 | divided_by: candidate_total | round: 0 }}%)
in this site's full backfill are matched this way, now that OCPF's own
bulk export has been pulled for the full 2002-2024 range (see
`fetch.campaign_finance` in `pipeline/README.md`) rather than just one
year — the rest either have no OCPF filing on record (common for
candidates under OCPF's low-fundraising exemption threshold) or use a last
name this matching doesn't correctly extract (multi-word surnames in
particular — see the module docstring in `build.campaign_finance_match`
for the exact rule).

## Demographics

District and seat pages show population, voting-age population, Hispanic
or Latino population (2020 Census PL 94-171 redistricting data), and
median household income and bachelor's-degree-or-higher count (American
Community Survey 5-year estimates) when available.

**This only ever covers the current (2022-present) redistricting
vintage.** PL 94-171 is published against a state's *current* district
boundaries only — the Census Bureau doesn't retroactively republish it
against districts that have since been redrawn — and this site's own ACS
pull follows the same current-vintage geography. A pre-2022 district page
simply has no Demographics section.

Matching is by district name, after stripping the Census's own trailing
`"(2022), Massachusetts"`-style suffix, using the same name-matching logic
this site already uses to reconcile PD43+'s district names against
boundary-file names. It's not perfect: House matched 159 of its 160
districts (the one miss — 19th Worcester District — simply isn't in
Census's own house district list at all, a genuine gap in the source
data, not a matching failure); Senate matched only 26 of 40, since
Census's Senate district names diverge from PD43+'s more than the matcher
can close on its own (e.g. Census's "Second Hampden & Hampshire District"
vs. this site's "Hampden and Hampshire District" — both an ordinal-word
prefix and a different conjunction). As elsewhere on this site, a missing
demographics section means the match failed, not that the data doesn't
exist.

One more real gotcha worth flagging: the Census ACS API encodes a
suppressed or statistically unreliable estimate as the literal value
`-666666666`, not a null. Where that shows up (rare, but it does happen —
one district's median household income in this site's own fetched data),
this site treats it as missing rather than publishing a nonsense figure.

## Competitiveness

Each district is bucketed by its lean's distance from 50%, in the style
of the Cook Political Report's Partisan Voter Index:

| Bucket | Margin from 50% |
|---|---|
| Safe | > 15 points |
| Likely | 10-15 points |
| Lean | 5-10 points |
| Tossup | < 5 points |

The bucket is paired with which party the lean favors (e.g. "Safe D",
"Tossup R") into the competitiveness label shown throughout the site.

## Seats vs. districts

A **[seat](/seat/)** page tracks a specific area's representation over
time — the current redistricting vintage's district, plus a history
section linking back through prior vintages by best land-area overlap
(from `build.crosswalks`' seat-lineage matching). A
**[district](/district/)** page is scoped to one specific vintage's
boundaries; the same area can be a different district (different
boundaries, sometimes a different name) in an earlier vintage, so
district identity isn't assumed to persist across redistricting the way a
seat's does.

## Source

All of this runs from a public data pipeline —
[electionstats.state.ma.us](https://electionstats.state.ma.us) (PD43+)
for election results, Census TIGER/Line and MIT Libraries' GeoData
Repository for district boundaries — published in full at
[github.com/nesanders/ma-political-analytics](https://github.com/nesanders/ma-political-analytics),
including the exact code that computes everything on this page.

<script>
  // Field-by-field data, not a full-object jsonify — same reasoning as
  // every other inline chart on this site (see e.g. chamber.html's
  // seatData): avoids ever embedding a Jekyll Document's other rendered
  // fields inside a script tag. site.data.war_v2/_fit_sample are plain
  // Python-written YAML (numbers and short strings only, no Document
  // risk), so jsonify-ing them directly here is safe.
  const methodologyStyle = getComputedStyle(document.documentElement);
  const methodologyCssVar = (name) => methodologyStyle.getPropertyValue(name).trim();
  const methodologyAxisConfig = {
    axis: {
      labelColor: methodologyCssVar("--text-secondary"),
      titleColor: methodologyCssVar("--text-primary"),
      gridColor: methodologyCssVar("--gridline"),
      domainColor: methodologyCssVar("--gridline")
    },
    legend: { labelColor: methodologyCssVar("--text-secondary"), titleColor: methodologyCssVar("--text-primary") },
    view: { stroke: null }
  };

  {% if site.data.war_v2 %}
  // --- Prior vs. posterior: incumbent_1 term ---------------------------
  (function () {
    function normalPdf(x, mean, sd) {
      return Math.exp(-0.5 * Math.pow((x - mean) / sd, 2)) / (sd * Math.sqrt(2 * Math.PI));
    }
    const priorMean = {{ site.data.war_v2.coefficients.incumbent_1.prior_mean | jsonify }};
    const priorSd = {{ site.data.war_v2.coefficients.incumbent_1.prior_sd | jsonify }};
    const postMean = {{ site.data.war_v2.coefficients.incumbent_1.posterior_mean | jsonify }};
    const postSd = {{ site.data.war_v2.coefficients.incumbent_1.posterior_sd | jsonify }};
    const lo = Math.min(priorMean - 3.5 * priorSd, postMean - 3.5 * postSd);
    const hi = Math.max(priorMean + 3.5 * priorSd, postMean + 3.5 * postSd);
    const steps = 200;
    const data = [];
    for (let i = 0; i <= steps; i++) {
      const x = lo + ((hi - lo) * i) / steps;
      data.push({ x: x, density: normalPdf(x, priorMean, priorSd), series: "Prior belief" });
      data.push({ x: x, density: normalPdf(x, postMean, postSd), series: "Posterior (after data)" });
    }
    const spec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "width": "container",
      "height": 200,
      "background": null,
      "data": { "values": data },
      "mark": { "type": "area", "opacity": 0.45, "line": { "strokeWidth": 2 } },
      "encoding": {
        "x": { "field": "x", "type": "quantitative", "title": "Incumbent, 1st term — coefficient value", "axis": { "format": "+.0%" } },
        "y": { "field": "density", "type": "quantitative", "title": null, "axis": null },
        "color": {
          "field": "series", "type": "nominal", "title": null,
          "scale": { "domain": ["Prior belief", "Posterior (after data)"], "range": [methodologyCssVar("--text-secondary"), methodologyCssVar("--war-incumbency")] }
        },
        "tooltip": [{ "field": "series", "title": "Distribution" }, { "field": "x", "type": "quantitative", "format": "+.1%", "title": "Value" }]
      },
      "config": methodologyAxisConfig
    };
    vegaEmbed("#prior-posterior-chart", spec, { actions: false }).catch(console.error);
  })();

  // --- Reusable forest plot: posterior mean + 95% CI per coefficient -----
  // Shared by the WAR v2 core plot and both WAR v3 extension plots below,
  // so each only has to supply its own coefficients object, [label, key]
  // term list, target element id, and accent color.
  function renderForestChart(elementId, coefs, terms, color, height, standardized) {
    const meanKey = standardized ? "standardized_mean" : "posterior_mean";
    const loKey = standardized ? "standardized_ci_95_low" : "ci_95_low";
    const hiKey = standardized ? "standardized_ci_95_high" : "ci_95_high";
    const data = terms.map(([label, key]) => ({
      term: label,
      mean: coefs[key][meanKey],
      lo: coefs[key][loKey],
      hi: coefs[key][hiKey],
    }));
    const termOrder = terms.map((t) => t[0]);
    const xTitle = standardized ? "Standardized effect (per 1 SD of predictor)" : "Coefficient value";
    const spec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "width": "container",
      "height": height || 220,
      "background": null,
      "layer": [
        {
          "data": { "values": [{ "x": 0 }] },
          "mark": { "type": "rule", "strokeDash": [4, 2] },
          "encoding": { "x": { "field": "x", "type": "quantitative", "title": xTitle }, "color": { "value": methodologyCssVar("--gridline") } }
        },
        {
          "data": { "values": data },
          "mark": { "type": "rule", "size": 2 },
          "encoding": {
            "y": { "field": "term", "type": "nominal", "sort": termOrder, "title": null },
            "x": { "field": "lo", "type": "quantitative" },
            "x2": { "field": "hi" },
            "color": { "value": color }
          }
        },
        {
          "data": { "values": data },
          "mark": { "type": "point", "filled": true, "size": 90 },
          "encoding": {
            "y": { "field": "term", "type": "nominal", "sort": termOrder, "title": null },
            "x": { "field": "mean", "type": "quantitative" },
            "color": { "value": color },
            "tooltip": [
              { "field": "term", "title": "Term" },
              { "field": "mean", "type": "quantitative", "format": ".4f", "title": "Posterior mean" },
              { "field": "lo", "type": "quantitative", "format": ".4f", "title": "95% CI low" },
              { "field": "hi", "type": "quantitative", "format": ".4f", "title": "95% CI high" }
            ]
          }
        }
      ],
      "config": methodologyAxisConfig
    };
    vegaEmbed("#" + elementId, spec, { actions: false }).catch(console.error);
  }

  renderForestChart(
    "war-v2-forest-chart",
    {{ site.data.war_v2.coefficients | jsonify }},
    [
      ["Intercept", "intercept"],
      ["District lean", "own_lean"],
      ["Statewide tide", "own_tide"],
      ["Incumbent, 1st term", "incumbent_1"],
      ["Incumbent, 2nd term", "incumbent_2"],
      ["Incumbent, 3rd+ term", "incumbent_3plus"],
    ],
    methodologyCssVar("--war-incumbency")
  );

  // --- Model overview: every fitted effect, one comparable scale ---------
  (function () {
    const overviewCoreCoefs = {{ site.data.war_v2.coefficients | jsonify }};
    const rows = [
      { term: "District lean", model: "Core", key: "own_lean" },
      { term: "Statewide tide", model: "Core", key: "own_tide" },
      { term: "Incumbency, 1st term", model: "Core", key: "incumbent_1" },
      { term: "Incumbency, 2nd term", model: "Core", key: "incumbent_2" },
      { term: "Incumbency, 3rd+ term", model: "Core", key: "incumbent_3plus" },
    ].map((r) => {
      const c = overviewCoreCoefs[r.key];
      return { term: r.term, model: r.model, mean: c.standardized_mean, lo: c.standardized_ci_95_low, hi: c.standardized_ci_95_high };
    });
    {% if site.data.war_v3_demographics.full %}
    (function () {
      const demoCoefs = {{ site.data.war_v3_demographics.full.coefficients | jsonify }};
      [
        ["Bachelor's degree %", "bachelors_pct"],
        ["Hispanic or Latino %", "hispanic_pct"],
        ["Voting-age %", "voting_age_pct"],
        ["Median household income", "income_10k"],
      ].forEach(([term, key]) => {
        const c = demoCoefs[key];
        rows.push({ term: term, model: "Demographics", mean: c.standardized_mean, lo: c.standardized_ci_95_low, hi: c.standardized_ci_95_high });
      });
    })();
    {% endif %}
    {% if site.data.war_v3_finance %}
    (function () {
      const c = {{ site.data.war_v3_finance.coefficients | jsonify }}.log_raised;
      rows.push({ term: "Campaign fundraising (logged)", model: "Campaign finance", mean: c.standardized_mean, lo: c.standardized_ci_95_low, hi: c.standardized_ci_95_high });
    })();
    {% endif %}
    const termOrder = rows.map((r) => r.term);
    const modelColor = {
      "Core": methodologyCssVar("--war-incumbency"),
      "Demographics": methodologyCssVar("--war-extra"),
      "Campaign finance": methodologyCssVar("--war-residual"),
    };
    const spec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "width": "container",
      "height": Math.max(160, rows.length * 34),
      "background": null,
      "layer": [
        {
          "data": { "values": [{ "x": 0 }] },
          "mark": { "type": "rule", "strokeDash": [4, 2] },
          "encoding": { "x": { "field": "x", "type": "quantitative", "title": "Standardized effect (vote-share points per 1 SD of predictor)" }, "color": { "value": methodologyCssVar("--gridline") } }
        },
        {
          "data": { "values": rows },
          "mark": { "type": "rule", "size": 2 },
          "encoding": {
            "y": { "field": "term", "type": "nominal", "sort": termOrder, "title": null },
            "x": { "field": "lo", "type": "quantitative" },
            "x2": { "field": "hi" },
            "color": { "field": "model", "type": "nominal", "title": "Model", "scale": { "domain": Object.keys(modelColor), "range": Object.values(modelColor) } }
          }
        },
        {
          "data": { "values": rows },
          "mark": { "type": "point", "filled": true, "size": 90 },
          "encoding": {
            "y": { "field": "term", "type": "nominal", "sort": termOrder, "title": null },
            "x": { "field": "mean", "type": "quantitative" },
            "color": { "field": "model", "type": "nominal", "title": "Model", "scale": { "domain": Object.keys(modelColor), "range": Object.values(modelColor) } },
            "tooltip": [
              { "field": "term", "title": "Term" },
              { "field": "model", "title": "Model" },
              { "field": "mean", "type": "quantitative", "format": ".4f", "title": "Standardized effect" },
              { "field": "lo", "type": "quantitative", "format": ".4f", "title": "95% CI low" },
              { "field": "hi", "type": "quantitative", "format": ".4f", "title": "95% CI high" }
            ]
          }
        }
      ],
      "config": methodologyAxisConfig
    };
    vegaEmbed("#war-overview-chart", spec, { actions: false }).catch(console.error);
  })();
  {% endif %}

  {% if site.data.war_v3_demographics.core %}
  renderForestChart(
    "war-v3-demographics-forest-chart",
    {{ site.data.war_v3_demographics.core.coefficients | jsonify }},
    [["Bachelor's degree %", "bachelors_pct"]],
    methodologyCssVar("--war-tide"),
    90
  );
  {% endif %}
  {% if site.data.war_v3_demographics.full %}
  renderForestChart(
    "war-v3-demographics-full-forest-chart",
    {{ site.data.war_v3_demographics.full.coefficients | jsonify }},
    [
      ["Bachelor's degree %", "bachelors_pct"],
      ["Hispanic or Latino %", "hispanic_pct"],
      ["Voting-age %", "voting_age_pct"],
      ["Median household income (per $10k)", "income_10k"],
    ],
    methodologyCssVar("--war-tide"),
    180
  );
  renderForestChart(
    "war-v3-demographics-standardized-chart",
    {{ site.data.war_v3_demographics.full.coefficients | jsonify }},
    [
      ["District lean", "own_lean"],
      ["Statewide tide", "own_tide"],
      ["Incumbent, 1st term", "incumbent_1"],
      ["Incumbent, 2nd term", "incumbent_2"],
      ["Incumbent, 3rd+ term", "incumbent_3plus"],
      ["Bachelor's degree %", "bachelors_pct"],
      ["Hispanic or Latino %", "hispanic_pct"],
      ["Voting-age %", "voting_age_pct"],
      ["Median household income (per $10k)", "income_10k"],
    ],
    methodologyCssVar("--war-extra"),
    310,
    true
  );
  {% endif %}

  {% if site.data.war_v3_finance %}
  renderForestChart(
    "war-v3-finance-forest-chart",
    {{ site.data.war_v3_finance.coefficients | jsonify }},
    [["log(total raised + 1)", "log_raised"]],
    methodologyCssVar("--war-residual"),
    90
  );
  renderForestChart(
    "war-v3-finance-standardized-chart",
    {{ site.data.war_v3_finance.coefficients | jsonify }},
    [
      ["District lean", "own_lean"],
      ["Statewide tide", "own_tide"],
      ["Incumbent, 1st term", "incumbent_1"],
      ["Incumbent, 2nd term", "incumbent_2"],
      ["Incumbent, 3rd+ term", "incumbent_3plus"],
      ["log(total raised + 1)", "log_raised"],
    ],
    methodologyCssVar("--war-extra"),
    220,
    true
  );
  {% endif %}

  {% if site.data.war_v2_fit_sample %}
  // --- Actual vs. expected share scatter ----------------------------------
  (function () {
    const fitSample = {{ site.data.war_v2_fit_sample | jsonify }};
    const colorDem = methodologyCssVar("--series-dem");
    const colorRep = methodologyCssVar("--series-rep");
    const spec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "width": "container",
      "height": 320,
      "background": null,
      "layer": [
        {
          "data": { "values": [{ "x": 0, "y": 0 }, { "x": 1, "y": 1 }] },
          "mark": { "type": "line", "strokeDash": [4, 2] },
          "encoding": {
            "x": { "field": "x", "type": "quantitative" },
            "y": { "field": "y", "type": "quantitative" },
            "color": { "value": methodologyCssVar("--text-secondary") }
          }
        },
        {
          "data": { "values": fitSample },
          "mark": { "type": "circle", "opacity": 0.35, "size": 30 },
          "encoding": {
            "x": { "field": "expected", "type": "quantitative", "title": "Expected share (core model)", "axis": { "format": "%" }, "scale": { "domain": [0, 1] } },
            "y": { "field": "actual", "type": "quantitative", "title": "Actual share", "axis": { "format": "%" }, "scale": { "domain": [0, 1] } },
            "color": {
              "field": "party", "type": "nominal", "title": "Party",
              "scale": { "domain": ["Democratic", "Republican"], "range": [colorDem, colorRep] }
            },
            "tooltip": [
              { "field": "year", "title": "Year" },
              { "field": "party", "title": "Party" },
              { "field": "actual", "type": "quantitative", "format": ".1%", "title": "Actual" },
              { "field": "expected", "type": "quantitative", "format": ".1%", "title": "Expected (v2)" }
            ]
          }
        }
      ],
      "resolve": { "scale": { "x": "shared", "y": "shared" } },
      "config": methodologyAxisConfig
    };
    vegaEmbed("#war-v2-fit-scatter", spec, { actions: false }).catch(console.error);
  })();

  // --- Residual histogram, Democratic vs. Republican ----------------------
  (function () {
    const residuals = {{ site.data.war_v2_fit_sample | jsonify }}.map((r) => ({
      party: r.party,
      residual: r.actual - r.expected,
    }));
    const colorDem = methodologyCssVar("--series-dem");
    const colorRep = methodologyCssVar("--series-rep");

    function meanOf(party) {
      const vals = residuals.filter((r) => r.party === party).map((r) => r.residual);
      return vals.reduce((a, b) => a + b, 0) / vals.length;
    }
    const demMean = meanOf("Democratic");
    const repMean = meanOf("Republican");
    const fmtPts = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + " points";
    document.getElementById("dem-residual-note").textContent = fmtPts(demMean);
    document.getElementById("rep-residual-note").textContent = fmtPts(repMean);

    const meanLines = [
      { party: "Democratic", residual: demMean },
      { party: "Republican", residual: repMean },
    ];
    const spec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "width": "container",
      "height": 240,
      "background": null,
      "layer": [
        {
          "data": { "values": [{ "x": 0 }] },
          "mark": { "type": "rule", "strokeDash": [4, 2] },
          "encoding": { "x": { "field": "x", "type": "quantitative" }, "color": { "value": methodologyCssVar("--gridline") } }
        },
        {
          "data": { "values": residuals },
          "transform": [{ "bin": { "step": 0.02 }, "field": "residual", "as": ["bin_lo", "bin_hi"] }],
          "mark": { "type": "bar", "opacity": 0.55 },
          "encoding": {
            "x": { "field": "bin_lo", "bin": "binned", "type": "quantitative", "title": "Residual (actual − expected share)", "axis": { "format": "+.0%" } },
            "x2": { "field": "bin_hi" },
            "y": { "aggregate": "count", "type": "quantitative", "title": "Candidate-races", "stack": null },
            "color": {
              "field": "party", "type": "nominal", "title": "Party",
              "scale": { "domain": ["Democratic", "Republican"], "range": [colorDem, colorRep] }
            },
            "tooltip": [
              { "field": "party", "title": "Party" },
              { "aggregate": "count", "title": "Candidate-races" }
            ]
          }
        },
        {
          "data": { "values": meanLines },
          "mark": { "type": "rule", "size": 2 },
          "encoding": {
            "x": { "field": "residual", "type": "quantitative" },
            "color": {
              "field": "party", "type": "nominal", "legend": null,
              "scale": { "domain": ["Democratic", "Republican"], "range": [colorDem, colorRep] }
            },
            "tooltip": [
              { "field": "party", "title": "Party" },
              { "field": "residual", "type": "quantitative", "format": "+.1%", "title": "Mean residual" }
            ]
          }
        }
      ],
      "config": methodologyAxisConfig
    };
    vegaEmbed("#war-v2-residual-histogram", spec, { actions: false }).catch(console.error);
  })();
  {% endif %}
</script>
