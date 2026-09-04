---
layout: default
title: Statewide Map
description: Every MA legislative and congressional district at once, colored by partisan lean or any inferred variable.
permalink: /map/
---

<link rel="stylesheet" href="{{ '/assets/css/vendor/maplibre-gl-4.7.1.css' | relative_url }}">
<script src="{{ '/assets/js/vendor/maplibre-gl-4.7.1.min.js' | relative_url }}"></script>
<script src="{{ '/assets/js/statewide-map.js' | relative_url }}"></script>

# Statewide Map

Every district at once. Use **Redistricting vintage** below each map to
switch boundaries, **Election year** (its own options depend on which
vintage is selected, since each vintage covers a different span of
general elections) to pick which specific race each district is shown
for, and **Color districts by** to recolor from the default partisan lean
to any district-level inferred variable this site computes for that
race — turnout, the winner's own over/underperformance (WAR), or how much
district lean, statewide tide, incumbency, demographics, or campaign
fundraising each contributed to that winner's *expected* vote share (the
model's prediction — WAR itself is the leftover, unexplained by any of
these, not a sum of them; see the
[methodology page]({{ '/methodology/' | relative_url }}) for how each is
computed). Click a district to open its page.

## State House

<div
  data-statewide-map
  data-chamber="house"
  data-geo-base="{{ '/assets/data/geo/' | relative_url }}"
  data-vintages="2001-2010,2012-2020,2022-present"
  data-default-vintage="2022-present"
  style="height: 500px;"
></div>

## State Senate

<div
  data-statewide-map
  data-chamber="senate"
  data-geo-base="{{ '/assets/data/geo/' | relative_url }}"
  data-vintages="2001-2010,2012-2020,2022-present"
  data-default-vintage="2022-present"
  style="height: 500px;"
></div>

## U.S. House

<div
  data-statewide-map
  data-chamber="us-house"
  data-geo-base="{{ '/assets/data/geo/' | relative_url }}"
  data-vintages="2001-2010,2012-2020,2022-present"
  data-default-vintage="2022-present"
  style="height: 500px;"
></div>
