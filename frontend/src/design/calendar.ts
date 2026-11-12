/** Month grids for the DatePicker in both calendars (pure; tested without a browser). Weeks start on Saturday in the
 * Jalali calendar and on Monday in the Gregorian one. Dates are local-midnight `Date`s. */
import { addMonths as addJalaliMonths, getDate as jDate, getDaysInMonth as jDaysInMonth, getMonth as jMonth, getYear as jYear,
  startOfMonth as jStartOfMonth } from "date-fns-jalali";

export type CalendarKind = "jalali" | "gregorian";
export type Cell = { date: Date; day: number; inMonth: boolean };

const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const sameDay = (a: Date | null | undefined, b: Date | null | undefined) =>
  Boolean(a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate());

export function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

export function monthStart(d: Date, kind: CalendarKind): Date {
  return kind === "jalali" ? midnight(jStartOfMonth(d)) : new Date(d.getFullYear(), d.getMonth(), 1);
}

export function addMonths(d: Date, n: number, kind: CalendarKind): Date {
  return kind === "jalali" ? midnight(addJalaliMonths(d, n)) : new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), 28));
}

export function dayOfMonth(d: Date, kind: CalendarKind): number {
  return kind === "jalali" ? jDate(d) : d.getDate();
}

/** [year, month index 0-11] of a date in the calendar. */
export function yearMonth(d: Date, kind: CalendarKind): [number, number] {
  return kind === "jalali" ? [jYear(d), jMonth(d)] : [d.getFullYear(), d.getMonth()];
}

/** First weekday column: Saturday (6) for Jalali, Monday (1) for Gregorian. */
export function weekStart(kind: CalendarKind): number {
  return kind === "jalali" ? 6 : 1;
}

/** Weekday indexes (0 = Sunday) in column order. */
export function weekdays(kind: CalendarKind): number[] {
  return Array.from({ length: 7 }, (_, i) => (weekStart(kind) + i) % 7);
}

/** Six weeks of cells covering the month of `anchor`, padded with the days of the neighbouring months. */
export function monthGrid(anchor: Date, kind: CalendarKind): Cell[][] {
  const first = monthStart(anchor, kind);
  const days = kind === "jalali" ? jDaysInMonth(first) : new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const lead = (first.getDay() - weekStart(kind) + 7) % 7;
  const cells: Cell[] = Array.from({ length: 42 }, (_, i) => {
    const date = addDays(first, i - lead);
    return { date, day: dayOfMonth(date, kind), inMonth: i >= lead && i < lead + days };
  });
  return Array.from({ length: 6 }, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/** Keyboard movement in the grid (the directions are logical: «next day» is ArrowLeft in RTL). */
export function moveFocus(d: Date, key: string, kind: CalendarKind, rtl: boolean): Date | null {
  const forward = rtl ? "ArrowLeft" : "ArrowRight", back = rtl ? "ArrowRight" : "ArrowLeft";
  switch (key) {
    case forward: return addDays(d, 1);
    case back: return addDays(d, -1);
    case "ArrowDown": return addDays(d, 7);
    case "ArrowUp": return addDays(d, -7);
    case "PageDown": return addMonths(d, 1, kind);
    case "PageUp": return addMonths(d, -1, kind);
    case "Home": return addDays(d, -((d.getDay() - weekStart(kind) + 7) % 7));
    case "End": return addDays(d, 6 - ((d.getDay() - weekStart(kind) + 7) % 7));
    default: return null;
  }
}
