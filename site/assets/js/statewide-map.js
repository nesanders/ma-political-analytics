// Renders the statewide "all districts at once" overview map — site/map/,
// one map per chamber, every district colored by which party its lean
// favors (opacity scaled by competitiveness) and clickable through to
// that district's own page. See district-map.js for the single-district
// map used on seat/district pages; this is deliberately a separate,
// simpler script rather than a shared one, since it renders a whole
// FeatureCollection with data-driven styling instead of one polygon in a
// fixed color.
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

  function init(container) {
    var geojsonUrl = container.dataset.geojsonUrl;
    if (!geojsonUrl || typeof maplibregl === "undefined") return;

    var style = getComputedStyle(document.documentElement);
    var colorDem = style.getPropertyValue("--series-dem").trim();
    var colorRep = style.getPropertyValue("--series-rep").trim();
    var colorNeutral = style.getPropertyValue("--series-neutral").trim();

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

    fetch(geojsonUrl)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (collection) {
        function addLayers() {
          map.addSource("districts", { type: "geojson", data: collection });
          map.addLayer({
            id: "districts-fill",
            type: "fill",
            source: "districts",
            paint: {
              "fill-color": ["match", ["get", "party_favored"], "Democratic", colorDem, "Republican", colorRep, colorNeutral],
              "fill-opacity": [
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
              ],
            },
          });
          map.addLayer({
            id: "districts-outline",
            type: "line",
            source: "districts",
            paint: { "line-color": colorNeutral, "line-width": 0.5 },
          });

          // Fit to the whole collection's bounds.
          var lons = [];
          var lats = [];
          collection.features.forEach(function (f) {
            (function collect(coords) {
              if (typeof coords[0] === "number") {
                lons.push(coords[0]);
                lats.push(coords[1]);
              } else {
                coords.forEach(collect);
              }
            })(f.geometry.coordinates);
          });
          if (lons.length) {
            map.fitBounds(
              [
                [Math.min.apply(null, lons), Math.min.apply(null, lats)],
                [Math.max.apply(null, lons), Math.max.apply(null, lats)],
              ],
              { padding: 16, animate: false }
            );
          }

          map.on("mousemove", "districts-fill", function (e) {
            map.getCanvas().style.cursor = "pointer";
            var p = e.features[0].properties;
            var leanPct = Math.round(p.lean_dem_share * 1000) / 10;
            popup
              .setLngLat(e.lngLat)
              .setHTML(
                "<strong>" + p.district_name + "</strong><br>" + p.competitiveness_label + " (" + leanPct + "% D)"
              )
              .addTo(map);
          });
          map.on("mouseleave", "districts-fill", function () {
            map.getCanvas().style.cursor = "";
            popup.remove();
          });
          map.on("click", "districts-fill", function (e) {
            var url = e.features[0].properties.url;
            if (url) window.location.href = withBaseUrl(url);
          });
        }
        // Gated on the *style* being ready (sources/layers parsed), not
        // the full "load" event (first visually-complete render, which
        // waits on the basemap's own raster tiles finishing). Found
        // live, real bug: this page renders two maps at once, both
        // requesting tiles from the same three openstreetmap.org
        // subdomains — with both maps competing for the browser's
        // limited per-host connection pool, the second map's tile
        // requests can stall indefinitely, and since "load" never fires
        // without them, the district layer (which doesn't itself depend
        // on the basemap) never got added at all: no zoom, no districts,
        // nothing on screen. style.load has no such dependency. The
        // timeout is defense-in-depth in case that assumption doesn't
        // hold on some browser/version — either way, the district layer
        // (the actual content) no longer depends on three tile servers
        // answering fast enough across two competing map instances.
        var addedLayers = false;
        function tryAddLayers() {
          if (addedLayers) return;
          addedLayers = true;
          addLayers();
        }
        if (map.isStyleLoaded()) tryAddLayers();
        else map.once("style.load", tryAddLayers);
        setTimeout(tryAddLayers, 3000);
      })
      .catch(function (e) {
        console.error("Statewide map: failed to load geometry", e);
        container.innerHTML = "<p><em>Map unavailable.</em></p>";
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-statewide-map]").forEach(init);
  });
})();
