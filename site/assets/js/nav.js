// Click-to-toggle dropdown menus for the header nav's grouped links
// ("Chambers", "Browse") — plain click/keyboard toggling, not CSS :hover,
// since :hover-only dropdowns don't work on touch devices at all (no hover
// state to trigger them) and this site's other interactive bits
// (header-search's own dropdown, in search.js) already use the same
// click-to-open/click-outside-to-close pattern, so this matches rather
// than introducing a second convention.
(function () {
  function closeAll(except) {
    document.querySelectorAll(".nav-group.open").forEach(function (group) {
      if (group !== except) {
        group.classList.remove("open");
        group.querySelector(".nav-group-toggle").setAttribute("aria-expanded", "false");
      }
    });
  }

  document.querySelectorAll(".nav-group").forEach(function (group) {
    var toggle = group.querySelector(".nav-group-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      var isOpen = group.classList.contains("open");
      closeAll(isOpen ? null : group);
      group.classList.toggle("open", !isOpen);
      toggle.setAttribute("aria-expanded", String(!isOpen));
    });
  });

  document.addEventListener("click", function () {
    closeAll(null);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAll(null);
  });
})();
