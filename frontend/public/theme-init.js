// Applies the stored theme before the first paint (no flash). A file, not an inline script: the app's
// Content-Security-Policy allows scripts from its own origin only. lib/prefs.tsx keeps it in step afterwards.
(function () {
  var theme = "system";
  try {
    var stored = localStorage.getItem("boms.theme");
    if (stored === "light" || stored === "dark") theme = stored;
  } catch (e) { /* storage unavailable: follow the system */ }
  var dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  var root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.dataset.theme = theme;
})();
