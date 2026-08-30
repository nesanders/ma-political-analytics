(function () {
  function withBaseUrl(path) {
    var baseurl = document.body ? document.body.dataset.siteBaseurl || "" : "";
    return baseurl + path;
  }

  var indexPromise = null;
  function fetchIndex() {
    if (!indexPromise) {
      indexPromise = fetch(withBaseUrl("/search/index.json")).then(function (r) { return r.json(); });
    }
    return indexPromise;
  }

  function typeLabel(type) {
    return { seat: "Seat", candidate: "Candidate", town: "Town", party: "Party" }[type] || type;
  }

  function matches(entries, query) {
    var q = query.toLowerCase();
    return entries.filter(function (e) {
      return e.name.toLowerCase().indexOf(q) !== -1;
    });
  }

  function metaText(e) {
    var text = typeLabel(e.type);
    if (e.type === "seat") text += ", " + e.competitiveness_label;
    else if (e.detail) text += ", " + e.detail;
    else if (e.party) text += ", " + e.party;
    return text;
  }

  initHeaderSearch();
  initSearchPage();

  function initHeaderSearch() {
    var input = document.getElementById("header-search-input");
    var dropdown = document.getElementById("header-search-dropdown");
    if (!input || !dropdown) return;

    function render(query) {
      dropdown.innerHTML = "";
      if (query.length < 2) {
        dropdown.hidden = true;
        return;
      }
      fetchIndex().then(function (entries) {
        var results = matches(entries, query).slice(0, 8);
        dropdown.innerHTML = "";
        if (results.length === 0) {
          dropdown.hidden = true;
          return;
        }
        results.forEach(function (e) {
          var a = document.createElement("a");
          a.href = withBaseUrl(e.url);
          a.textContent = e.name;
          var meta = document.createElement("span");
          meta.textContent = " (" + metaText(e) + ")";
          a.appendChild(meta);
          dropdown.appendChild(a);
        });
        dropdown.hidden = false;
      });
    }

    input.addEventListener("input", function () { render(input.value); });
    input.addEventListener("focus", function () { if (input.value) render(input.value); });
    document.addEventListener("click", function (e) {
      if (e.target !== input && !dropdown.contains(e.target)) dropdown.hidden = true;
    });
  }

  function initSearchPage() {
    var input = document.getElementById("search-input");
    var resultsEl = document.getElementById("search-results");
    var comparePanel = document.getElementById("compare-panel");
    if (!input || !resultsEl) return;

    var compareSeats = [];

    function renderResults(query, entries) {
      resultsEl.innerHTML = "";
      if (query.length < 2) return;
      var results = matches(entries, query).slice(0, 25);

      results.forEach(function (e) {
        var li = document.createElement("li");

        var link = document.createElement("a");
        link.href = withBaseUrl(e.url);
        link.textContent = e.name;

        var meta = document.createElement("span");
        meta.className = "search-result-meta";
        meta.textContent = " (" + metaText(e) + ")";

        li.appendChild(link);
        li.appendChild(meta);

        if (e.type === "seat") {
          var alreadyAdded = compareSeats.some(function (s) { return s.url === e.url; });
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = alreadyAdded ? "Added" : "+ Compare";
          btn.disabled = alreadyAdded || compareSeats.length >= 2;
          btn.addEventListener("click", function () {
            compareSeats.push(e);
            renderCompare();
            fetchIndex().then(function (entries) { renderResults(input.value, entries); });
          });
          li.appendChild(document.createTextNode(" "));
          li.appendChild(btn);
        }

        resultsEl.appendChild(li);
      });

      if (results.length === 0) {
        var none = document.createElement("li");
        none.textContent = "No matches.";
        resultsEl.appendChild(none);
      }
    }

    function pct(x) {
      return x === null || x === undefined ? "—" : Math.round(x * 1000) / 10 + "%";
    }

    function dollars(x) {
      return x === null || x === undefined ? "—" : "$" + x.toLocaleString();
    }

    function count(x) {
      return x === null || x === undefined ? "—" : x.toLocaleString();
    }

    function renderCompare() {
      comparePanel.innerHTML = "";
      if (compareSeats.length === 0) return;

      var table = document.createElement("table");
      var rows = [
        ["Chamber", function (s) { return s.chamber; }],
        ["Partisan lean", function (s) { return s.competitiveness_label + " (" + pct(s.lean_dem_share) + " D)"; }],
        ["Turnout vs. baseline", function (s) { return pct(s.turnout_ratio); }],
        ["Open seat (most recent)", function (s) { return s.is_open_seat === true ? "Yes" : s.is_open_seat === false ? "No" : "Unknown"; }],
        ["Population", function (s) { return s.demographics ? count(s.demographics.total_population) : "—"; }],
        ["Median household income", function (s) { return s.demographics ? dollars(s.demographics.median_household_income) : "—"; }],
      ];

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      headRow.appendChild(document.createElement("th"));
      compareSeats.forEach(function (s, i) {
        var th = document.createElement("th");
        var link = document.createElement("a");
        link.href = withBaseUrl(s.url);
        link.textContent = s.name;
        th.appendChild(link);
        var remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "✕";
        remove.title = "Remove from comparison";
        remove.addEventListener("click", function () {
          compareSeats.splice(i, 1);
          renderCompare();
          fetchIndex().then(function (entries) { renderResults(input.value, entries); });
        });
        th.appendChild(document.createTextNode(" "));
        th.appendChild(remove);
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      rows.forEach(function (row) {
        var tr = document.createElement("tr");
        var th = document.createElement("th");
        th.textContent = row[0];
        tr.appendChild(th);
        compareSeats.forEach(function (s) {
          var td = document.createElement("td");
          td.textContent = row[1](s);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);

      comparePanel.appendChild(table);
      if (compareSeats.length < 2) {
        var hint = document.createElement("p");
        hint.innerHTML = "<small>Search for and add one more seat to compare.</small>";
        comparePanel.appendChild(hint);
      }
    }

    input.addEventListener("input", function () {
      fetchIndex().then(function (entries) { renderResults(input.value, entries); });
    });
  }
})();
