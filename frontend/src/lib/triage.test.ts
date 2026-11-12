/** v0.10.0 quick triage: keys (both layouts, both directions), moving on, progress. */
import { describe, expect, it } from "vitest";

import { advance, progress, triageCommand } from "./triage";

describe("quick triage", () => {
  it("S, R and D decide; arrows move (next is ArrowLeft in RTL)", () => {
    expect(["s", "S", "r", "d"].map((k) => triageCommand(k, true))).toEqual(["star", "star", "reviewing", "dismiss"]);
    expect(["س", "ق", "ی"].map((k) => triageCommand(k, true))).toEqual(["star", "reviewing", "dismiss"]);
    expect([triageCommand("ArrowLeft", true), triageCommand("ArrowRight", true)]).toEqual(["next", "previous"]);
    expect([triageCommand("ArrowRight", false), triageCommand("ArrowLeft", false)]).toEqual(["next", "previous"]);
    expect(triageCommand("x", false)).toBeNull();
  });
  it("moves on and stays at the ends", () => {
    expect([advance(0, 3, 1), advance(2, 3, 1), advance(0, 3, -1), advance(0, 0, 1)]).toEqual([1, 2, 0, 0]);
  });
  it("counts the decided listings", () => {
    expect(progress(new Set(["a", "c", "z"]), ["a", "b", "c", "d"])).toEqual({ done: 2, total: 4, percent: 50 });
    expect(progress(new Set(), [])).toEqual({ done: 0, total: 0, percent: 0 });
  });
});
