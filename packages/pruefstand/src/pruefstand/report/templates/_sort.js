(function () {
  function key(row, i) {
    var c = row.cells[i];
    var v = c.getAttribute("data-sort");
    if (v === null) { v = c.textContent.trim(); }
    var n = parseFloat(v.replace("\u2212", "-"));
    return isNaN(n) ? v.toLowerCase() : n;
  }
  function sortBy(th) {
    var table = th.closest("table");
    var body = table.tBodies[0];
    var i = th.cellIndex;
    var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (a, b) {
      var x = key(a, i), y = key(b, i);
      if (x === y) { return 0; }
      if (typeof x !== typeof y) { return typeof x === "number" ? -1 : 1; }
      return (x < y ? -1 : 1) * dir;
    });
    rows.forEach(function (r) { body.appendChild(r); });
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (h) {
      h.setAttribute("aria-sort", h === th ? (dir === 1 ? "ascending" : "descending") : "none");
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll("th[aria-sort] button"), function (b) {
    b.addEventListener("click", function () { sortBy(b.parentNode); });
  });
})();
