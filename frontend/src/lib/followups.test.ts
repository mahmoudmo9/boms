import { describe, expect, it } from "vitest";

import { canSaveQuickLog, fromDateString, quickDueDate, type QuickLogForm, toDateString } from "./followups";

describe("quick due-date buttons", () => {
  it("adds 1, 3 and 7 calendar days", () => {
    const today = new Date(2026, 9, 25, 15, 0);
    expect(quickDueDate(today, "tomorrow")).toBe("2026-10-26");
    expect(quickDueDate(today, "3days")).toBe("2026-10-28");
    expect(quickDueDate(today, "week")).toBe("2026-11-01");
  });
  it("crosses month and year ends", () => {
    expect(quickDueDate(new Date(2026, 11, 30), "3days")).toBe("2027-01-02");
    expect(quickDueDate(new Date(2028, 1, 28), "tomorrow")).toBe("2028-02-29");
  });
  it("uses the local date even late in the evening", () => {
    expect(quickDueDate(new Date(2026, 9, 25, 23, 59), "tomorrow")).toBe("2026-10-26");
    expect(toDateString(new Date(2026, 0, 5, 0, 1))).toBe("2026-01-05");
  });
  it("round-trips date strings", () => {
    expect(toDateString(fromDateString("2026-03-21"))).toBe("2026-03-21");
  });
});

describe("quick-log Save rule", () => {
  const base: QuickLogForm = {
    partyId: "p1",
    channel: "whatsapp",
    direction: "in",
    occurredAt: new Date(),
    followupAction: "",
    followupDue: null,
    noFollowup: false,
    noFollowupReason: "",
  };

  it("is disabled until a next action or a no-follow-up reason is given", () => {
    expect(canSaveQuickLog(base)).toBe(false);
    expect(canSaveQuickLog({ ...base, followupAction: "Call back" })).toBe(false);
    expect(canSaveQuickLog({ ...base, followupAction: "  ", followupDue: "2026-10-26" })).toBe(false);
    expect(canSaveQuickLog({ ...base, followupAction: "Call back", followupDue: "2026-10-26" })).toBe(true);
  });
  it("accepts 'no follow-up' only with a reason", () => {
    expect(canSaveQuickLog({ ...base, noFollowup: true })).toBe(false);
    expect(canSaveQuickLog({ ...base, noFollowup: true, noFollowupReason: "   " })).toBe(false);
    expect(canSaveQuickLog({ ...base, noFollowup: true, noFollowupReason: "deal closed" })).toBe(true);
  });
  it("ignores a typed action when 'no follow-up' is chosen (exactly one path is sent)", () => {
    expect(canSaveQuickLog({ ...base, noFollowup: true, followupAction: "x", followupDue: "2026-10-26" })).toBe(false);
  });
  it("needs a party, channel, direction and time", () => {
    const ok = { ...base, followupAction: "a", followupDue: "2026-10-26" };
    expect(canSaveQuickLog({ ...ok, partyId: null })).toBe(false);
    expect(canSaveQuickLog({ ...ok, channel: "" })).toBe(false);
    expect(canSaveQuickLog({ ...ok, occurredAt: null })).toBe(false);
  });
});
