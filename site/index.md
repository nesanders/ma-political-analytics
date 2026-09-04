---
layout: default
title: MA Political Analytics
---

# MA Political Analytics

Candidates, districts, and party lean for Massachusetts state legislative,
U.S. House, and U.S. Senate races, back through three redistricting
cycles.

<div class="stat-row">
  <div class="stat-tile"><div class="stat-value">{{ site.seats | size }}</div><div class="stat-label">Current seats tracked (State House, State Senate &amp; U.S. House)</div></div>
  <div class="stat-tile"><div class="stat-value">{{ site.candidates | size }}</div><div class="stat-label">Candidates tracked</div></div>
  <div class="stat-tile"><div class="stat-value">{{ site.towns | size }}</div><div class="stat-label">Massachusetts towns</div></div>
  <div class="stat-tile"><div class="stat-value">3</div><div class="stat-label">Redistricting vintages, back to 2001</div></div>
</div>

<ul class="quicklink-grid">
  <li><a class="quicklink" href="{{ '/chamber/house/' | relative_url }}">State House<span class="quicklink-desc">160 districts</span></a></li>
  <li><a class="quicklink" href="{{ '/chamber/senate/' | relative_url }}">State Senate<span class="quicklink-desc">40 districts</span></a></li>
  <li><a class="quicklink" href="{{ '/chamber/us-house/' | relative_url }}">U.S. House<span class="quicklink-desc">9 MA districts</span></a></li>
  <li><a class="quicklink" href="{{ '/us-senate/' | relative_url }}">U.S. Senate<span class="quicklink-desc">Statewide results &amp; history</span></a></li>
  <li><a class="quicklink" href="{{ '/map/' | relative_url }}">Statewide map<span class="quicklink-desc">Every district, colored by lean or any inferred variable</span></a></li>
  <li><a class="quicklink" href="{{ '/search/' | relative_url }}">Search &amp; compare<span class="quicklink-desc">Look up or compare seats</span></a></li>
  <li><a class="quicklink" href="{{ '/methodology/' | relative_url }}">Methodology<span class="quicklink-desc">How lean and WAR are computed</span></a></li>
</ul>

This site is under active development — see the
[methodology page]({{ '/methodology/' | relative_url }}) for how lean and
WAR are computed, or the [source](https://github.com/nesanders/ma-political-analytics)
for the full data pipeline.
