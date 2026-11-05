import { describe, expect, it } from "vitest";

import { cashRows, itemProgress, manualPoSteps, orderProgress, parseContainers, stepGroups, stepState } from "./execution";

describe("delivery progress", () => {
  it("counts an item as delivered only when the full quantity arrived", () => {
    expect(itemProgress("88", "30")).toEqual({ done: 30, total: 88, complete: false, percent: 34 });
    expect(itemProgress("88.0000", "88")).toMatchObject({ complete: true, percent: 100 });
    expect(itemProgress("0", "0").complete).toBe(false);
  });
  it("counts the items fully delivered out of all («۲ از ۳ قلم»)", () => {
    expect(orderProgress([{ quantity: "10", delivered: "10" }, { quantity: "2", delivered: "1" }, { quantity: "5", delivered: "5" }]))
      .toEqual({ done: 2, total: 3, complete: false });
    expect(orderProgress([{ quantity: "1", delivered: "1" }]).complete).toBe(true);
    expect(orderProgress([]).complete).toBe(false);
  });
});

describe("cash position display", () => {
  it("one row per currency with the net tied up and what is still expected", () => {
    const rows = cashRows({ actual: { USD: { received: "1000.0000", paid: "600.0000", net_tied_up: "-400.0000" },
      IRR: { received: "0", paid: "5000", net_tied_up: "5000" } }, outstanding: { USD: { in: "0", out: "900" }, EUR: { in: "10", out: "0" } }, plan: null });
    expect(rows.map((r) => r.currency)).toEqual(["EUR", "IRR", "USD"]);
    expect(rows.find((r) => r.currency === "USD")).toMatchObject({ received: "1000.0000", net: "-400.0000", tone: "success", outstandingOut: "900" });
    expect(rows.find((r) => r.currency === "IRR")?.tone).toBe("warning");
    expect(rows.find((r) => r.currency === "EUR")).toMatchObject({ received: "0", net: "0", tone: "neutral", outstandingIn: "10" });
    expect(cashRows(null)).toEqual([]);
  });
});

describe("process stepper", () => {
  const today = "2026-11-05";
  it("states: done, not applicable, overdue, in progress, to do", () => {
    expect(stepState({ status: "done", due_on: "2026-01-01" }, today)).toBe("done");
    expect(stepState({ status: "not_applicable", due_on: null }, today)).toBe("na");
    expect(stepState({ status: "pending", due_on: "2026-11-04" }, today)).toBe("overdue");
    expect(stepState({ status: "in_progress", due_on: "2026-11-10" }, today)).toBe("current");
    expect(stepState({ status: "pending", due_on: null }, today)).toBe("todo");
  });
  it("groups steps in template order with done counts", () => {
    const groups = stepGroups([
      { group: "customs", status: "done", position: 8 }, { group: "supplier_order", status: "done", position: 1 },
      { group: "supplier_order", status: "pending", position: 2 }, { group: "customs", status: "not_applicable", position: 9 },
      { group: null, status: "pending", position: 20 }]);
    expect(groups.map((g) => [g.group, g.steps.length, g.done])).toEqual([["supplier_order", 2, 1], ["customs", 2, 2], ["", 1, 0]]);
  });
});

describe("small helpers", () => {
  it("containers typed with spaces, commas or Persian commas", () => {
    expect(parseContainers("mscu1234567, TGHU7654321،MSCU1234567\nCAIU0000001")).toEqual(["MSCU1234567", "TGHU7654321", "CAIU0000001"]);
  });
  it("the statuses a PO can be moved to by hand", () => {
    expect(manualPoSteps("confirmed")).toEqual(["in_production", "ready", "shipped"]);
    expect(manualPoSteps("draft")).toEqual([]);
  });
});
