/** v0.10.0 chart geometry: scaling, the waterfall of the profit bridge, the cash-flow balance with its lowest point,
 * the route with the travelled part. */
import { describe, expect, it } from "vitest";

import { areaPath, bridgeBars, cashFlowBars, lastRecorded, linePath, routeNodes, scalePoints, smoothPath } from "./charts";

describe("sparkline", () => {
  it("scales into the box with the highest value at the top", () => {
    const p = scalePoints([10, 20, 15], 100, 50, 0);
    expect(p).toEqual([{ x: 0, y: 50 }, { x: 50, y: 0 }, { x: 100, y: 25 }]);
    expect(linePath(p)).toBe("M0 50 L50 0 L100 25");
    expect(areaPath(p, 50)).toBe("M0 50 L50 0 L100 25 L100 50 L0 50 Z");
  });
  it("draws a flat or single series in the middle", () => {
    expect(scalePoints([5, 5], 100, 40, 0).map((p) => p.y)).toEqual([20, 20]);
    expect(scalePoints([7], 100, 40)).toEqual([{ x: 50, y: 20 }]);
    expect(scalePoints([], 100, 40)).toEqual([]);
  });
});

describe("profit bridge", () => {
  const steps = [
    { key: "plan", label: "Plan", value: 1000, kind: "total" as const },
    { key: "fx", label: "FX", value: 200, kind: "delta" as const },
    { key: "costs", label: "Costs", value: -500, kind: "delta" as const },
    { key: "actual", label: "Actual", value: 700, kind: "total" as const },
  ];
  const bars = bridgeBars(steps, 400, 120, 0);
  it("each delta starts where the running sum is; totals stand on zero", () => {
    expect(bars.map((b) => [b.from, b.to])).toEqual([[0, 1000], [1000, 1200], [1200, 700], [0, 700]]);
    expect(bars.map((b) => b.positive)).toEqual([true, true, false, true]);
  });
  it("heights are proportional to the amounts (120 px for the 1200 span)", () => {
    expect(bars.map((b) => b.height)).toEqual([100, 20, 50, 70]);
    expect(bars.map((b) => b.y)).toEqual([20, 0, 0, 50]);
    expect(bars.map((b) => b.x)).toEqual([0, 100, 200, 300]);
  });
  it("a loss below zero extends the scale downwards", () => {
    const b = bridgeBars([{ key: "p", label: "", value: 100, kind: "total" }, { key: "c", label: "", value: -300, kind: "delta" }, { key: "a", label: "", value: -200, kind: "total" }], 300, 150, 0);
    expect(b.map((x) => [x.from, x.to])).toEqual([[0, 100], [100, -200], [0, -200]]);
    expect(b[2].positive).toBe(false);
    expect(b[0].y + b[0].height).toBe(b[2].y);         // both stand on the zero line
  });
});

describe("cash flow", () => {
  const points = [
    { key: "w1", label: "W1", cashIn: 100, cashOut: 0 },
    { key: "w2", label: "W2", cashIn: 0, cashOut: 250 },
    { key: "w3", label: "W3", cashIn: 300, cashOut: 50 },
  ];
  it("runs the balance from the opening amount and marks the lowest point", () => {
    const { bars } = cashFlowBars(points, 300, 100, 50);
    expect(bars.map((b) => b.balance)).toEqual([150, -100, 150]);
    expect(bars.map((b) => b.lowest)).toEqual([false, true, false]);
  });
  it("draws in above and out below the zero line", () => {
    const { bars, zeroY, balancePath } = cashFlowBars(points, 300, 110, 0);
    expect(zeroY).toBe(60);                            // scale 300 .. -250 over 110 px
    expect([bars[0].inY, bars[0].inHeight, bars[0].outHeight]).toEqual([40, 20, 0]);
    expect([bars[1].outY, bars[1].outHeight]).toEqual([60, 50]);
    expect(balancePath.startsWith("M")).toBe(true);
  });
  it("is empty without points", () => {
    expect(cashFlowBars([], 300, 100).bars).toEqual([]);
  });
});

describe("route line", () => {
  const stops = [
    { key: "a", name: "Shanghai", code: "CNSHA", state: "done" as const },
    { key: "b", name: "Jebel Ali", code: "AEJEA", state: "last" as const },
    { key: "c", name: "Bushehr", code: "IRBUZ", state: "upcoming" as const },
  ];
  it("puts the origin at the start edge and the destination at the end edge, mirrored in RTL", () => {
    const ltr = routeNodes(stops, 800, 200, false, 20);
    expect([ltr[0].x, ltr[2].x]).toEqual([20, 780]);
    const rtl = routeNodes(stops, 800, 200, true, 20);
    expect([rtl[0].x, rtl[2].x]).toEqual([780, 20]);
    expect(ltr[1].y).toBeLessThan(ltr[0].y);           // the arc rises in the middle
  });
  it("knows where the travelled part ends", () => {
    expect(lastRecorded(stops)).toBe(1);
    expect(lastRecorded(stops.map((s) => ({ ...s, state: "upcoming" as const })))).toBe(-1);
  });
  it("draws a smooth path through the stops", () => {
    expect(smoothPath([{ x: 0, y: 0 }, { x: 10, y: 10 }])).toBe("M0 0 L10 10");
    expect(smoothPath([{ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 20, y: 0 }])).toBe("M0 0 Q10 10 15 5 T20 0");
    expect(smoothPath([{ x: 0, y: 0 }])).toBe("");
  });
});
