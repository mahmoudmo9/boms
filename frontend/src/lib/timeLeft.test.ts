import { describe, expect, it } from "vitest";

import { stripRemainingRemark, timeLeft, timeLeftMessage } from "./timeLeft";

const now = new Date("2026-11-01T10:00:00Z");
const at = (ms: number) => new Date(now.getTime() + ms).toISOString();
const H = 3_600_000;
const M = 60_000;

describe("time left at the precision that matters", () => {
  it("3 days 5 hours: whole days from the exact time", () => {
    const tl = timeLeft(at(3 * 24 * H + 5 * H), now)!;
    expect([tl.kind, tl.days, tl.tone]).toEqual(["days", 3, "success"]);
    expect(timeLeftMessage(tl)).toEqual({ key: "time.left.days", values: { count: 3, d: 3, h: 5, m: 0 } });
  });
  it("1 day 21 hours: days and hours", () => {
    const tl = timeLeft(at(45 * H), now)!;
    expect([tl.kind, tl.days, tl.hours, tl.tone]).toEqual(["daysHours", 1, 21, "warning"]);
  });
  it("5 hours 10 minutes: hours and minutes in red", () => {
    const tl = timeLeft(at(5 * H + 10 * M), now)!;
    expect([tl.kind, tl.hours, tl.minutes, tl.tone]).toEqual(["hoursMinutes", 5, 10, "danger"]);
  });
  it("40 minutes", () => {
    const tl = timeLeft(at(40 * M + 20_000), now)!;
    expect([tl.kind, tl.minutes]).toEqual(["minutes", 40]);
  });
  it("passed 2 hours ago", () => {
    const tl = timeLeft(at(-2 * H - 5 * M), now)!;
    expect(tl.kind).toBe("passed");
    expect(timeLeftMessage(tl)).toEqual({ key: "time.passedAgo.hours", values: { count: 2, n: 2 } });
    expect(timeLeft(at(-3 * 24 * H), now)!.ago).toEqual({ unit: "days", n: 3 });
    expect(timeLeft(at(-20 * M), now)!.ago).toEqual({ unit: "minutes", n: 20 });
  });
  it("the list's estimate is marked; no deadline gives nothing", () => {
    expect(timeLeft(at(10 * H), now, true)!.estimate).toBe(true);
    expect(timeLeft(null, now)).toBeNull();
  });
  it("the day count uses the exact time, not a calendar difference", () => {
    // 1 day 23 h is "1 day 23 hours", even when the date is two calendar days later
    expect(timeLeft("2026-11-03T09:00:00Z", now)!.kind).toBe("daysHours");
  });
});

describe("site remark", () => {
  it("removes «(باقی‌مانده هنگام دریافت: …)» from a deadline", () => {
    expect(stripRemainingRemark("1405/08/06 - 10:03 (باقی‌مانده هنگام دریافت: 14 روز و 1 ساعت)")).toBe("1405/08/06 - 10:03");
    expect(stripRemainingRemark("1405/08/06 (باقیمانده: ۲ روز)")).toBe("1405/08/06");
    expect(stripRemainingRemark("بدون توضیح")).toBe("بدون توضیح");
  });
});
