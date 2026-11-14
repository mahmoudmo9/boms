/** Developer mode (Settings → System): shows the `/design` catalogue. Kept apart from the page, which loads on demand. */
const DEV_KEY = "boms.dev";

export function devMode(): boolean {
  try { return localStorage.getItem(DEV_KEY) === "1"; } catch { return false; }
}

export function setDevMode(on: boolean): void {
  try { if (on) localStorage.setItem(DEV_KEY, "1"); else localStorage.removeItem(DEV_KEY); } catch { /* per-browser convenience only */ }
}
