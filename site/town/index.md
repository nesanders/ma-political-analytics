---
layout: default
title: All Towns
description: Every Massachusetts municipality and the House/Senate districts it overlaps.
---

# All Towns

{% assign towns = site.towns | sort: "name" %}
<table>
  <thead>
    <tr><th>Town</th><th>Districts</th></tr>
  </thead>
  <tbody>
    {% for t in towns %}
    <tr>
      <td><a href="{{ t.url | relative_url }}">{{ t.name }}</a></td>
      <td>{{ t.districts.size }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
