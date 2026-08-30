(function () {
  function withBaseUrl(path) {
    var baseurl = document.body ? document.body.dataset.siteBaseurl || "" : "";
    return baseurl + path;
  }

  function readIndex(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : [];
  }

  var allEntries = []
    .concat(readIndex("search-index-seats"))
    .concat(readIndex("search-index-candidates"))
    .concat(readIndex("search-index-towns"))
    .concat(readIndex("search-index-parties"));

  var input = document.getElementById("search-input");
  var resultsEl = document.getElementById("search-results");
  var comparePanel = document.getElementById("compare-panel");
  var compareSeats = [];

  function typeLabel(type) {
    return { seat: "Seat", candidate: "Candidate", town: "Town", party: "Party" }[type] || type;
  }

  function renderResults(query) {
    resultsEl.innerHTML = "";
    if (query.length < 2) return;
    var q = query.toLowerCase();
    var matches = allEntries.filter(function (e) {
      return e.name.toLowerCase().indexOf(q) !== -1;
    }).slice(0, 25);

    matches.forEach(function (e) {
      var li = document.createElement("li");

      var link = document.createElement("a");
      link.href = withBaseUrl(e.url);
      link.textContent = e.name;

      var meta = document.createElement("span");
      meta.className = "search-result-meta";
      var metaText = " (" + typeLabel(e.type);
      if (e.type === "seat") {
        metaText += ", " + e.competitiveness_label;
      } else if (e.detail) {
        metaText += ", " + e.detail;
      } else if (e.party) {
        metaText += ", " + e.party;
      }
      metaText += ")";
      meta.textContent = metaText;

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
          renderResults(input.value);
        });
        li.appendChild(document.createTextNode(" "));
        li.appendChild(btn);
      }

      resultsEl.appendChild(li);
    });

    if (matches.length === 0) {
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
        renderResults(input.value);
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
    renderResults(input.value);
  });
})();
