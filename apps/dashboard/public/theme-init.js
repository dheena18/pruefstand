// No-flash theme (ui-spec §7): runs blocking in <head> before first paint, loaded as a file, never inline.
(function () {
  var mode = "system";
  try {
    var stored = window.localStorage.getItem("pruefstand.theme");
    if (stored === "light" || stored === "dark") mode = stored;
  } catch (error) {
    mode = "system";
  }
  document.documentElement.setAttribute("data-theme", mode);
})();
