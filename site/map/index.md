---
layout: default
title: Statewide Map
description: Every MA House and Senate district at once, colored by partisan lean.
permalink: /map/
---

<link rel="stylesheet" href="{{ '/assets/css/vendor/maplibre-gl-4.7.1.css' | relative_url }}">
<script src="{{ '/assets/js/vendor/maplibre-gl-4.7.1.min.js' | relative_url }}"></script>
<script src="{{ '/assets/js/statewide-map.js' | relative_url }}"></script>

# Statewide Map

Every district, current (2022-present) boundaries. Color shows which party
the district's lean favors; darker means safer for that party, lighter
means more competitive. Click a district to open its page.

## House

<div
  data-statewide-map
  data-geojson-url="{{ '/assets/data/geo/house-2022-present-all.geojson' | relative_url }}"
  style="height: 500px;"
></div>

## Senate

<div
  data-statewide-map
  data-geojson-url="{{ '/assets/data/geo/senate-2022-present-all.geojson' | relative_url }}"
  style="height: 500px;"
></div>
