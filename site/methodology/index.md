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

**The WAR regression below uses a different, *structural* version of this
lean** — the plain average of `lean_dem_share` across every election year
on record for that district within its current redistricting vintage,
rather than the one specific year's own apportioned value. Splitting a
district's long-run partisan baseline from a given cycle's national mood
this way is the standard Gelman & King "normal vote" decomposition (cited
below) — and, practically, it's much less collinear with the model's
separate statewide-tide term than two numbers both freshly derived from
the same year's baseline race used to be. Every other use of lean on this
site (the headline stat above, the trend-over-time chart, the
competitiveness bucket) is still the plain per-year value.

## WAR (wins above replacement)

**WAR = actual two-party vote share − expected share from a fitted
regression.** Positive means a candidate outperformed what the model
expected; negative means they underperformed it. It's reported per
contested race, for Democratic and Republican candidates only — a
minor-party candidate has no meaningful two-party baseline to compare
against, and an uncontested race has no meaningful "actual" side (an
unopposed candidate's near-100% share is mechanically inflated, not
earned against real competition) — so WAR is null in both cases.

The site fits **one regression** — district lean, statewide tide, and
incumbency, each with its own Democratic-vs-Republican interaction term,
plus district demographics and campaign fundraising wherever a race's own
data supports them — and shows every race's WAR from that single model.
A race's expected share automatically includes whichever of the
demographics/fundraising terms its own data supports (both, either, or
neither); every page's own **Factors** column says which pieces actually
went into that specific number.

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

## The regression model

**WAR = actual two-party vote share − this one fitted regression's
expected share**, where the regression is:

> *own-party share ~ intercept + Democratic + district lean + district
> lean × Democratic + statewide tide + statewide tide × Democratic +
> incumbency + incumbency × Democratic +
> district demographics + campaign fundraising*

"Own-party" means lean, tide, and the actual share are all already
flipped to the candidate's own party's perspective (a Republican's
own_lean is `1 − ` the district's structural lean, same for tide) — the
same symmetry the plain lean-only definition above already uses, so one
fit covers both parties' *shared* behavior. The `× Democratic` terms then
let a Democrat's fitted relationship to lean/tide/incumbency differ from
a Republican's on top of that shared baseline — see "Party interaction
terms" below for why.

**Statewide tide** is a fundamental beyond district lean itself: the
*unapportioned*, whole-state two-party Democratic share on that year's
baseline race (Governor or President), as opposed to `lean_dem_share`,
which is that same race apportioned down to one district. Splitting them
apart lets the model separate a district's own persistent partisanship
from a given cycle's overall national/state mood — the same normal-vote-
plus-national-tide idea behind Gelman & King (1990), cited above, rather
than lean alone conflating the two.

**Incumbency** is a single incumbent/non-incumbent term (see "Incumbency
and open seats" below) rather than one term per consecutive-term bucket
(1st/2nd/3rd-or-later, as an earlier version of this fit used) — that
split's three posterior means landed close enough together (this site's
data doesn't show a strong "sophomore surge" or a fading effect in later
terms) that the extra parameters weren't earning their keep over one
shared incumbency effect.

### Party interaction terms

Splitting a scatter of this model's own residuals (actual share minus
expected share, before these interaction terms existed) by party revealed
a real, found-live asymmetry: Democratic candidates' residuals averaged
positive, Republican candidates' averaged negative, by close to equal and
opposite amounts (see the residual histogram further down, which now
shows the *corrected* picture). That's not a contradiction of the
own-party symmetry above — a pooled fit with one shared `own_lean` slope,
one shared `own_tide` slope, and one shared `incumbent` term literally
cannot tell a Democrat in a D+10 district from a Republican in an R+10
one. What it *can* miss is whether incumbent and non-incumbent
candidates relate to lean/tide identically between the two parties. In
Massachusetts specifically that looks shaky: the legislature's real,
well-documented Democratic supermajority is larger than the state's own
top-of-ticket vote share alone would predict, and this backfill's own
composition reflects it — most Democratic candidates in it are
incumbents, while most Republicans are non-incumbent challengers running
in a chamber their party rarely controls. A shared coefficient set in
that situation lands closer to whichever pattern is more common in the
data, leaving same-direction residuals within each party even though the
pooled average comes out to zero by construction.

Rather than fit two fully separate regressions per party (which would
throw away the fact that both parties share a lot of the same underlying
relationship, and would double the number of poorly-identified
coefficients), each core term gets one additional `× Democratic` delta
term — a **partial-pooling design**: the delta's own prior is centered at
0 with **half** the width of its corresponding shared term's prior, so
the fit only pulls a term away from full pooling when the data actually
supports a real asymmetry, rather than assuming symmetry or independence
outright.

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
- Incumbents are a **minority of races** (roughly a quarter of this
  fit's sample), and the demographics/finance terms below are informed
  by samples small enough that an unconstrained estimate would be
  mostly noise.

A Gaussian prior on each coefficient shrinks it toward a substantively
reasonable value in proportion to how little the data actually pins it
down — real regularization, not an ad hoc penalty — and the fit reports a
full posterior (mean, standard deviation, and a 95% credible interval
taken directly from the sampled draws), not just a point estimate.

**Concretely, here's what that regularization does to one term.** Before
seeing any data, the prior for an incumbent's edge was a wide,
weakly-informed guess (mean {{ site.data.war_model.coefficients.incumbent.prior_mean | times: 100 | round: 0 }}
points, standard deviation {{ site.data.war_model.coefficients.incumbent.prior_sd | times: 100 | round: 0 }}
points — that shape, below). After fitting on
{{ site.data.war_model.n_incumbent }} real incumbent races, the
posterior is both narrower and shifted to
{{ site.data.war_model.coefficients.incumbent.posterior_mean | times: 100 | round: 1 }}
points — the data had enough to say something much more specific than the
prior alone did, which is exactly what "the data pins it down" should
look like:

<div id="prior-posterior-chart" role="img" aria-label="Density chart comparing the prior and posterior distributions for the incumbency coefficient"></div>

As of the last full pipeline run, on
{{ site.data.war_model.n }} contested major-party candidate-races
(R² = {{ site.data.war_model.r_squared }}), every core and party-interaction
term's posterior mean and 95% credible interval:

<div id="war-model-forest-chart" role="img" aria-label="Forest plot of the regression's core and party-interaction coefficients with 95% credible intervals"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| Intercept | {{ site.data.war_model.coefficients.intercept.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_model.coefficients.intercept.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_model.coefficients.intercept.ci_95_high | times: 100 | round: 1 }}] |
| Democratic | {{ site.data.war_model.coefficients.is_dem.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_model.coefficients.is_dem.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_model.coefficients.is_dem.ci_95_high | times: 100 | round: 1 }}] |
| District lean | {{ site.data.war_model.coefficients.own_lean.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.own_lean.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.own_lean.ci_95_high | round: 3 }}] |
| District lean × Democratic | {{ site.data.war_model.coefficients.own_lean_x_dem.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.own_lean_x_dem.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.own_lean_x_dem.ci_95_high | round: 3 }}] |
| Statewide tide | {{ site.data.war_model.coefficients.own_tide.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.own_tide.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.own_tide.ci_95_high | round: 3 }}] |
| Statewide tide × Democratic | {{ site.data.war_model.coefficients.own_tide_x_dem.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.own_tide_x_dem.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.own_tide_x_dem.ci_95_high | round: 3 }}] |
| Incumbent | +{{ site.data.war_model.coefficients.incumbent.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_model.coefficients.incumbent.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_model.coefficients.incumbent.ci_95_high | times: 100 | round: 1 }}] |
| Incumbent × Democratic | {{ site.data.war_model.coefficients.incumbent_x_dem.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.war_model.coefficients.incumbent_x_dem.ci_95_low | times: 100 | round: 1 }}, {{ site.data.war_model.coefficients.incumbent_x_dem.ci_95_high | times: 100 | round: 1 }}] |

District lean's coefficient sitting well below 1.0 is a real finding, not
a fitting artifact — checked directly against plain least squares on the
same data, which lands in the same neighborhood. It means a district's
own structural lean, once that year's statewide tide is already in the
model, only partially carries through to actual legislative vote share —
plausibly some mix of the area-weighted apportionment noise documented
above and real candidate-to-candidate variation legislative races carry
that a top-of-ticket baseline can't see. The `× Democratic` rows are each
centered near a much smaller magnitude than their shared term, and a
partial-pooling fit lets the data decide term by term which ones move: on
the last run, `own_lean_x_dem` and `incumbent_x_dem` both have 95%
intervals clear of zero (a real, if modest, party difference in how
strongly lean and incumbency translate into vote share), while `is_dem`
and `own_tide_x_dem` straddle zero (no clear evidence of a party
difference in the baseline or the tide response beyond what lean and
incumbency already explain).

**What that fit actually looks like against every one of those races**:
each point is one contested major-party candidate-race, this model's
expected share (x) against what actually happened (y). A point sitting
exactly on the dashed diagonal means the model called it perfectly; above
the line is a real overperformance (positive WAR), below is an
underperformance — the same information the site's own WAR numbers
carry, just all {{ site.data.war_model.n }} of them at once instead of one
race at a time.

<div id="war-fit-scatter" role="img" aria-label="Scatter plot of the regression's expected two-party share against each candidate's actual share, colored by party"></div>

**Split by party, here's the residual picture the party-interaction terms
above were added to correct**: Democratic candidates' residuals (actual
share minus expected) average <span id="dem-residual-note">…</span>;
Republican candidates' average <span id="rep-residual-note">…</span> —
both should now sit much closer to zero than the roughly ±5-point gap a
purely-pooled fit (no `× Democratic` terms at all) showed on this same
data:

<div id="war-residual-histogram" role="img" aria-label="Histogram of the regression's residuals (actual minus expected share), separately for Democratic and Republican candidates"></div>

Whatever asymmetry remains here is what the shrinkage priors on the
`× Democratic` terms deliberately left on the table rather than fully
absorbing — half-width priors regularize toward the shared, pooled
coefficients by design, so a real but modest party-specific pattern can
still show up as a small residual gap even after fitting it, rather than
being eliminated outright. That's the accepted tradeoff of partial
pooling over two fully separate per-party regressions: less noise-driven
overfitting to each party's own thinner sample, at the cost of not fully
zeroing out a real asymmetry if one exists.

Every district and seat page has a "What drives replacement level" chart
breaking a race's most recent contested year into these pieces (intercept,
lean, tide, incumbency, demographics and/or fundraising where a race's own
data supports them, and the WAR residual) for each candidate, and a
candidate's own page charts their actual share against this model's
expected share, and the same decomposition, across every year they ran —
the gap between the two lines on the first chart *is* WAR, made visible.

**A related, worth-naming property**: in `own_lean`/`own_tide`'s own
terms, the two candidates in a race are exact mirrors
(`own_lean` + the other candidate's `own_lean` = 1, always, since a
district's structural lean is still one number split between the two
parties' perspectives) — the "Lean" and "Statewide tide" bars for both
candidates in the attribution chart are both genuinely positive because a
district's baseline splits into two positive shares, not because the
model favors both sides at once. The **intercept** (plus its `is_dem`
delta), though, is a single fitted pair of constants applied identically
to every race of that party, not split between the two opposing
candidates in one race — so unlike a plain lean-only baseline (where the
two opposing candidates' expected shares always summed to exactly 100%,
and their WAR values were exact opposites), **this model's two expected
shares in a race don't sum to 100%**, and the two WAR values aren't
required to cancel out. That's an accepted consequence of letting the
regression fit its own intercept rather than assuming a lean-only
"coefficient on lean = 1, no intercept" structure — not an error in the
numbers, but a real change in what the model guarantees.

### Demographics and campaign fundraising

The same regression also carries district-level demographics and a
candidate's own campaign fundraising as ordinary terms — not two
separate diagnostic fits reported only on this page, the way an earlier
version of this site's model worked. **Each term folds into a candidate's
actual WAR number wherever that specific district or candidate has the
data to support it**, and — new in this design — a single race can now
carry both a demographics contribution and a fundraising contribution at
once, which the old "resolve to exactly one extension" design could never
represent.

That's possible because of how each term handles missing data: rather
than an explicit indicator/dummy variable marking "this term doesn't
apply here," each of these five covariates is centered on its own mean
*among the rows that actually have it*, and a row missing it gets that
same mean substituted — so its centered value is exactly 0 and it
contributes nothing to that term's fitted share, while the row's
lean/tide/incumbency values still fully inform the shared core terms
above. Mathematically that's equivalent to "this term simply doesn't
apply to this race," without needing a separate dummy column or a second
model.

{% if site.data.war_model.coefficients.bachelors_pct %}
**Demographics** adds district-level Census fields (2020 PL 94-171 + 2022
ACS 5-year, current 2022-present vintage only) — bachelor's-degree-or-
higher share of population (the "diploma divide" variable most associated
with recent-era partisan realignment), Hispanic-or-Latino population
share, voting-age population share, and median household income (per
$10,000):

<div id="war-demographics-forest-chart" role="img" aria-label="Forest plot of the demographics terms' coefficients with 95% credible intervals"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| Bachelor's degree % | {{ site.data.war_model.coefficients.bachelors_pct.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.bachelors_pct.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.bachelors_pct.ci_95_high | round: 3 }}] |
| Hispanic or Latino % | {{ site.data.war_model.coefficients.hispanic_pct.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.hispanic_pct.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.hispanic_pct.ci_95_high | round: 3 }}] |
| Voting-age % | {{ site.data.war_model.coefficients.voting_age_pct.posterior_mean | round: 3 }} | [{{ site.data.war_model.coefficients.voting_age_pct.ci_95_low | round: 3 }}, {{ site.data.war_model.coefficients.voting_age_pct.ci_95_high | round: 3 }}] |
| Median household income (per $10k) | {{ site.data.war_model.coefficients.income_10k.posterior_mean | round: 4 }} | [{{ site.data.war_model.coefficients.income_10k.ci_95_low | round: 4 }}, {{ site.data.war_model.coefficients.income_10k.ci_95_high | round: 4 }}] |

Fit on {{ site.data.war_model.n_demographics }} candidate-races with at
least a bachelor's-degree match — a district missing the fuller PL
94-171 match (Hispanic/voting-age population specifically) still
contributes its bachelor's-degree term, via the same per-covariate
mean-centering described above, rather than being dropped from this term
entirely (see `demographics_tier` on district/seat pages' own data — a
district shows `"full"`, `"core"`, or no Demographics section at all).

No interaction with tide (e.g. "does a district's education level swing
more or less with the national mood than average") is fit here — an
interaction is only as identified as the number of distinct election
years behind it, and demographics only covers the current, 2022-present
vintage's election years on record so far, nowhere near enough to trust
one over just a couple of elections' worth of noise.
{% endif %}

{% if site.data.war_model.coefficients.log_raised %}
**Campaign finance** adds a candidate's own OCPF total raised that cycle
(log-transformed — fundraising totals are heavily right-skewed),
restricted to candidates `campaign_finance_match` actually matched to an
OCPF filer (see "Campaign finance" below):

<div id="war-finance-forest-chart" role="img" aria-label="Forest plot of the campaign fundraising term's coefficient with a 95% credible interval"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| log(total raised + 1) | {{ site.data.war_model.coefficients.log_raised.posterior_mean | round: 4 }} | [{{ site.data.war_model.coefficients.log_raised.ci_95_low | round: 4 }}, {{ site.data.war_model.coefficients.log_raised.ci_95_high | round: 4 }}] |

Fit on {{ site.data.war_model.n_finance }} candidate-races with a matched
OCPF total, across the full 2002-2024 backfill. A positive, clearly-
nonzero coefficient (95% credible interval entirely above zero) says
money and vote share move together in this data even after accounting
for lean, tide, incumbency, and their party-interaction terms.

**On a per-race attribution chart, the Fundraising bar is centered on
this fit's own mean log-dollar total ({{ site.data.war_model.reference_values.log_raised | round: 2 }}),
not on $0.** `log(total raised + 1)`'s coefficient above is genuinely
small, but its predictor lives on a log-dollar scale (typically 7–14
across real candidates) rather than the 0–1 fraction lean, tide, and the
demographics terms use — multiplying that small coefficient by a raw
value in the 7–14 range, rather than by how far it sits from a *typical*
matched candidate's total, would make the bar disproportionately large
purely from comparing against an impossible $0-raised baseline.
Centering it avoids that: the bar reads as "how this candidate's
fundraising compares to a typical matched candidate's," in real
vote-share points, with the removed constant folded into the chart's
Baseline bar instead — the total predicted share for the race is
unchanged. The same centering-not-zero convention applies to the
Demographics bar above.
{% endif %}

Every fitted effect on this page, including these two extension terms,
appears together on one standardized scale in the forest plot near the
top of this page.

Wherever demographics and/or fundraising apply, they're threaded into
their race's own attribution chart alongside the core components: a
candidate page's "What drives replacement level, by year" chart shows a
Fundraising and/or Demographics segment for any year that candidate's own
data supports it, and a district or seat page's chart does the same for
whichever candidates in that race have a match. Each of those pages also
has a companion forest-style chart, right below the stacked bar, showing
the same components as a point plus an approximate 95% interval — the
stacked bar is good at showing what a share is made of, not at showing
how confidently. Those intervals use the same delta-method shortcut as
everywhere else on this page: each component's uncertainty approximated
from that component's own coefficient(s)' posterior SD (combining the
shared and `× Democratic` terms as
`sqrt(shared_sd² + (is_dem × delta_sd)²)` where a party-interaction term
applies), scaled by the covariate's own value where applicable, and
treating coefficients as independent of each other rather than
propagating their full joint posterior — a known simplification, not a
full solution.

## U.S. House and U.S. Senate

This site also covers MA's federal delegation — nine U.S. House seats and
one U.S. Senate seat — from the same PD43+ source as the state House and
Senate, back to 2002.

**U.S. House gets the same district/seat/candidate treatment as the state
chambers, including its own WAR model** — but a genuinely *separate* fit
from the state House/Senate regression above, not pooled into it. MA's nine
congressional districts are a different kind of race from 160 state House
or 40 state Senate seats: much larger, statewide-spanning geographies,
fewer, and dominated by long-serving incumbents in safe seats, so folding
a few hundred congressional candidate-races into a fit trained on 1,500+
state-legislative ones would let the far larger sample determine a
coefficient meant to describe a different electorate. The U.S. House model
is otherwise the same shape as the state model's core terms (own-party
lean, tide, and incumbency, with the same `× Democratic` interaction
convention) — just without the demographics and campaign-fundraising
extensions, for a real, separate reason each:

- **No demographics extension.** This site's Census matching
  (`demographics_match.py`) is built against the state House/Senate
  district rosters; extending it to nine congressional districts would
  need its own crosswalk, not attempted this round.
- **No campaign-finance extension.** OCPF, this site's only
  campaign-finance source, covers state-filed candidates — federal
  candidates file with the FEC instead, a separate data source this site
  doesn't fetch yet. A candidate page for a U.S. House member accordingly
  has no "Campaign finance" section.

On the last full run: n=116 contested major-party candidate-races
(2002-2024), R²=0.89, own-district-lean coefficient +0.50, own-statewide-
tide −0.01, incumbency +0.04 — see `site/_data/us_house_war_model.yml`
for the live figures. No primary model for U.S. House either, for the same
reason as the demographics/finance gaps above (a separate fit is real work,
not attempted this round): a congressional primary candidate's page still
shows their raw vote share and field size, just no fitted "expected share"
overlay the way a state legislative primary candidate's does.

**U.S. Senate has no district/seat/WAR treatment at all** — a deliberate
choice, not an oversight. MA elects only one U.S. Senator at a time, on a
staggered six-year term, so there's no second Massachusetts to compare a
Senate result against and no meaningful "replacement level" the way a
multi-seat chamber has one. Instead, the [U.S. Senate
page]({{ '/us-senate/' | relative_url }}) is a straightforward results-and-
candidate-history table, built directly from PD43+'s statewide U.S. Senate
results with no apportionment, crosswalk, or regression involved.

## Primary elections

Massachusetts's 2026 state primary happened days before this section was
written, and PD43+ has always carried primary results alongside the
general — fetched every year of this site's backfill, just not modeled or
shown until now. This site now gives every primary its own full
attribution: **primary-only candidates get a full candidate page**, even
one who never appears in a general, and every district/seat page gets its
own "Primary results" section alongside "Election results."

A primary isn't a two-party race, so it needs its own model rather than
reusing the general regression above: a two-candidate primary's "fair"
share is 50%, a four-candidate primary's is 25%, and there's no
Democratic-vs-Republican axis to split by (a Democratic primary is scored
against other Democrats, a Republican primary against other Republicans).
**Primary WAR = actual share of that primary's vote − this separate
fitted regression's expected share**, where the regression is:

> *excess share ~ intercept + incumbency + incumbency × statewide tide +
> incumbency × district lean + campaign fundraising*

**Excess share** is a candidate's actual primary share minus that
primary's own **fair share** (`1 ÷ number of candidates`) — the same role
`lean_dem_share` plays as a "no-information" baseline for the general
model, but derived from the field's own size rather than a separate
baseline race, since a primary field can be 2-way, 3-way, or larger from
year to year. **Incumbency** only ever appears here interacted with tide
and lean, never as its own bare main effect — there's no reason a
non-incumbent's own primary share should track that year's statewide mood
or the district's general-election partisanship the way an incumbent
defending a seat plausibly might, so those two interaction terms are
strictly narrower claims than the general model's own tide/lean main
effects, not their primary-model equivalents.

Fit on {{ site.data.primary_war_model.n }} contested major-party primary
candidate-races (R² = {{ site.data.primary_war_model.r_squared }}),
{{ site.data.primary_war_model.n_incumbent }} of them an incumbent
defending their own seat and {{ site.data.primary_war_model.n_finance }}
with a matched OCPF total:

<div id="primary-war-forest-chart" role="img" aria-label="Forest plot of the primary regression's coefficients with 95% credible intervals"></div>

| Term | Posterior mean | 95% credible interval |
|---|---|---|
| Intercept | {{ site.data.primary_war_model.coefficients.primary_intercept.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.primary_war_model.coefficients.primary_intercept.ci_95_low | times: 100 | round: 1 }}, {{ site.data.primary_war_model.coefficients.primary_intercept.ci_95_high | times: 100 | round: 1 }}] |
| Incumbent | +{{ site.data.primary_war_model.coefficients.primary_incumbent.posterior_mean | times: 100 | round: 1 }} pts | [{{ site.data.primary_war_model.coefficients.primary_incumbent.ci_95_low | times: 100 | round: 1 }}, {{ site.data.primary_war_model.coefficients.primary_incumbent.ci_95_high | times: 100 | round: 1 }}] |
| Incumbent × statewide tide | {{ site.data.primary_war_model.coefficients.primary_incumbent_x_tide.posterior_mean | round: 3 }} | [{{ site.data.primary_war_model.coefficients.primary_incumbent_x_tide.ci_95_low | round: 3 }}, {{ site.data.primary_war_model.coefficients.primary_incumbent_x_tide.ci_95_high | round: 3 }}] |
| Incumbent × district lean | {{ site.data.primary_war_model.coefficients.primary_incumbent_x_lean.posterior_mean | round: 3 }} | [{{ site.data.primary_war_model.coefficients.primary_incumbent_x_lean.ci_95_low | round: 3 }}, {{ site.data.primary_war_model.coefficients.primary_incumbent_x_lean.ci_95_high | round: 3 }}] |
| log(total raised + 1) | {{ site.data.primary_war_model.coefficients.primary_log_raised.posterior_mean | round: 4 }} | [{{ site.data.primary_war_model.coefficients.primary_log_raised.ci_95_low | round: 4 }}, {{ site.data.primary_war_model.coefficients.primary_log_raised.ci_95_high | round: 4 }}] |

An incumbent's edge in their own primary
(+{{ site.data.primary_war_model.coefficients.primary_incumbent.posterior_mean | times: 100 | round: 1 }}
points over an even split, before the tide/lean interactions) comes in
larger than the general model's own incumbency term — a real, plausible
difference: a primary electorate skews toward a party's most engaged
voters, among whom a sitting legislator's name recognition and local
relationships plausibly matter even more than with a general audience.
The tide and lean interaction terms pull in different directions — a
positive `incumbent × lean` (an incumbent does better in their own
primary the more the district structurally favors their party) alongside
a negative `incumbent × tide` (an incumbent does worse in their own
primary the more that year's statewide mood favors their party) — read
together, that's consistent with an incumbent's primary strength coming
more from durable local support than from a favorable statewide year,
though with this sample's size
({{ site.data.primary_war_model.n_incumbent }} incumbent rows) neither
term should be read as a precise estimate on its own.

<div id="primary-war-fit-scatter" role="img" aria-label="Scatter plot of the primary regression's expected share against each candidate's actual share, colored by party"></div>

**Every candidate's raw prediction above is rescaled by one shared,
race-level factor so that race's own candidates' expected shares sum to
exactly 1** — a real second step, not just how the numbers happen to come
out. Fit directly, an uncontested incumbent's raw prediction (fair share
already at 100%, plus a real positive incumbency effect on top) can read
well above 100%, which is right in what it's measuring but easy to misread
as a data error for a single candidate's own "share of this race's vote."
Rescaling every candidate in the race by the same factor — `1 ÷ (sum of
their raw predictions)` — fixes that without discarding the signal: a
candidate the raw model favors more still ends up with a higher normalized
share than one it favors less, and for a genuinely uncontested race (one
candidate, nothing to rescale against but themselves) it always lands
exactly at 100%, matching the only possible actual result. The regression
itself, and every coefficient shown above, is unchanged — only this last
step, turning those coefficients into one specific race's predicted split,
is new.

On a candidate, district, or seat page's attribution chart, a primary's
**Baseline** bar combines its (rescaled) equal fair share and fitted
intercept into one slice (rather than two, the way the general model
keeps Baseline and Lean separate), since a primary has no separate lean
term to isolate; **Incumbency** already carries both interaction terms
combined; **Fundraising** and **WAR (residual)** work the same way as the
general model's own bars, centered the same mean-log-dollar way described
above, with the same rescale factor applied to every component so they
still sum exactly to the (rescaled) expected share. A primary has no
Lean, Statewide tide, or Demographics slice of its own — a primary's bar
sits beside that year's general bar, labeled directly above it ("General,"
"Primary," or "Special" for a special-election primary) rather than via a
legend, since two legend-based approaches tried first (shading, then a
bordered outline) each turned out to have a real rendering gap at legend
scale.

**Special elections are included here; generals are not, yet.** PD43+
posts a special election's own primary and general separately, same as a
regular cycle's, and this site's backfill loop discovers every primary
year independent of whether that year's baseline Governor/President race
exists yet — needed for 2026, whose regular-cycle primary and general
aren't posted as of this writing, but whose special-election primaries
already are. Generals keep their pre-existing scope, excluding specials:
a special general shares a calendar year with that same district's own
regular-cycle general in 30-plus district-years across this site's
2002-2024 backfill, which the current one-row-per-(district, year)
incumbency-chain logic isn't built to represent safely. A primary carries
no such collision risk (each is keyed to its own PD43+ `election_id`, so a
regular and a special primary in the same district/party/year each get
their own row), so extending special elections there was the unambiguous
first step; extending the general model to handle two same-year generals
per district remains a real gap this site hasn't closed.

**One consequence of rescaling, worth naming**: a candidate's own
`primary_expected_share` is now specific to who else was in that
particular race, not a portable, standalone quantity — the same raw
prediction for a given incumbent rescales differently depending on how
many opponents they had and how the model favored each of them. That's
the intended behavior (a "share of this race's vote" only means anything
relative to that race's own field), but it's a real change from the
general model's `expected_share_resolved`, which is computed the same way
regardless of the specific opponent a candidate happened to face.

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
  // fields inside a script tag. site.data.war_model/war_fit_sample are
  // plain Python-written YAML (numbers and short strings only, no
  // Document risk), so jsonify-ing them directly here is safe.
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

  {% if site.data.war_model %}
  // --- Prior vs. posterior: incumbent term ------------------------------
  (function () {
    function normalPdf(x, mean, sd) {
      return Math.exp(-0.5 * Math.pow((x - mean) / sd, 2)) / (sd * Math.sqrt(2 * Math.PI));
    }
    const priorMean = {{ site.data.war_model.coefficients.incumbent.prior_mean | jsonify }};
    const priorSd = {{ site.data.war_model.coefficients.incumbent.prior_sd | jsonify }};
    const postMean = {{ site.data.war_model.coefficients.incumbent.posterior_mean | jsonify }};
    const postSd = {{ site.data.war_model.coefficients.incumbent.posterior_sd | jsonify }};
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
        "x": { "field": "x", "type": "quantitative", "title": "Incumbent — coefficient value", "axis": { "format": "+.0%" } },
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
  // Shared by every forest plot on this page — the core+interaction
  // plot and the two extension-term plots below — so each only has to
  // supply its own coefficients object, [label, key] term list, target
  // element id, and accent color. All read from the one site.data.war_model
  // fit now — there's no second or third model's coefficients object to
  // pass in anymore.
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
          "mark": { "type": "rule", "strokeDash": [6, 3], "strokeWidth": 1.5 },
          "encoding": { "x": { "field": "x", "type": "quantitative", "title": xTitle }, "color": { "value": methodologyCssVar("--text-secondary") } }
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
    "war-model-forest-chart",
    {{ site.data.war_model.coefficients | jsonify }},
    [
      ["Intercept", "intercept"],
      ["Democratic", "is_dem"],
      ["District lean", "own_lean"],
      ["District lean × Dem.", "own_lean_x_dem"],
      ["Statewide tide", "own_tide"],
      ["Statewide tide × Dem.", "own_tide_x_dem"],
      ["Incumbent", "incumbent"],
      ["Incumbent × Dem.", "incumbent_x_dem"],
    ],
    methodologyCssVar("--war-incumbency"),
    280
  );

  // --- Model overview: every fitted effect, one comparable scale ---------
  // One model now, not three — "model" below labels each row by term
  // *family* (core fundamentals, their Democratic-interaction deltas,
  // demographics, campaign finance) purely for chart readability, not
  // because these are separate fits.
  (function () {
    const coefs = {{ site.data.war_model.coefficients | jsonify }};
    const rows = [
      { term: "District lean", family: "Core", key: "own_lean" },
      { term: "Statewide tide", family: "Core", key: "own_tide" },
      { term: "Incumbency", family: "Core", key: "incumbent" },
      { term: "Democratic (intercept delta)", family: "Party interaction", key: "is_dem" },
      { term: "District lean × Dem.", family: "Party interaction", key: "own_lean_x_dem" },
      { term: "Statewide tide × Dem.", family: "Party interaction", key: "own_tide_x_dem" },
      { term: "Incumbency × Dem.", family: "Party interaction", key: "incumbent_x_dem" },
    ].map((r) => {
      const c = coefs[r.key];
      return { term: r.term, family: r.family, mean: c.standardized_mean, lo: c.standardized_ci_95_low, hi: c.standardized_ci_95_high };
    });
    {% if site.data.war_model.coefficients.bachelors_pct %}
    [
      ["Bachelor's degree %", "bachelors_pct"],
      ["Hispanic or Latino %", "hispanic_pct"],
      ["Voting-age %", "voting_age_pct"],
      ["Median household income", "income_10k"],
    ].forEach(([term, key]) => {
      const c = coefs[key];
      rows.push({ term: term, family: "Demographics", mean: c.standardized_mean, lo: c.standardized_ci_95_low, hi: c.standardized_ci_95_high });
    });
    {% endif %}
    {% if site.data.war_model.coefficients.log_raised %}
    (function () {
      const c = coefs.log_raised;
      rows.push({ term: "Campaign fundraising (logged)", family: "Campaign finance", mean: c.standardized_mean, lo: c.standardized_ci_95_low, hi: c.standardized_ci_95_high });
    })();
    {% endif %}
    const termOrder = rows.map((r) => r.term);
    const familyColor = {
      "Core": methodologyCssVar("--war-incumbency"),
      "Party interaction": methodologyCssVar("--war-tide"),
      "Demographics": methodologyCssVar("--war-extra"),
      "Campaign finance": methodologyCssVar("--war-fundraising"),
    };
    const spec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "width": "container",
      "height": Math.max(160, rows.length * 34),
      "background": null,
      "layer": [
        {
          "data": { "values": [{ "x": 0 }] },
          "mark": { "type": "rule", "strokeDash": [6, 3], "strokeWidth": 1.5 },
          "encoding": { "x": { "field": "x", "type": "quantitative", "title": "Standardized effect (vote-share points per 1 SD of predictor)" }, "color": { "value": methodologyCssVar("--text-secondary") } }
        },
        {
          "data": { "values": rows },
          "mark": { "type": "rule", "size": 2 },
          "encoding": {
            "y": { "field": "term", "type": "nominal", "sort": termOrder, "title": null },
            "x": { "field": "lo", "type": "quantitative" },
            "x2": { "field": "hi" },
            "color": { "field": "family", "type": "nominal", "title": "Term family", "scale": { "domain": Object.keys(familyColor), "range": Object.values(familyColor) } }
          }
        },
        {
          "data": { "values": rows },
          "mark": { "type": "point", "filled": true, "size": 90 },
          "encoding": {
            "y": { "field": "term", "type": "nominal", "sort": termOrder, "title": null },
            "x": { "field": "mean", "type": "quantitative" },
            "color": { "field": "family", "type": "nominal", "title": "Term family", "scale": { "domain": Object.keys(familyColor), "range": Object.values(familyColor) } },
            "tooltip": [
              { "field": "term", "title": "Term" },
              { "field": "family", "title": "Term family" },
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

  {% if site.data.war_model.coefficients.bachelors_pct %}
  renderForestChart(
    "war-demographics-forest-chart",
    {{ site.data.war_model.coefficients | jsonify }},
    [
      ["Bachelor's degree %", "bachelors_pct"],
      ["Hispanic or Latino %", "hispanic_pct"],
      ["Voting-age %", "voting_age_pct"],
      ["Median household income (per $10k)", "income_10k"],
    ],
    methodologyCssVar("--war-extra"),
    180
  );
  {% endif %}

  {% if site.data.war_model.coefficients.log_raised %}
  renderForestChart(
    "war-finance-forest-chart",
    {{ site.data.war_model.coefficients | jsonify }},
    [["log(total raised + 1)", "log_raised"]],
    methodologyCssVar("--war-fundraising"),
    90
  );
  {% endif %}
  {% endif %}

  {% if site.data.primary_war_model %}
  renderForestChart(
    "primary-war-forest-chart",
    {{ site.data.primary_war_model.coefficients | jsonify }},
    [
      ["Intercept", "primary_intercept"],
      ["Incumbent", "primary_incumbent"],
      ["Incumbent × tide", "primary_incumbent_x_tide"],
      ["Incumbent × lean", "primary_incumbent_x_lean"],
      ["log(total raised + 1)", "primary_log_raised"],
    ],
    methodologyCssVar("--war-incumbency"),
    220
  );
  {% endif %}

  {% if site.data.primary_war_fit_sample %}
  // --- Primary: actual vs. expected share scatter -------------------------
  (function () {
    const fitSample = {{ site.data.primary_war_fit_sample | jsonify }};
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
          "mark": { "type": "point", "filled": true, "opacity": 0.4, "size": 40 },
          "encoding": {
            "x": { "field": "expected", "type": "quantitative", "title": "Expected share (primary model)", "axis": { "format": "%" } },
            "y": { "field": "actual", "type": "quantitative", "title": "Actual share", "axis": { "format": "%" }, "scale": { "domain": [0, 1] } },
            "shape": {
              "field": "is_special", "type": "nominal", "title": "Special election?",
              "scale": { "domain": [false, true], "range": ["circle", "triangle-up"] }
            },
            "color": {
              "field": "party", "type": "nominal", "title": "Party",
              "scale": { "domain": ["Democratic", "Republican"], "range": [colorDem, colorRep] }
            },
            "tooltip": [
              { "field": "year", "title": "Year" },
              { "field": "party", "title": "Party" },
              { "field": "is_special", "title": "Special election?" },
              { "field": "actual", "type": "quantitative", "format": ".1%", "title": "Actual" },
              { "field": "expected", "type": "quantitative", "format": ".1%", "title": "Expected" }
            ]
          }
        }
      ],
      "resolve": { "scale": { "x": "shared", "y": "shared" } },
      "config": methodologyAxisConfig
    };
    vegaEmbed("#primary-war-fit-scatter", spec, { actions: false }).catch(console.error);
  })();
  {% endif %}

  {% if site.data.war_fit_sample %}
  // --- Actual vs. expected share scatter ----------------------------------
  (function () {
    const fitSample = {{ site.data.war_fit_sample | jsonify }};
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
            "x": { "field": "expected", "type": "quantitative", "title": "Expected share (this model)", "axis": { "format": "%" }, "scale": { "domain": [0, 1] } },
            "y": { "field": "actual", "type": "quantitative", "title": "Actual share", "axis": { "format": "%" }, "scale": { "domain": [0, 1] } },
            "color": {
              "field": "party", "type": "nominal", "title": "Party",
              "scale": { "domain": ["Democratic", "Republican"], "range": [colorDem, colorRep] }
            },
            "tooltip": [
              { "field": "year", "title": "Year" },
              { "field": "party", "title": "Party" },
              { "field": "actual", "type": "quantitative", "format": ".1%", "title": "Actual" },
              { "field": "expected", "type": "quantitative", "format": ".1%", "title": "Expected" }
            ]
          }
        }
      ],
      "resolve": { "scale": { "x": "shared", "y": "shared" } },
      "config": methodologyAxisConfig
    };
    vegaEmbed("#war-fit-scatter", spec, { actions: false }).catch(console.error);
  })();

  // --- Residual histogram, Democratic vs. Republican ----------------------
  (function () {
    const residuals = {{ site.data.war_fit_sample | jsonify }}.map((r) => ({
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
          "mark": { "type": "rule", "strokeDash": [6, 3], "strokeWidth": 1.5 },
          "encoding": { "x": { "field": "x", "type": "quantitative" }, "color": { "value": methodologyCssVar("--text-secondary") } }
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
    vegaEmbed("#war-residual-histogram", spec, { actions: false }).catch(console.error);
  })();
  {% endif %}
</script>
