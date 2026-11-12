/** v0.10.0 (ProFinance): the deal's cash flow on the case finance tab, from its open payment milestones — the same rule
 * as the command center's 90-day view (finance/overview.py): the expected amount less what was already received or
 * paid; overdue and undated milestones are counted beside the chart, not in it. Grouped by due month and currency. */
import type { CashPoint } from "../design/charts";
import type { MilestoneRow } from "./types";

export type DealCash = { currency: string; points: CashPoint[]; totalIn: number; totalOut: number; overdueIn: number; overdueOut: number };
export type DealCashFlow = { currencies: DealCash[]; undated: number };

const OPEN = new Set(["expected", "partly"]);

export function openAmount(m: MilestoneRow): number {
  const expected = Number(m.expected_amount);
  const paid = m.actual_amount && (!m.actual_amount_currency || m.actual_amount_currency === m.expected_currency) ? Number(m.actual_amount) : 0;
  return Math.max(0, expected - paid);
}

export type MonthOf = (day: string) => { key: string; label: string };

/** The month of a "YYYY-MM-DD" day in the user's calendar: a sortable key and its name ("آذر ۱۴۰۵", "December 2026"). */
export function calendarMonth(calendar: "jalali" | "gregorian", lang: "fa" | "en"): MonthOf {
  const ca = calendar === "jalali" ? "persian" : "gregory";
  const keyFmt = new Intl.DateTimeFormat(`en-u-ca-${ca}-nu-latn`, { year: "numeric", month: "2-digit", timeZone: "UTC" });
  const labelFmt = new Intl.DateTimeFormat(`${lang === "fa" ? "fa-IR" : "en-GB"}-u-ca-${ca}`, { year: "numeric", month: "long", timeZone: "UTC" });
  return (day) => {
    const [y, m, d] = day.split("-").map(Number);
    const at = new Date(Date.UTC(y, m - 1, d));
    const parts = Object.fromEntries(keyFmt.formatToParts(at).map((p) => [p.type, p.value]));
    return { key: `${parts.year.replace(/\D/g, "")}-${parts.month}`, label: labelFmt.format(at) };
  };
}

export function dealCashFlow(milestones: MilestoneRow[], today: string, month: MonthOf): DealCashFlow {
  const per = new Map<string, { months: Map<string, CashPoint>; overdueIn: number; overdueOut: number }>();
  let undated = 0;
  for (const m of milestones) {
    if (!OPEN.has(m.status) || !m.expected_currency) continue;
    const amount = openAmount(m);
    if (amount <= 0) continue;
    if (!m.due_on) { undated += 1; continue; }
    const c = per.get(m.expected_currency) ?? { months: new Map(), overdueIn: 0, overdueOut: 0 };
    per.set(m.expected_currency, c);
    if (m.due_on < today) {
      if (m.direction === "in") c.overdueIn += amount; else c.overdueOut += amount;
      continue;
    }
    const { key, label } = month(m.due_on);
    const p = c.months.get(key) ?? { key, label, cashIn: 0, cashOut: 0 };
    if (m.direction === "in") p.cashIn += amount; else p.cashOut += amount;
    c.months.set(key, p);
  }
  const currencies = [...per.entries()].map(([currency, c]) => {
    const points = [...c.months.values()].sort((a, b) => a.key.localeCompare(b.key));
    return { currency, points, totalIn: points.reduce((s, p) => s + p.cashIn, 0), totalOut: points.reduce((s, p) => s + p.cashOut, 0),
      overdueIn: c.overdueIn, overdueOut: c.overdueOut };
  });
  currencies.sort((a, b) => (b.totalIn + b.totalOut + b.overdueIn + b.overdueOut) - (a.totalIn + a.totalOut + a.overdueIn + a.overdueOut));
  return { currencies, undated };
}
