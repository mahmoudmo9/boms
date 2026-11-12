/** v0.10.0 theme setting: light, dark and system (following the system live), kept across loads, and applied before
 * the first paint by public/theme-init.js. The DOM pieces are small fakes: the logic needs no browser. */
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

type Listener = (e: { matches: boolean }) => void;

function fakeBrowser(systemDark: boolean, stored: Record<string, string> = {}) {
  const classes = new Set<string>();
  const listeners = new Set<Listener>();
  const media = {
    matches: systemDark,
    addEventListener: (_: string, fn: Listener) => listeners.add(fn),
    removeEventListener: (_: string, fn: Listener) => listeners.delete(fn),
  };
  const root = {
    classList: { toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)), contains: (n: string) => classes.has(n) },
    dataset: {} as Record<string, string>, lang: "", dir: "",
  };
  const storage = { getItem: (k: string) => stored[k] ?? null, setItem: (k: string, v: string) => { stored[k] = v; } };
  vi.stubGlobal("document", { documentElement: root });
  vi.stubGlobal("window", { matchMedia: () => media });
  vi.stubGlobal("localStorage", storage);
  return {
    root, stored, listeners,
    dark: () => classes.has("dark"),
    systemChanges: (dark: boolean) => { media.matches = dark; listeners.forEach((fn) => fn({ matches: dark })); },
  };
}

describe("theme setting", () => {
  beforeEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

  it("applies light and dark and keeps the choice", async () => {
    const b = fakeBrowser(true);
    const { applyTheme, storedTheme } = await import("./prefs");
    applyTheme("light");
    expect([b.dark(), b.root.dataset.theme, b.stored["boms.theme"], storedTheme()]).toEqual([false, "light", "light", "light"]);
    applyTheme("dark");
    expect([b.dark(), b.root.dataset.theme, storedTheme()]).toEqual([true, "dark", "dark"]);
    b.systemChanges(false);                                   // a fixed choice ignores the system
    expect(b.dark()).toBe(true);
  });

  it("system follows Windows and switches live", async () => {
    const b = fakeBrowser(false);
    const { applyTheme, storedTheme } = await import("./prefs");
    applyTheme("system");
    expect([b.dark(), b.root.dataset.theme, storedTheme()]).toEqual([false, "system", "system"]);
    b.systemChanges(true);
    expect(b.dark()).toBe(true);
    b.systemChanges(false);
    expect(b.dark()).toBe(false);
    applyTheme("dark");                                       // leaving «system» stops following
    expect(b.listeners.size).toBe(0);
    b.systemChanges(false);
    expect(b.dark()).toBe(true);
  });

  it("an unknown stored value means system", async () => {
    fakeBrowser(false, { "boms.theme": "sepia" });
    const { storedTheme } = await import("./prefs");
    expect(storedTheme()).toBe("system");
  });
});

describe("no flash on load (public/theme-init.js)", () => {
  const script = readFileSync("public/theme-init.js", "utf-8");
  const run = (systemDark: boolean, stored: Record<string, string>) => {
    const b = fakeBrowser(systemDark, stored);
    new Function("document", "window", "localStorage", script)(document, window, localStorage);
    return [b.dark(), b.root.dataset.theme];
  };
  beforeEach(() => vi.unstubAllGlobals());
  it("sets the theme class before the app loads, from the kept choice", () => {
    expect(run(false, { "boms.theme": "dark" })).toEqual([true, "dark"]);
    expect(run(true, { "boms.theme": "light" })).toEqual([false, "light"]);
  });
  it("follows the system when nothing or «system» is kept", () => {
    expect(run(true, {})).toEqual([true, "system"]);
    expect(run(false, { "boms.theme": "system" })).toEqual([false, "system"]);
  });
  it("is loaded by index.html before the application script, from the app's own origin", () => {
    const html = readFileSync("index.html", "utf-8");
    expect(html.indexOf('<script src="/theme-init.js"></script>')).toBeGreaterThan(0);
    expect(html.indexOf("/theme-init.js")).toBeLessThan(html.indexOf("/src/main.tsx"));
    expect(html).not.toMatch(/<script>(?!<)/);                 // no inline script: the CSP forbids it
  });
});
