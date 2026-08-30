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
  weighting, not theirs); that hasn't been built yet, so treat current WAR
  values as baseline-only, not the fuller model.
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
