// Renders a district's boundary on a MapLibre map — used by district.html
// and seat.html (a seat's current-vintage record already carries the same
// geo_slug field a district record does, so this runs unmodified on both).
// See docs/PLAN.md §6 and pipeline/README.md for how the GeoJSON itself is
// published (ma_politics.build.publish_district_geo).
//
// Basemap: OpenStreetMap's standard raster tiles (tile.openstreetmap.org) —
// genuinely free and keyless, unlike CARTO's basemaps.cartocdn.com, which
// this project originally used on the understanding that it didn't require
// an API key. Found live, from a real deployed screenshot, that it does now
// (or does for this project's traffic/referrer): every tile came back as an
// "API KEY REQUIRED" placeholder image instead of a map. OSM's tile usage
// policy (operations.osmfoundation.org/policies/tiles) is explicitly scoped
// to light/moderate use, not heavy production traffic — acceptable for a
// small site like this one, but revisit (dedicated tile hosting, or a paid
// provider) if traffic ever grows enough to matter. No light/dark variant
// exists here the way CARTO's light_all/dark_all did, so the map no longer
// adapts to the page's theme — a real regression traded for one that
// actually shows a map. This session's own network policy still blocks
// tile.openstreetmap.org, so the basemap layer itself remains unverified
// live from here (real end-user browsers reach it directly, the same
// situation as AskAI's jsDelivr/extensions.duckdb.org dependencies — see
// duckdb.ts). What *is* verified: the district polygon itself renders
// correctly as a MapLibre GeoJSON source/layer against a blank style with
// no external tiles at all — the basemap failing to load (blocked host,
// offline, etc.) leaves the polygon still visible on a plain background
// rather than blanking the whole map, since it's added as its own layer
// independent of the basemap's own load success.
(function () {
  function collectCoords(coords, out) {
    if (typeof coords[0] === "number") {
      out.push(coords);
    } else {
      coords.forEach(function (c) {
        collectCoords(c, out);
      });
    }
  }

  function fitToFeature(map, feature) {
    var coords = [];
    collectCoords(feature.geometry.coordinates, coords);
    if (coords.length === 0) return;
    var lons = coords.map(function (c) { return c[0]; });
    var lats = coords.map(function (c) { return c[1]; });
    map.fitBounds(
      [
        [Math.min.apply(null, lons), Math.min.apply(null, lats)],
        [Math.max.apply(null, lons), Math.max.apply(null, lats)],
      ],
      { padding: 24, animate: false }
    );
  }

  function init(container) {
    var geojsonUrl = container.dataset.geojsonUrl;
    var partyFavored = container.dataset.partyFavored;
    if (!geojsonUrl || typeof maplibregl === "undefined") return;

    var style = getComputedStyle(document.documentElement);
    var fillColor =
      partyFavored === "Democratic"
        ? style.getPropertyValue("--series-dem").trim()
        : partyFavored === "Republican"
        ? style.getPropertyValue("--series-rep").trim()
        : style.getPropertyValue("--series-neutral").trim();

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

    fetch(geojsonUrl)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (feature) {
        function addDistrictLayer() {
          map.addSource("district", { type: "geojson", data: feature });
          map.addLayer({
            id: "district-fill",
            type: "fill",
            source: "district",
            paint: { "fill-color": fillColor, "fill-opacity": 0.35 },
          });
          map.addLayer({
            id: "district-outline",
            type: "line",
            source: "district",
            paint: { "line-color": fillColor, "line-width": 2 },
          });
          fitToFeature(map, feature);
        }
        if (map.loaded()) addDistrictLayer();
        else map.on("load", addDistrictLayer);
      })
      .catch(function (e) {
        console.error("District map: failed to load geometry", e);
        container.innerHTML = "<p><em>Map unavailable.</em></p>";
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-geojson-url]").forEach(init);
  });
})();
