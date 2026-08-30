---
layout: default
title: Parties
description: Every party currently holding at least one MA House or Senate seat.
---

# Parties

{% assign parties = site.parties | sort: "seat_count" | reverse %}
<table>
  <thead>
    <tr><th>Party</th><th>House seats</th><th>Senate seats</th><th>Total</th></tr>
  </thead>
  <tbody>
    {% for p in parties %}
    <tr>
      <td><a href="{{ p.url | relative_url }}">{{ p.name }}</a></td>
      <td>{{ p.seat_count_by_chamber.house | default: 0 }}</td>
      <td>{{ p.seat_count_by_chamber.senate | default: 0 }}</td>
      <td>{{ p.seat_count }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
