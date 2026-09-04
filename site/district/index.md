---
layout: default
title: All Districts
description: Every MA House, Senate, and U.S. House district across three redistricting vintages (2001-2010, 2012-2020, 2022-present).
---

# All Districts

Every House, Senate, and U.S. House district, across all three
redistricting vintages this site covers. For "who represents this area
today," start from a [seat](/seat/) instead — a district page is scoped to
one vintage's boundaries, which can differ from what came before or after
redistricting. (MA's U.S. Senate seat has no districts — see the
[U.S. Senate page](/us-senate/) instead.)

{% assign chambers = "house,senate,us-house" | split: "," %}
{% assign vintages = "2022-present,2012-2020,2001-2010" | split: "," %}
{% for chamber in chambers %}
## {{ site.data.chamber_labels[chamber] | default: chamber }}

{% for vintage in vintages %}
{% assign districts = site.districts | where: "chamber", chamber | where: "vintage", vintage | sort: "district_name" %}
{% if districts.size > 0 %}
### {{ vintage }}

<table>
  <thead>
    <tr><th>District</th><th>Years</th><th>Most recent lean</th></tr>
  </thead>
  <tbody>
    {% for d in districts %}
    <tr>
      <td><a href="{{ d.url | relative_url }}">{{ d.district_name }}</a></td>
      <td>{{ d.years | join: ", " }}</td>
      <td>{{ d.competitiveness_label }} ({{ d.lean_dem_share | times: 100 | round: 1 }}% D)</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}
{% endfor %}
{% endfor %}
