(function initializeTheme() {
  var preference = "system";
  try {
    var stored = window.localStorage.getItem("bricky-theme");
    if (stored === "light" || stored === "dark" || stored === "system") {
      preference = stored;
    }
  } catch (_error) {
    // Storage may be unavailable in privacy-restricted browser contexts.
  }
  var systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  var theme = preference === "system" ? (systemDark ? "dark" : "light") : preference;
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "dark" ? "#160f11" : "#7f1d2d");
})();
