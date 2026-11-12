/** v0.10.0 DatePicker grids: both calendars, week starts, padding, keyboard movement. */
import { describe, expect, it } from "vitest";

import { addMonths, monthGrid, moveFocus, sameDay, weekdays, yearMonth } from "./calendar";

const d = (y: number, m: number, day: number) => new Date(y, m - 1, day);

describe("month grid", () => {
  it("Gregorian: November 2026 starts on a Sunday, weeks start on Monday", () => {
    const grid = monthGrid(d(2026, 11, 12), "gregorian");
    expect(weekdays("gregorian")).toEqual([1, 2, 3, 4, 5, 6, 0]);
    expect(grid).toHaveLength(6);
    expect(grid[0].map((c) => c.day)).toEqual([26, 27, 28, 29, 30, 31, 1]);
    expect(grid[0].map((c) => c.inMonth)).toEqual([false, false, false, false, false, false, true]);
    expect(grid.flat().filter((c) => c.inMonth)).toHaveLength(30);
  });
  it("Jalali: Aban 1405 (23 Oct - 21 Nov 2026) has 30 days, weeks start on Saturday", () => {
    const grid = monthGrid(d(2026, 11, 12), "jalali");
    expect(weekdays("jalali")).toEqual([6, 0, 1, 2, 3, 4, 5]);
    const inMonth = grid.flat().filter((c) => c.inMonth);
    expect(inMonth).toHaveLength(30);
    expect(sameDay(inMonth[0].date, d(2026, 10, 23))).toBe(true);
    expect(inMonth[0].day).toBe(1);
    expect(sameDay(inMonth[29].date, d(2026, 11, 21))).toBe(true);
    expect(yearMonth(d(2026, 11, 12), "jalali")).toEqual([1405, 7]);
    expect(grid[0][0].date.getDay()).toBe(6);
  });
  it("Esfand of a common Jalali year has 29 days, of a leap year 30", () => {
    expect(monthGrid(d(2027, 3, 1), "jalali").flat().filter((c) => c.inMonth)).toHaveLength(29);     // Esfand 1405
    expect(monthGrid(d(2025, 3, 1), "jalali").flat().filter((c) => c.inMonth)).toHaveLength(30);     // Esfand 1403 (leap)
  });
});

describe("keyboard movement", () => {
  const day = d(2026, 11, 12);       // a Thursday
  it("arrows are logical: the next day is ArrowLeft in RTL", () => {
    expect(sameDay(moveFocus(day, "ArrowLeft", "jalali", true), d(2026, 11, 13))).toBe(true);
    expect(sameDay(moveFocus(day, "ArrowRight", "jalali", true), d(2026, 11, 11))).toBe(true);
    expect(sameDay(moveFocus(day, "ArrowRight", "gregorian", false), d(2026, 11, 13))).toBe(true);
    expect(sameDay(moveFocus(day, "ArrowDown", "gregorian", false), d(2026, 11, 19))).toBe(true);
    expect(sameDay(moveFocus(day, "ArrowUp", "gregorian", false), d(2026, 11, 5))).toBe(true);
  });
  it("Home and End go to the ends of the week, PageUp / PageDown change the month", () => {
    expect(sameDay(moveFocus(day, "Home", "gregorian", false), d(2026, 11, 9))).toBe(true);      // Monday
    expect(sameDay(moveFocus(day, "End", "gregorian", false), d(2026, 11, 15))).toBe(true);      // Sunday
    expect(sameDay(moveFocus(day, "Home", "jalali", true), d(2026, 11, 7))).toBe(true);          // Saturday
    expect(sameDay(moveFocus(day, "PageDown", "gregorian", false), d(2026, 12, 12))).toBe(true);
    expect(yearMonth(moveFocus(day, "PageDown", "jalali", true)!, "jalali")).toEqual([1405, 8]);
    expect(yearMonth(addMonths(day, -8, "jalali"), "jalali")).toEqual([1404, 11]);
    expect(moveFocus(day, "a", "jalali", true)).toBeNull();
  });
});
