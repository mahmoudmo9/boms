/** Execution helpers (v0.7.0, pure and unit-tested): delivery progress, the cash position display, the process
 * stepper (groups of steps with their state), statuses and tones. */
import type { CashPosition, ProcessStepRow } from "./types";

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

/** «۳۰ از ۸۸ تحویل شد»: numbers for one item (strings from the API, decimals allowed). */
export function itemProgress(ordered: string, delivered: string): { done: number; total: number; complete: boolean; percent: number } {
  const total = Number(ordered) || 0;
  const done = Number(delivered) || 0;
  return { done, total, complete: total > 0 && done >= total, percent: total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0 };
}

/** «۲ از ۳ قلم»: items fully delivered out of all items. */
export function orderProgress(items: { quantity: string; delivered: string }[]): { done: number; total: number; complete: boolean } {
  const done = items.filter((i) => itemProgress(i.quantity, i.delivered).complete).length;
  return { done, total: items.length, complete: items.length > 0 && done === items.length };
}

export interface CashRow { currency: string; received: string; paid: string; net: string; tone: Tone; outstandingIn: string; outstandingOut: string }

/** One row per currency: received, paid, the net cash tied up now (positive = our money in the deal: warning), and
 * what is still expected in and out. Currencies of both actual and outstanding, sorted. */
export function cashRows(cash: CashPosition | null | undefined): CashRow[] {
  if (!cash) return [];
  const currencies = [...new Set([...Object.keys(cash.actual ?? {}), ...Object.keys(cash.outstanding ?? {})])].sort();
  return currencies.map((currency) => {
    const a = cash.actual?.[currency];
    const o = cash.outstanding?.[currency];
    const net = a?.net_tied_up ?? "0";
    const n = Number(net);
    return { currency, received: a?.received ?? "0", paid: a?.paid ?? "0", net, tone: n > 0 ? "warning" : n < 0 ? "success" : "neutral",
      outstandingIn: o?.in ?? "0", outstandingOut: o?.out ?? "0" };
  });
}

export type StepState = "done" | "na" | "current" | "overdue" | "todo";

/** The state of one step for the stepper: done / not applicable / in progress (current) / overdue / to do. */
export function stepState(step: Pick<ProcessStepRow, "status" | "due_on">, today: string): StepState {
  if (step.status === "done") return "done";
  if (step.status === "not_applicable") return "na";
  if (step.due_on && step.due_on < today) return "overdue";
  if (step.status === "in_progress") return "current";
  return "todo";
}

/** Steps grouped as the template defines them (in order), with counts per group. */
export function stepGroups<T extends Pick<ProcessStepRow, "group" | "status" | "position">>(steps: T[]): { group: string; steps: T[]; done: number }[] {
  const out: { group: string; steps: T[]; done: number }[] = [];
  for (const s of [...steps].sort((a, b) => a.position - b.position)) {
    const key = s.group ?? "";
    let g = out.find((x) => x.group === key);
    if (!g) { g = { group: key, steps: [], done: 0 }; out.push(g); }
    g.steps.push(s);
    if (s.status === "done" || s.status === "not_applicable") g.done += 1;
  }
  return out;
}

export const STEP_TONE: Record<StepState, Tone> = { done: "success", na: "neutral", current: "accent", overdue: "danger", todo: "neutral" };

export const SO_TONE: Record<string, Tone> = { draft: "warning", confirmed: "accent", in_progress: "accent", delivered: "success", closed: "neutral", cancelled: "neutral" };
export const PO_TONE: Record<string, Tone> = { draft: "warning", approved: "accent", sent: "accent", confirmed: "accent", in_production: "accent",
  ready: "success", shipped: "success", received: "success", closed: "neutral", cancelled: "neutral", superseded: "neutral" };
export const MILESTONE_TONE: Record<string, Tone> = { expected: "warning", partly: "accent", done: "success", cancelled: "neutral" };
export const CLAIM_TONE: Record<string, Tone> = { open: "danger", submitted: "warning", negotiating: "warning", resolved: "success", rejected: "neutral", withdrawn: "neutral" };

/** The next statuses a PO can be moved to by hand (BOMS sets the others). */
export function manualPoSteps(status: string): string[] {
  return ({ confirmed: ["in_production", "ready", "shipped"], in_production: ["ready", "shipped"], ready: ["shipped", "closed"],
    shipped: ["closed"], received: ["closed"] } as Record<string, string[]>)[status] ?? [];
}

/** Containers typed as "MSCU1234567, TGHU7654321" or one per line -> a clean list. */
export function parseContainers(text: string): string[] {
  return [...new Set(text.split(/[\s,،;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean))];
}
