/** v0.10.0 finance: the profit bridge steps. */
import { describe, expect, it } from "vitest";

import { profitBridge } from "./finance";


describe("profit bridge (v0.10.0)", () => {
  const pair = (deal: string | null, base: string | null = deal) => ({ deal, base }) as never;
  const profit = {
    profit: { planned: pair("1000"), actual: { deal: "820", base: "820" }, variance: pair("-180") },
    revenue: { planned: pair("5000"), actual: { deal: "5100", base: "5100" }, variance: pair("100") },
    rows: [
      { kind: "goods", planned: pair("3500"), actual: { deal: "3700", base: "3700" }, variance: pair("200"), variance_percent: null, estimated: false, unrealized: false },
      { kind: "freight_international", planned: pair("300"), actual: { deal: "380", base: "380" }, variance: pair("80"), variance_percent: null, estimated: true, unrealized: false },
      { kind: "insurance", planned: pair("50"), actual: { deal: "50", base: "50" }, variance: pair("0"), variance_percent: null, estimated: false, unrealized: false },
    ],
  } as never;
  it("plan → revenue → cost groups → actual, adding up exactly; empty groups left out; estimated marked", () => {
    const b = profitBridge(profit, (k) => k)!;
    expect(b.steps.map((s) => [s.key, s.value, s.kind])).toEqual([
      ["plan", 1000, "total"], ["revenue", 100, "delta"], ["goods", -200, "delta"], ["freight_international", -80, "delta"], ["actual", 820, "total"]]);
    expect(b.estimated).toEqual(["freight_international"]);
  });
  it("a remainder (lines without a plan) shows as its own step; no plan means no bridge", () => {
    const b = profitBridge({ ...(profit as object), profit: { planned: pair("1000"), actual: { deal: "800", base: "800" }, variance: pair("-200") } } as never, (k) => k)!;
    expect(b.steps.find((s) => s.key === "other")?.value).toBe(-20);
    expect(profitBridge({ ...(profit as object), profit: { planned: pair(null), actual: { deal: "800", base: "800" }, variance: pair(null) } } as never, (k) => k)).toBeNull();
  });
});
