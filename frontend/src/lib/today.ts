/** The command center's «most important now» and «today's timeline» (v0.10.0, reference ProToday), from the
 * command-center data only. Pure, tested without a browser. */
import type { TaskRow } from "./tasks";
import type { CommandCenter } from "./types";

export type Moment = {
  key: string;
  kind: "tender" | "setad" | "task" | "followup" | "step" | "quote";
  /** ISO date-time of the deadline; a date-only item is due at the end of its day. */
  at: string;
  title: string;
  detail?: string | null;
  link: string;
  /** Only a time of day was not given (date-only). */
  allDay: boolean;
  priority: number;
};

export type Overview = {
  profit_quarter: { gregorian: PeriodProfit; jalali: PeriodProfit & { year: number; season: number } };
  win_rate: { won: number; decided: number; percent: number | null; months: { month: string; won: number; lost: number }[] };
  tied_up: { cases: number; by_currency: { currency: string; amount: string }[] };
  setad_today: { count: number; keywords: { keyword: string; count: number }[] };
  cash_flow: { from: string; days: number; currencies: CashCurrency[]; overdue: { currency: string; in: string; out: string }[]; undated: number };
};
export type PeriodProfit = { from: string; to: string; deals: number; by_currency: { currency: string; profit: string }[] };
export type CashCurrency = { currency: string; weeks: { week: string; in: string; out: string; net: string }[]; lowest_week: number | null; total_in: string; total_out: string };

/** End of a date-only day in local time. */
export function endOfDay(day: string): Date {
  const [y, m, d] = day.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d, 23, 59, 59);
}

const iso = (d: Date) => d.toISOString();
const name = (fa: string | null | undefined, en: string | null | undefined, lang: string) => (lang === "fa" ? fa || en : en || fa) ?? "";

/** Every dated thing of the command center, as moments. */
export function moments(cc: CommandCenter, lang: string): Moment[] {
  const out: Moment[] = [];
  for (const r of cc.tenders?.dates_soon ?? []) {
    out.push({ key: `tender-${r.tender_id}-${r.kind}-${r.at}`, kind: "tender", at: r.at, title: r.case_title, detail: r.kind, link: `/cases/${r.case_id}?tab=tender`,
      allDay: false, priority: r.kind === "proposal" || r.kind === "submission" ? 0 : 1 });
  }
  for (const r of cc.setad?.due ?? []) {
    out.push({ key: `setad-${r.id}`, kind: "setad", at: r.deadline, title: r.title, detail: r.organization,
      link: r.inquiry_id ? `/sourcing/inquiries/${r.inquiry_id}` : `/tenders?source=${r.source}&include_old=1&listing=${r.id}`, allDay: false, priority: 1 });
  }
  const tasks: TaskRow[] = [...(cc.tasks?.overdue ?? []), ...(cc.tasks?.today ?? []), ...(cc.tasks?.tomorrow ?? [])];
  for (const r of tasks) {
    out.push({ key: `task-${r.id}`, kind: "task", at: r.due_at ?? iso(endOfDay(r.due_on)), title: r.title, detail: r.case_title ?? null,
      link: r.case_id ? `/cases/${r.case_id}?tab=tasks` : "/tasks", allDay: !r.due_at, priority: r.priority === "high" ? 0 : 2 });
  }
  for (const r of [...cc.overdue, ...cc.today]) {
    out.push({ key: `followup-${r.id}`, kind: "followup", at: iso(endOfDay(r.due_on)), title: r.action, detail: name(r.party_name_fa, r.party_name_en, lang),
      link: `/parties/${r.party_id}`, allDay: true, priority: 2 });
  }
  for (const r of cc.execution?.steps_due ?? []) {
    out.push({ key: `step-${r.step_id}`, kind: "step", at: iso(endOfDay(r.due_on)), title: lang === "fa" ? r.label_fa : r.label_en, detail: r.case_title,
      link: `/cases/${r.case_id}?tab=logistics`, allDay: true, priority: 2 });
  }
  for (const r of cc.sourcing.quotes_expiring ?? []) {
    out.push({ key: `quote-${r.quote_id}`, kind: "quote", at: iso(endOfDay(r.valid_until)), title: r.number, detail: r.case_title,
      link: `/cases/${r.case_id}?tab=quotes&quote=${r.quote_id}`, allDay: true, priority: 2 });
  }
  return out;
}

export const FOCUS_WINDOW_HOURS = 72;

/** The most important thing now: the soonest deadline still ahead within 72 h (a tender date or a high-priority task
 * first when two fall on the same hour); if nothing is ahead, the most recently passed one. */
export function focus(items: Moment[], now: Date): Moment | null {
  const t = now.getTime();
  const ahead = items.filter((m) => new Date(m.at).getTime() >= t && new Date(m.at).getTime() - t <= FOCUS_WINDOW_HOURS * 3600_000);
  const byTime = (a: Moment, b: Moment) => {
    const ha = Math.floor(new Date(a.at).getTime() / 3600_000), hb = Math.floor(new Date(b.at).getTime() / 3600_000);
    return ha - hb || a.priority - b.priority || a.key.localeCompare(b.key);
  };
  if (ahead.length) return [...ahead].sort(byTime)[0];
  const passed = items.filter((m) => new Date(m.at).getTime() < t);
  return passed.length ? [...passed].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime() || a.priority - b.priority)[0] : null;
}

/** Share of the 72-hour window still left (0..100); 0 once passed. */
export function timeLeftPercent(m: Moment, now: Date): number {
  const left = new Date(m.at).getTime() - now.getTime();
  return Math.max(0, Math.min(100, (left / (FOCUS_WINDOW_HOURS * 3600_000)) * 100));
}

/** Today's moments in time order, each marked passed / next / later relative to now. */
export function todayLine(items: Moment[], now: Date): (Moment & { state: "done" | "current" | "upcoming" })[] {
  const day = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const today = items.filter((m) => day(new Date(m.at)) === day(now)).sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  let current = false;
  return today.map((m) => {
    const passed = new Date(m.at).getTime() < now.getTime();
    if (passed) return { ...m, state: "done" as const };
    if (!current) { current = true; return { ...m, state: "current" as const }; }
    return { ...m, state: "upcoming" as const };
  });
}

/** The currency to show first in the cash flow: the one with the most money moving. */
export function mainCurrency(cf: Overview["cash_flow"]): string | null {
  return cf.currencies[0]?.currency ?? null;
}
