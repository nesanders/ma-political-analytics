---
layout: default
title: U.S. Senate
description: MA's U.S. Senate election results and candidate history, 2002-2024.
permalink: /us-senate/
---

# U.S. Senate

Massachusetts elects two U.S. Senators, but — unlike the U.S. House or the
state House/Senate — only one seat at a time, on a staggered six-year term,
so this office doesn't come up for election every cycle. There's also no
second Massachusetts to compare a Senate result against, so this page
doesn't compute a "wins above replacement" figure or a partisan-lean
baseline the way this site's other chamber pages do — just the raw
results and candidate history over time. See the
<a href="{{ '/methodology/' | relative_url }}">methodology page</a> for
more on why, and for this page's other documented gaps (no campaign-finance
section — OCPF, this site's only campaign-finance source, doesn't cover
federal candidates).

## General elections

<table>
  <thead>
    <tr><th>Year</th><th>Candidates</th><th>Winner</th></tr>
  </thead>
  <tbody>
    {% for race in site.data.us_senate.generals %}
    <tr>
      <td>{{ race.year }}{% if race.is_special %} (special){% endif %}</td>
      <td>
        {% for c in race.candidates %}
        {{ c.name }}{% if c.party %} ({{ c.party | slice: 0, 1 }}){% endif %}: {{ c.vote_share | times: 100 | round: 1 }}%{% unless forloop.last %}, {% endunless %}
        {% endfor %}
      </td>
      <td>
        {% assign winner = race.candidates | where: "winner", true | first %}
        {% if winner %}{{ winner.name }} ({{ winner.party }}){% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

## Primaries

<table>
  <thead>
    <tr><th>Year</th><th>Party</th><th>Candidates</th><th>Winner</th></tr>
  </thead>
  <tbody>
    {% for race in site.data.us_senate.primaries %}
    <tr>
      <td>{{ race.year }}{% if race.is_special %} (special){% endif %}</td>
      <td>{{ race.party }}</td>
      <td>
        {% for c in race.candidates %}
        {{ c.name }}: {{ c.primary_vote_share | times: 100 | round: 1 }}%{% unless forloop.last %}, {% endunless %}
        {% endfor %}
      </td>
      <td>
        {% assign winner = race.candidates | where: "winner", true | first %}
        {% if winner %}{{ winner.name }}{% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
