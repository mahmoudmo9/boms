/** v0.10.0 tokens: both themes define every token; every promised text/surface and status pair meets WCAG AA; the
 * Tailwind mirror names only tokens that exist; the design lint refuses literals. */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// @ts-expect-error a plain .mjs script without types
import { checkDir, checkText } from "../../scripts/check-design.mjs";
import { contrast, contrastTable, parseColor, readTheme } from "./tokens";

const css = readFileSync("src/design/tokens.css", "utf-8");

describe("themes", () => {
  const light = readTheme(css, "light"), dark = readTheme(css, "dark");
  const shared = ["duration-fast", "duration", "duration-slow", "ease-out", "ease-in-out", "z-sticky", "z-rail", "z-drawer", "z-modal", "z-popover",
    "z-toast", "z-palette", "rail-width", "rail-width-collapsed", "topbar-height", "target"];
  it("define exactly the same tokens", () => {
    const themed = (t: Record<string, string>) => Object.keys(t).filter((k) => !shared.includes(k)).sort();
    expect(themed(dark)).toEqual(themed(light));
    expect(themed(light).length).toBeGreaterThanOrEqual(60);
    for (const name of shared) expect(light[name], name).toBeTruthy();
  });
  it("hold the palette of the reference files", () => {
    expect([dark.bg, dark.surface, dark["surface-2"]]).toEqual(["#0b0f1a", "#121827", "#151c2d"]);
    expect([dark.accent, dark["accent-bright"], dark.title, dark.fg, dark["fg-2"], dark.muted]).toEqual(["#d9be8c", "#e7cc97", "#f4efe3", "#e9e4d8", "#b9bfcd", "#8c93a6"]);
    expect([dark.success, dark.warning, dark.danger]).toEqual(["#9fc7ae", "#e7cc97", "#f2c3b9"]);
    expect([light.bg, light.surface, light["surface-2"]]).toEqual(["#f4f2ed", "#ffffff", "#f2efe8"]);
    expect([light.title, light.fg, light.muted, light["accent-bright"], light.success, light.danger]).toEqual(["#121826", "#1e2a44", "#5b6070", "#c9a46a", "#2f6b4f", "#a23b2e"]);
  });
  it("every colour the Tailwind mirror names is a token, and every colour token is mirrored", () => {
    const mirrored = [...css.matchAll(/--color-([\w-]+):\s*var\(--([\w-]+)\)/g)];
    for (const [, util, token] of mirrored) {
      expect(util).toBe(token);
      expect(light[token], token).toBeTruthy();
    }
    const colourTokens = Object.keys(light).filter((k) => parseColor(light[k]) && !k.startsWith("bg-glow") && !k.startsWith("shadow") && !k.startsWith("ring"));
    expect(colourTokens.filter((k) => !mirrored.some(([, u]) => u === k))).toEqual([]);
  });
  it("motion stays between 150 and 250 ms", () => {
    expect([light["duration-fast"], light.duration, light["duration-slow"]]).toEqual(["150ms", "200ms", "250ms"]);
  });
});

describe("contrast (WCAG 2.1 AA)", () => {
  it("computes the ratio", () => {
    expect(contrast([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
    expect(contrast([255, 255, 255], [255, 255, 255])).toBe(1);
    expect(parseColor("rgba(18, 24, 38, 0.45)")).toEqual({ rgb: [18, 24, 38], alpha: 0.45 });
  });
  it("every text / surface and status pair passes in both themes", () => {
    const table = contrastTable(css);
    expect(table.length).toBeGreaterThan(150);
    expect(table.filter((r) => !r.pass).map((r) => `${r.theme}: ${r.fg} on ${r.bg} = ${r.ratio} (< ${r.min})`)).toEqual([]);
  });
  it("the mockup values that were adjusted really failed", () => {
    const rgb = (h: string) => parseColor(h)!.rgb;
    expect(contrast(rgb("#6b7080"), rgb("#f4f2ed"))).toBeLessThan(4.5);       // light muted of the mockups on paper
    expect(contrast(rgb("#8a6a3a"), rgb("#f4f2ed"))).toBeLessThan(4.5);       // light brass text on paper
    expect(contrast(rgb("#121826"), rgb("#8a6a3a"))).toBeLessThan(4.5);       // ink on the dark end of the light gradient
    expect(contrast(rgb("#d9d4c7"), rgb("#ffffff"))).toBeLessThan(3);         // light input border
  });
});

describe("design lint", () => {
  const rules = (text: string) => checkText(text).map((p: { rule: string }) => p.rule);
  it("refuses a colour literal", () => {
    expect(rules('<div style={{ color: "#D9BE8C" }} />')).toEqual(["colour literal"]);
    expect(rules("background: rgba(255,255,255,.03);")).toEqual(["colour literal"]);
    expect(rules('<p className="text-red-500 bg-white" />')).toEqual(["colour literal", "colour literal"]);
  });
  it("refuses a pixel font size and arbitrary spacing", () => {
    expect(rules('<p className="text-[13px]" />')).toEqual(["pixel font size"]);
    expect(rules("font-size: 13px;")).toEqual(["pixel font size"]);
    expect(rules('<p style={{ fontSize: 13 }} />')).toEqual(["pixel font size"]);
    expect(rules('<p className="p-[13px] gap-[0.4rem] -mt-[5vh]" />')).toEqual(["arbitrary spacing", "arbitrary spacing", "arbitrary spacing"]);
  });
  it("still refuses physical directions", () => {
    expect(rules('<p className="ml-2 text-left" />')).toEqual(["physical direction", "physical direction"]);
  });
  it("accepts token classes, anchors, sizes and grids", () => {
    expect(rules('<a href="#top" className="bg-surface text-muted p-3 gap-2.5 text-sm max-h-[65vh] grid-cols-[minmax(0,1fr)_16rem] w-72" />')).toEqual([]);
    expect(rules('<Link to="#item-3" id="x" />')).toEqual([]);
  });
  it("the whole of src/ is clean", () => {
    expect(checkDir("src")).toEqual([]);
  });
});
