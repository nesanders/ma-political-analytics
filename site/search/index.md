---
layout: default
title: Search & Compare
description: Search every seat, candidate, town, and party on this site, and compare two seats side by side.
---

# Search & Compare

<div id="search-app">
  <input type="search" id="search-input" placeholder="Search seats, candidates, towns, parties&hellip;" autocomplete="off">
  <p id="search-hint"><small>Type at least 2 characters. Add up to two seats to compare them side by side.</small></p>
  <ul id="search-results"></ul>
  <div id="compare-panel"></div>
</div>

<script type="application/json" id="search-index-seats">
[
{% for s in site.seats %}
  {
    "type": "seat",
    "name": {{ s.district_name | jsonify }},
    "chamber": {{ s.chamber | jsonify }},
    "url": {{ s.url | jsonify }},
    "lean_dem_share": {{ s.lean_dem_share | jsonify }},
    "competitiveness_label": {{ s.competitiveness_label | jsonify }},
    "party_favored": {{ s.party_favored | jsonify }},
    "turnout_ratio": {{ s.results_by_year.first.turnout_ratio | jsonify }},
    "is_open_seat": {{ s.results_by_year.first.is_open_seat | jsonify }},
    "demographics": {{ s.demographics | jsonify }}
  }{% unless forloop.last %},{% endunless %}
{% endfor %}
]
</script>

<script type="application/json" id="search-index-candidates">
[
{% for c in site.candidates %}
{% assign latest_race = c.races | first %}
  {
    "type": "candidate",
    "name": {{ c.name | jsonify }},
    "party": {{ c.party | jsonify }},
    "url": {{ c.url | jsonify }},
    "detail": {{ latest_race.year | append: " " | append: latest_race.chamber | append: ", " | append: latest_race.district_name | jsonify }}
  }{% unless forloop.last %},{% endunless %}
{% endfor %}
]
</script>

<script type="application/json" id="search-index-towns">
[
{% for t in site.towns %}
  {
    "type": "town",
    "name": {{ t.name | jsonify }},
    "url": {{ t.url | jsonify }},
    "detail": {{ t.districts.size | append: " district" | jsonify }}
  }{% unless forloop.last %},{% endunless %}
{% endfor %}
]
</script>

<script type="application/json" id="search-index-parties">
[
{% for p in site.parties %}
  {
    "type": "party",
    "name": {{ p.name | jsonify }},
    "url": {{ p.url | jsonify }},
    "detail": {{ p.seat_count | append: " seats held" | jsonify }}
  }{% unless forloop.last %},{% endunless %}
{% endfor %}
]
</script>

<script src="{{ '/assets/js/search.js' | relative_url }}"></script>
