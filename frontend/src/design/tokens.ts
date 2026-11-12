/** Reading the token file (v0.10.0 section 1): the themes as name -> value maps and WCAG contrast, used by the token
 * tests and by the `/design` reference page. The values themselves live only in tokens.css. */

export type Theme = "light" | "dark";
export type Rgb = [number, number, number];

/** The custom properties of one rule block (`:root {…}` or `:root.dark {…}`) of the token file. */
export function readTheme(css: string, theme: Theme): Record<string, string> {
  const out: Record<string, string> = {};
  const blocks = css.matchAll(/(^|\n)(:root(?:\.dark)?)(?:,\s*\.theme-(?:light|dark))?\s*\{([^}]*)\}/g);
  for (const [, , sel, body] of blocks) {
    if ((sel === ":root.dark") !== (theme === "dark")) continue;
    for (const [, name, value] of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) out[name] = value.trim();
  }
  return out;
}

export function parseColor(value: string): { rgb: Rgb; alpha: number } | null {
  const hex = /^#([0-9a-f]{6})$/i.exec(value.trim());
  if (hex) return { rgb: [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) as Rgb, alpha: 1 };
  const rgba = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(value.trim());
  if (rgba) return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], alpha: rgba[4] === undefined ? 1 : Number(rgba[4]) };
  return null;
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance([r, g, b]: Rgb): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG 2.1 contrast ratio of two opaque colours, 1 to 21. */
export function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function contrastOf(theme: Record<string, string>, fg: string, bg: string): number {
  const a = parseColor(theme[fg]), b = parseColor(theme[bg]);
  if (!a || !b || a.alpha !== 1 || b.alpha !== 1) throw new Error(`not an opaque colour: --${fg} ${theme[fg]} / --${bg} ${theme[bg]}`);
  return contrast(a.rgb, b.rgb);
}

/** The pairs the system promises: [foreground token, background token, minimum ratio, what it is]. */
const SURFACES = ["bg", "surface", "surface-2", "surface-3", "sunken", "hover"];
const TEXT = ["title", "fg", "fg-2", "muted", "accent", "success", "warning", "danger", "info"];
export const CONTRAST_PAIRS: [string, string, number, string][] = [
  ...SURFACES.flatMap((s) => TEXT.map((t) => [t, s, 4.5, "text"] as [string, string, number, string])),
  ...SURFACES.map((s) => ["control", s, 3, "control boundary"] as [string, string, number, string]),
  ...SURFACES.map((s) => ["focus", s, 3, "focus ring"] as [string, string, number, string]),
  ...["success", "warning", "danger", "info", "accent"].map((k) => [k, `${k}-soft`, 4.5, "status chip"] as [string, string, number, string]),
  ...["title", "fg"].map((k) => [k, "accent-soft", 4.5, "text on accent tint"] as [string, string, number, string]),
  ["accent-fg", "accent-fill-from", 4.5, "primary button"], ["accent-fg", "accent-fill-to", 4.5, "primary button"],
  ["accent-fg", "accent-bright", 4.5, "gold chip"],
  ["rail-title", "rail", 4.5, "rail"], ["rail-fg", "rail", 4.5, "rail"], ["rail-muted", "rail", 4.5, "rail"], ["rail-accent", "rail", 4.5, "rail"],
  ["rail-title", "rail-active", 4.5, "rail"], ["rail-fg", "rail-active", 4.5, "rail"], ["rail-muted", "rail-active", 4.5, "rail"],
  ["title", "card-accent-from", 4.5, "accent card"], ["fg", "card-accent-from", 4.5, "accent card"], ["muted", "card-accent-from", 4.5, "accent card"],
  ["accent", "card-accent-from", 4.5, "accent card"],
  ...["chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "chart-6", "chart-in", "chart-out", "chart-line"]
    .map((k) => [k, "surface", 3, "chart mark"] as [string, string, number, string]),
];

export function contrastTable(css: string): { theme: Theme; fg: string; bg: string; ratio: number; min: number; kind: string; pass: boolean }[] {
  return (["light", "dark"] as Theme[]).flatMap((theme) => {
    const t = readTheme(css, theme);
    return CONTRAST_PAIRS.map(([fg, bg, min, kind]) => {
      const ratio = Math.round(contrastOf(t, fg, bg) * 100) / 100;
      return { theme, fg, bg, ratio, min, kind, pass: ratio >= min };
    });
  });
}
