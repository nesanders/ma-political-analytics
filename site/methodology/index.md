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
site currently treats those the same. See the
[design plan](https://github.com/nesanders/ma-political-analytics/blob/HEAD/docs/PLAN.md)
for the full pipeline.

## WAR (wins above replacement)

**WAR = actual two-party vote share − expected share from district lean.**

Positive WAR means a candidate did better than the district's partisan
lean alone would predict; negative means they underperformed it. It's
reported per-race, and only defined for Democratic and Republican
candidates — a minor-party candidate has no meaningful "expected share"
against a two-party baseline.

WAR here is **adapted from, not identical to,** the WAR metric published
by the election-analytics outlet
[Split Ticket](https://split-ticket.org/) for federal races (since
~2022), which is itself the applied descendant of a real academic
literature on decomposing vote share into a normal-vote (partisan
baseline) component and a residual attributable to the candidate:

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

**This adaptation differs from Split Ticket's own method in ways worth
being explicit about, not hidden:**

- *Different population*: Massachusetts state legislative races (House
  and Senate), not federal — smaller electorates, a higher share of
  uncontested races, and much thinner public polling/finance data per
  race than a Congressional or Senate race has.
- *Different baseline, for now*: what's actually computed on this site
  today is district partisan lean alone — the "v1" baseline described
  above. The original design also called for adding incumbency and OCPF
  campaign-finance data as further fundamentals (a "v2" baseline, same
  spirit as Split Ticket's approach but this project's own regression and
  weighting, not theirs). Incumbency is now tracked and shown throughout
  the site (see below), but not yet folded into WAR's *expected*-share
  calculation itself — treat current WAR values as baseline-only, not the
  fuller model.
- *Different redistricting handling*: this site's lean baseline has to
  cross three Massachusetts redistricting vintages (2001-2010, 2012-2020,
  2022-present); Split Ticket's federal-district baseline doesn't face
  that at the same scale.

**A known limitation, not yet fixed**: an uncontested major-party
candidate mechanically gets an actual two-party share of 100% (there's no
opponent to divide the vote against), which inflates their WAR regardless
of how strong a candidate they actually are. Holding a seat the
environment says should be competitive, uncontested, is itself a real
signal — but it isn't comparable on the same scale to a contested race's
WAR the way this site currently computes it. Split Ticket's own WAR
reportedly handles uncontested races with distinct logic; this project's
doesn't yet. Treat uncontested-race WAR as directionally meaningful, not
precisely comparable to contested races, until this is addressed.

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
section rather than showing someone else's numbers. Around three in four
candidates matched this way when last checked — the rest either have no
OCPF filing on record (common for candidates under OCPF's low-fundraising
exemption threshold) or use a last name this matching doesn't correctly
extract (multi-word surnames in particular — see the module docstring in
`build.campaign_finance_match` for the exact rule).

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
