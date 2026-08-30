---
layout: default
title: Parties
description: Every party currently holding at least one MA House or Senate seat.
---

# Parties

{% assign parties = site.parties | sort: "seat_count" | reverse %}
<ul class="directory-grid">
  {% for p in parties %}
  <li class="directory-card party-{{ p.name | slugify }}">
    <h3><a href="{{ p.url | relative_url }}">{{ p.name }}</a></h3>
    <dl>
      <dt>House seats</dt><dd>{{ p.seat_count_by_chamber.house | default: 0 }}</dd>
      <dt>Senate seats</dt><dd>{{ p.seat_count_by_chamber.senate | default: 0 }}</dd>
      <dt>Total</dt><dd>{{ p.seat_count }}</dd>
    </dl>
  </li>
  {% endfor %}
</ul>
