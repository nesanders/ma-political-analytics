// Renders the statewide "all districts at once" overview map — site/map/,
// one map per chamber, colored by a viewer-selectable district-level
// variable (party lean by default, or the winner's own WAR, any of the
// regression components feeding that winner's *expected* vote share, or
// turnout — see METRICS below) and clickable through to that district's
// own page. Also offers a vintage selector (2001-2010/2012-2020/
// 2022-present), reloading that chamber's combined GeoJSON for the chosen
// vintage. See district-map.js for the single-district map used on seat/
// district pages; this is deliberately a separate, simpler script rather
// than a shared one, since it renders a whole FeatureCollection with
// data-driven styling instead of one polygon in a fixed color.
// Basemap: OpenStreetMap's standard raster tiles — see district-map.js's
// top-of-file comment for why (CARTO's basemaps.cartocdn.com, used here
// originally, turned out to require an API key in production despite this
// project's own documentation to the contrary — found live, from a real
// deployed screenshot showing "API KEY REQUIRED" tiles). No dark-mode
// variant here, unlike CARTO's, so this map no longer adapts to the page
// theme.
(function () {
  // Each feature's `url` property is a site-root-relative path computed in
  // Python at pipeline build time (ma_politics.build.generate_site_data's
  // district_url()) with no knowledge of Jekyll's site.baseurl — needs the
  // same baseurl prefix every relative_url-filtered link in the page
  // already carries. Found live: a real click-through test navigated to
  // `/district/...` instead of `/ma-political-analytics/district/...` and
  // landed on a 404 before this was added.
  function withBaseUrl(path) {
    var baseurl = document.body ? document.body.dataset.siteBaseurl || "" : "";
    return baseurl + path;
  }

  function pct(x) {
    return x === null || x === undefined ? "—" : Math.round(x * 1000) / 10 + "%";
  }

  function pctSigned(x) {
    if (x === null || x === undefined) return "—";
    var v = Math.round(x * 1000) / 10;
    return (v > 0 ? "+" : "") + v + " pts";
  }

  function ratio(x) {
    return x === null || x === undefined ? "—" : Math.round(x * 100) + "% of baseline";
  }

  // Each metric's `kind` decides how it's colored:
  //   "lean"      — the existing default: fill by party_favored (categorical),
  //                  opacity by competitiveness. Not a plain magnitude, so it
  //                  keeps its own bespoke styling rather than the diverging
  //                  ramp below.
  //   "diverging" — a numeric field centered at `center` (0 for WAR itself
  //                  or for one of the components feeding *expected* vote
  //                  share, 1.0 for turnout ratio — "no effect"/"exactly
  //                  baseline"), colored on a two-hue-plus-neutral-midpoint
  //                  ramp (--map-diverging-neg/-pos, --gridline) scaled to
  //                  this specific vintage's own actual data range — see
  //                  main.css's own comment on those tokens for the palette
  //                  choice (validated via the dataviz skill, deliberately
  //                  not dem/rep blue-red, which would misread a non-
  //                  partisan magnitude like "fundraising's contribution" as
  //                  a partisan signal). Note these components are NOT
  //                  "contributions to WAR" — they sum to expected_share_
  //                  resolved (the model's prediction), and WAR is defined
  //                  as actual_two_party_share minus that whole sum, i.e.
  //                  the part these components leave unexplained, not a
  //                  quantity they add up to. See generate_site_data.py's
  //                  apply_war for the exact arithmetic.
  // A metric only appears in a given map's own selector if at least one
  // loaded feature actually has a non-null value for it — e.g. U.S. House
  // has no fundraising_component (no FEC data fetched) and no demographics
  // outside the current vintage, so those options simply don't show up for
  // that chamber/vintage rather than appearing and doing nothing.
  var METRICS = [
    { key: "lean_dem_share", label: "Partisan lean", kind: "lean" },
    {
      key: "winner_war",
      label: "Most recent winner's over/underperformance (WAR)",
      kind: "diverging",
      center: 0,
      format: pctSigned,
    },
    {
      key: "winner_lean_component",
      label: "District lean's contribution to expected vote share",
      kind: "diverging",
      center: 0,
      format: pctSigned,
    },
    {
      key: "winner_tide_component",
      label: "Statewide tide's contribution to expected vote share",
      kind: "diverging",
      center: 0,
      format: pctSigned,
    },
    {
      key: "winner_incumbency_adjustment",
      label: "Incumbency's contribution to expected vote share",
      kind: "diverging",
      center: 0,
      format: pctSigned,
    },
    {
      key: "winner_demographics_component",
      label: "District demographics' contribution to expected vote share",
      kind: "diverging",
      center: 0,
      format: pctSigned,
    },
    {
      key: "winner_fundraising_component",
      label: "Campaign fundraising's contribution to expected vote share",
      kind: "diverging",
      center: 0,
      format: pctSigned,
    },
    {
      key: "turnout_ratio",
      label: "Turnout vs. baseline race",
      kind: "diverging",
      center: 1,
      format: ratio,
    },
  ];
  var METRICS_BY_KEY = {};
  METRICS.forEach(function (m) {
    METRICS_BY_KEY[m.key] = m;
  });

  function availableMetrics(collection) {
    return METRICS.filter(function (m) {
      if (m.kind === "lean") return true;
      return collection.features.some(function (f) {
        var v = f.properties[m.key];
        return v !== null && v !== undefined;
      });
    });
  }

  function collectBounds(collection) {
    var lons = [];
    var lats = [];
    collection.features.forEach(function (f) {
      (function walk(coords) {
        if (typeof coords[0] === "number") {
          lons.push(coords[0]);
          lats.push(coords[1]);
        } else {
          coords.forEach(walk);
        }
      })(f.geometry.coordinates);
    });
    if (!lons.length) return null;
    return [
      [Math.min.apply(null, lons), Math.min.apply(null, lats)],
      [Math.max.apply(null, lons), Math.max.apply(null, lats)],
    ];
  }

  function init(container) {
    var geoBase = container.dataset.geoBase;
    var chamber = container.dataset.chamber;
    var vintages = (container.dataset.vintages || "").split(",").filter(Boolean);
    var defaultVintage = container.dataset.defaultVintage || vintages[vintages.length - 1];
    if (!geoBase || !chamber || typeof maplibregl === "undefined") return;

    var style = getComputedStyle(document.documentElement);
    var colorDem = style.getPropertyValue("--series-dem").trim();
    var colorRep = style.getPropertyValue("--series-rep").trim();
    var colorNeutral = style.getPropertyValue("--series-neutral").trim();
    var colorDivNeg = style.getPropertyValue("--map-diverging-neg").trim();
    var colorDivPos = style.getPropertyValue("--map-diverging-pos").trim();
    var colorGridline = style.getPropertyValue("--gridline").trim();

    // Toolbar (vintage + metric selectors) and legend, inserted as
    // siblings around the map container rather than children of it — the
    // container is what MapLibre attaches its own canvas to, so anything
    // pre-existing inside it would just sit awkwardly under/behind that.
    var toolbar = document.createElement("div");
    toolbar.className = "statewide-map-toolbar";

    var vintageField = document.createElement("div");
    vintageField.className = "statewide-map-field";
    var vintageLabelId = "map-vintage-" + Math.random().toString(36).slice(2);
    vintageField.innerHTML = '<label id="' + vintageLabelId + '">Redistricting vintage</label>';
    var vintageSelect = document.createElement("select");
    vintageSelect.setAttribute("aria-labelledby", vintageLabelId);
    vintages.forEach(function (v) {
      var opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      if (v === defaultVintage) opt.selected = true;
      vintageSelect.appendChild(opt);
    });
    vintageField.appendChild(vintageSelect);
    if (vintages.length > 1) toolbar.appendChild(vintageField);

    var metricField = document.createElement("div");
    metricField.className = "statewide-map-field";
    var metricLabelId = "map-metric-" + Math.random().toString(36).slice(2);
    metricField.innerHTML = '<label id="' + metricLabelId + '">Color districts by</label>';
    var metricSelect = document.createElement("select");
    metricSelect.setAttribute("aria-labelledby", metricLabelId);
    metricField.appendChild(metricSelect);
    toolbar.appendChild(metricField);

    var legend = document.createElement("div");
    legend.className = "statewide-map-legend";

    container.parentNode.insertBefore(toolbar, container);
    container.parentNode.insertBefore(legend, container.nextSibling);

    var map = new maplibregl.Map({
      container: container,
      style: {
        version: 8,
        sources: {
          basemap: {
            type: "raster",
            tiles: [
              "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
              "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
              "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
            ],
            tileSize: 256,
            attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [{ id: "basemap", type: "raster", source: "basemap" }],
      },
      cooperativeGestures: true,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    var popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
    var layersAdded = false;
    var currentCollection = null;
    var currentMetricKey = "lean_dem_share";

    function diverging(min, center, max) {
      // Symmetric around `center` so the neutral midpoint always lands
      // exactly at 0 on the color scale, whatever this vintage's own
      // data range happens to be — an asymmetric range (e.g. more
      // underperformers than overperformers loaded) would otherwise pull
      // the "no effect" color off-center, misrepresenting which side of
      // center a mid-range value is actually on.
      var span = Math.max(center - min, max - center) || 1e-9;
      return [
        "interpolate",
        ["linear"],
        ["get", currentMetricKey],
        center - span,
        colorDivNeg,
        center,
        colorGridline,
        center + span,
        colorDivPos,
      ];
    }

    function applyMetric(metricKey) {
      currentMetricKey = metricKey;
      var metric = METRICS_BY_KEY[metricKey];
      if (!map.getLayer("districts-fill")) return;

      if (metric.kind === "lean") {
        map.setPaintProperty("districts-fill", "fill-color", [
          "match",
          ["get", "party_favored"],
          "Democratic",
          colorDem,
          "Republican",
          colorRep,
          colorNeutral,
        ]);
        map.setPaintProperty("districts-fill", "fill-opacity", [
          "match",
          ["get", "competitiveness"],
          "Safe",
          0.85,
          "Likely",
          0.65,
          "Lean",
          0.45,
          "Tossup",
          0.25,
          0.5,
        ]);
        legend.innerHTML =
          "<strong>Partisan lean.</strong> Color shows which party the district's lean favors; darker means safer for that party, lighter means more competitive.";
        return;
      }

      var values = currentCollection.features
        .map(function (f) {
          return f.properties[metricKey];
        })
        .filter(function (v) {
          return v !== null && v !== undefined;
        });
      var min = values.length ? Math.min.apply(null, values) : metric.center;
      var max = values.length ? Math.max.apply(null, values) : metric.center;

      map.setPaintProperty("districts-fill", "fill-color", [
        "case",
        ["==", ["get", metricKey], null],
        colorNeutral,
        diverging(min, metric.center, max),
      ]);
      map.setPaintProperty("districts-fill", "fill-opacity", [
        "case",
        ["==", ["get", metricKey], null],
        0.2,
        0.8,
      ]);

      var gradient = document.createElement("div");
      gradient.className = "statewide-map-legend-gradient";
      gradient.style.background = "linear-gradient(to right, " + colorDivNeg + ", " + colorGridline + ", " + colorDivPos + ")";
      var labels = document.createElement("div");
      labels.className = "statewide-map-legend-labels";
      var span = Math.max(metric.center - min, max - metric.center) || 1e-9;
      labels.innerHTML =
        "<span>" +
        metric.format(metric.center - span) +
        "</span><span>" +
        metric.format(metric.center) +
        "</span><span>" +
        metric.format(metric.center + span) +
        "</span>";
      var note = document.createElement("div");
      note.className = "statewide-map-legend-note";
      note.textContent =
        "From each district's most recent election year, for that race's winner. Gray: no data for this district.";
      legend.innerHTML = "<strong>" + metric.label + ".</strong>";
      legend.appendChild(gradient);
      legend.appendChild(labels);
      legend.appendChild(note);
    }

    function popupHtml(p) {
      var metric = METRICS_BY_KEY[currentMetricKey];
      var lines = ["<strong>" + p.district_name + "</strong>"];
      if (metric.kind === "lean") {
        var leanPct = pct(p.lean_dem_share);
        lines.push(p.competitiveness_label + " (" + leanPct + " D)");
      } else {
        lines.push(metric.label + ": " + metric.format(p[currentMetricKey]));
        lines.push(p.winner_name ? "Winner: " + p.winner_name + " (" + (p.winner_party || "—") + ")" : "");
      }
      return lines.filter(Boolean).join("<br>");
    }

    function addLayers() {
      map.addSource("districts", { type: "geojson", data: currentCollection });
      map.addLayer({
        id: "districts-fill",
        type: "fill",
        source: "districts",
        paint: { "fill-color": colorNeutral, "fill-opacity": 0.5 },
      });
      map.addLayer({
        id: "districts-outline",
        type: "line",
        source: "districts",
        paint: { "line-color": colorNeutral, "line-width": 0.5 },
      });

      map.on("mousemove", "districts-fill", function (e) {
        map.getCanvas().style.cursor = "pointer";
        popup.setLngLat(e.lngLat).setHTML(popupHtml(e.features[0].properties)).addTo(map);
      });
      map.on("mouseleave", "districts-fill", function () {
        map.getCanvas().style.cursor = "";
        popup.remove();
      });
      map.on("click", "districts-fill", function (e) {
        var url = e.features[0].properties.url;
        if (url) window.location.href = withBaseUrl(url);
      });

      layersAdded = true;
    }

    function refreshMetricOptions() {
      var previous = currentMetricKey;
      var available = availableMetrics(currentCollection);
      metricSelect.innerHTML = "";
      available.forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m.key;
        opt.textContent = m.label;
        metricSelect.appendChild(opt);
      });
      var stillAvailable = available.some(function (m) {
        return m.key === previous;
      });
      metricSelect.value = stillAvailable ? previous : "lean_dem_share";
      applyMetric(metricSelect.value);
    }

    function loadVintage(vintage) {
      fetch(geoBase + chamber + "-" + vintage + "-all.geojson")
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (collection) {
          currentCollection = collection;
          if (!layersAdded) {
            var tryAddLayers = (function () {
              var added = false;
              return function () {
                if (added) return;
                added = true;
                addLayers();
                refreshMetricOptions();
              };
            })();
            // Gated on the *style* being ready (sources/layers parsed),
            // not the full "load" event (first visually-complete render,
            // which waits on the basemap's own raster tiles finishing).
            // Found live, real bug: this page renders several maps at
            // once, all requesting tiles from the same three
            // openstreetmap.org subdomains — with maps competing for the
            // browser's limited per-host connection pool, a later map's
            // tile requests can stall indefinitely, and since "load"
            // never fires without them, the district layer (which
            // doesn't itself depend on the basemap) never got added at
            // all. style.load has no such dependency. The timeout is
            // defense-in-depth in case that assumption doesn't hold on
            // some browser/version.
            if (map.isStyleLoaded()) tryAddLayers();
            else map.once("style.load", tryAddLayers);
            setTimeout(tryAddLayers, 3000);
          } else {
            map.getSource("districts").setData(collection);
            refreshMetricOptions();
          }
          var bounds = collectBounds(collection);
          if (bounds) map.fitBounds(bounds, { padding: 16, animate: false });
        })
        .catch(function (e) {
          console.error("Statewide map: failed to load geometry", e);
          container.innerHTML = "<p><em>Map unavailable.</em></p>";
        });
    }

    vintageSelect.addEventListener("change", function () {
      loadVintage(vintageSelect.value);
    });
    metricSelect.addEventListener("change", function () {
      applyMetric(metricSelect.value);
    });

    loadVintage(defaultVintage);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-statewide-map]").forEach(init);
  });
})();
