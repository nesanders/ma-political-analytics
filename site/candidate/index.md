---
layout: default
title: All Candidates
description: Every candidate who has run for MA House or Senate in the years this site covers.
---

# All Candidates

{% assign candidates = site.candidates | sort: "name" %}
<table>
  <thead>
    <tr><th>Candidate</th><th>Party</th><th>Races</th><th>Most recent</th></tr>
  </thead>
  <tbody>
    {% for c in candidates %}
    {% assign latest = c.races | first %}
    <tr>
      <td><a href="{{ c.url | relative_url }}">{{ c.name }}</a></td>
      <td>{{ c.party }}</td>
      <td>{{ c.races.size }}</td>
      <td>{{ latest.year }} {{ latest.chamber | capitalize }}, {{ latest.district_name }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
