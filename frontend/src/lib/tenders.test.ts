import { describe, expect, it } from "vitest";

import { blockerMessage, combineDateTime, nextGuaranteeSteps, parseReminderDays, progressText, STAGES, stepper, timeOf } from "./tenders";

describe("tender stepper", () => {
  it("marks done / current / todo and hints only a stage ahead of the current one", () => {
    const rows = stepper("pricing", "envelopes");
    expect(rows.map((r) => r.state)).toEqual(["done", "done", "current", "todo", "todo", "todo", "todo", "todo", "todo"]);
    expect(rows.filter((r) => r.hinted).map((r) => r.stage)).toEqual(["envelopes"]);
    expect(stepper("envelopes", "pricing").some((r) => r.hinted)).toBe(false);
    expect(rows).toHaveLength(STAGES.length);
  });
});

describe("blocker messages", () => {
  it("formats envelope counts, guarantee dates and expired documents", () => {
    expect(blockerMessage({ code: "envelopes_incomplete", envelopes: { A: 2, B: 1 } })).toEqual({ key: "tenders.blockers.envelopes_incomplete", values: { list: "A: 2، B: 1" } });
    expect(blockerMessage({ code: "guarantee_validity_short", valid_until: "2026-11-01", needed_until: "2026-12-01" }).values).toEqual({ valid: "2026-11-01", needed: "2026-12-01" });
    expect(blockerMessage({ code: "company_document_expired", documents: [{ title: "a" }, { title: "b" }] }).values.list).toBe("a، b");
    expect(blockerMessage({ code: "bid_bond_not_issued" })).toEqual({ key: "tenders.blockers.bid_bond_not_issued", values: {} });
  });
});

describe("envelope progress", () => {
  it("is complete only when every item of a non-empty envelope is ready", () => {
    expect(progressText([3, 3])).toEqual({ done: 3, total: 3, complete: true });
    expect(progressText([2, 3]).complete).toBe(false);
    expect(progressText([0, 0]).complete).toBe(false);
  });
});

describe("reminder days typed by the owner", () => {
  it("accepts Persian digits and separators, dedupes and sorts largest first", () => {
    expect(parseReminderDays("۳، ۱")).toEqual([3, 1]);
    expect(parseReminderDays("1, 7 3 7")).toEqual([7, 3, 1]);
    expect(parseReminderDays("")).toEqual([]);
    expect(parseReminderDays("0")).toEqual([0]);
  });
  it("rejects non-numbers, out-of-range values and too many entries", () => {
    expect(parseReminderDays("3، x")).toBeNull();
    expect(parseReminderDays("-1")).toBeNull();
    expect(parseReminderDays("400")).toBeNull();
    expect(parseReminderDays("1.5")).toBeNull();
    expect(parseReminderDays("1 2 3 4 5 6 7 8 9 10 11")).toBeNull();
  });
});

describe("date and time of a tender date", () => {
  it("combines the picked day with a typed time in the PC's zone", () => {
    const iso = combineDateTime(new Date(2026, 10, 5), "۱۴:۳۰");
    expect(iso).not.toBeNull();
    const d = new Date(iso!);
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()]).toEqual([2026, 10, 5, 14, 30]);
    expect(timeOf(iso!)).toBe("14:30");
    expect(timeOf(combineDateTime(new Date(2026, 0, 1), "9")!)).toBe("09:00");
  });
  it("rejects invalid times", () => {
    expect(combineDateTime(new Date(), "24:00")).toBeNull();
    expect(combineDateTime(new Date(), "12:60")).toBeNull();
    expect(combineDateTime(new Date(), "noon")).toBeNull();
  });
});

describe("guarantee steps", () => {
  it("offers sensible next steps and none from a closed status", () => {
    expect(nextGuaranteeSteps("to_request")).toContain("requested");
    expect(nextGuaranteeSteps("issued")).toContain("released");
    expect(nextGuaranteeSteps("released")).toEqual([]);
  });
});
