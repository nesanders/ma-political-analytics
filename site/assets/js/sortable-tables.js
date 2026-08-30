// Makes every data table in the page body sortable by clicking a column
// header — no framework, just a plain script tag (like the chart-building
// scripts already inline in chamber.html), since this needs to run on
// every page, not just the ones with a chart or the AskAI React island.
(function () {
  function getCellText(row, index) {
    var cell = row.children[index];
    return cell ? cell.textContent.trim() : "";
  }

  // Numeric-aware compare: strips "%" and "," so "60.0%" and "11,093" sort
  // as numbers, not lexicographically (which would put "9" after "10").
  // Falls back to a plain string compare for genuinely non-numeric columns
  // (candidate/district names, party labels).
  function compareCells(a, b) {
    var na = parseFloat(a.replace(/[%,]/g, ""));
    var nb = parseFloat(b.replace(/[%,]/g, ""));
    var aIsNum = a !== "" && !isNaN(na);
    var bIsNum = b !== "" && !isNaN(nb);
    if (aIsNum && bIsNum) return na - nb;
    if (aIsNum !== bIsNum) return aIsNum ? -1 : 1;
    return a.localeCompare(b);
  }

  function makeSortable(table) {
    var thead = table.tHead;
    var tbody = table.tBodies[0];
    if (!thead || !tbody) return;
    var headerRow = thead.rows[0];
    if (!headerRow) return;

    Array.prototype.forEach.call(headerRow.cells, function (th, index) {
      th.classList.add("sortable-col");
      th.setAttribute("role", "button");
      th.setAttribute("tabindex", "0");
      var ascending = true;

      function sort() {
        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(function (r1, r2) {
          var cmp = compareCells(getCellText(r1, index), getCellText(r2, index));
          return ascending ? cmp : -cmp;
        });
        rows.forEach(function (r) {
          tbody.appendChild(r);
        });

        Array.prototype.forEach.call(headerRow.cells, function (h) {
          h.classList.remove("sorted-asc", "sorted-desc");
        });
        th.classList.add(ascending ? "sorted-asc" : "sorted-desc");
        ascending = !ascending;
      }

      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          sort();
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Scoped to <main> so AskAI's own dynamically-inserted result tables
    // (outside <main>, in the sidebar) aren't affected — they're small,
    // one-off query results, not a browsing table worth re-sorting.
    document.querySelectorAll("main table").forEach(makeSortable);
  });
})();
