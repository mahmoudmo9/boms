import { describe, expect, it } from "vitest";

import { GATE_CONDITIONS, gateChecklist, gridTarget, marginMarkupView } from "./costing";

describe("margin and markup display", () => {
  it("shows both views of the same profit", () => {
    // cost 81,000, price 101,250: margin 20 %, markup 25 % (the server's numbers)
    expect(marginMarkupView({ profit: "20250", margin_percent: "20.00", markup_percent: "25.00" }))
      .toEqual({ margin: "20.00 %", markup: "25.00 %", profit: "20250" });
  });
  it("formats the numbers with the given formatter (user's digits)", () => {
    expect(marginMarkupView({ profit: "1", margin_percent: "20.00", markup_percent: "25.00" }, (v) => `<${Number(v)}>`))
      .toMatchObject({ margin: "<20> %", markup: "<25> %" });
  });
  it("marks unknown values", () => {
    expect(marginMarkupView({ profit: null, margin_percent: null, markup_percent: null }))
      .toEqual({ margin: "—", markup: "—", profit: null });
  });
});

describe("lines grid keyboard navigation", () => {
  it("moves down with Enter / ArrowDown and up with ArrowUp in the same column", () => {
    expect(gridTarget("Enter", 0, "amount", 3)).toBe("1-amount");
    expect(gridTarget("ArrowDown", 1, "percent", 3)).toBe("2-percent");
    expect(gridTarget("ArrowUp", 2, "amount", 3)).toBe("1-amount");
  });
  it("stays inside the grid and ignores other keys", () => {
    expect(gridTarget("ArrowDown", 2, "amount", 3)).toBeNull();
    expect(gridTarget("ArrowUp", 0, "amount", 3)).toBeNull();
    expect(gridTarget("Tab", 0, "amount", 3)).toBeNull();
    expect(gridTarget("a", 0, "amount", 3)).toBeNull();
  });
});

describe("gate checklist", () => {
  it("lists every condition, failed ones with their details, in a fixed order", () => {
    const rows = gateChecklist([{ code: "fx_stale", as_of: "2026-10-01" }, { code: "sheet_not_final", status: "draft" }],
      { fx_stale: null, unconfirmed_parameter: null });
    expect(rows.map((r) => r.code)).toEqual([...GATE_CONDITIONS]);
    expect(rows.filter((r) => !r.ok).map((r) => r.code)).toEqual(["sheet_not_final", "fx_stale"]);
    expect(rows.find((r) => r.code === "fx_stale")?.failure).toEqual({ code: "fx_stale", as_of: "2026-10-01" });
  });
  it("marks an override and keeps unknown failure codes", () => {
    const rows = gateChecklist([{ code: "something_new" }], { fx_stale: "re-checked", unconfirmed_parameter: null });
    expect(rows.find((r) => r.code === "fx_stale")).toMatchObject({ ok: true, overridden: "re-checked" });
    expect(rows.at(-1)).toMatchObject({ code: "something_new", ok: false });
  });
  it("passes everything when there are no failures", () => {
    expect(gateChecklist([]).every((r) => r.ok)).toBe(true);
  });
});
