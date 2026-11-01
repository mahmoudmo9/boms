/** Tender tab helpers (v0.6.0, pure and unit-tested): the stepper, blockers as messages, envelope progress text,
 * reminder days typed by the owner, and which guarantee steps make sense next. */
import type { Blocker, TenderStage } from "./types";

export const STAGES: TenderStage[] = ["screening", "documents", "pricing", "guarantee", "envelopes", "submitted", "opening", "result", "closed"];

/** Stepper rows: done / current / hint (the furthest sensible stage from the data, shown only as a hint). */
export function stepper(stage: TenderStage, hint: TenderStage) {
  const at = STAGES.indexOf(stage);
  const hintAt = STAGES.indexOf(hint);
  return STAGES.map((s, i) => ({ stage: s, state: i < at ? "done" as const : i === at ? "current" as const : "todo" as const,
    hinted: i === hintAt && hintAt > at }));
}

/** i18n key + values of a blocker (all blockers are listed together). */
export function blockerMessage(b: Blocker): { key: string; values: Record<string, string | number> } {
  switch (b.code) {
    case "envelopes_incomplete": {
      const env = (b.envelopes ?? {}) as Record<string, number>;
      return { key: "tenders.blockers.envelopes_incomplete", values: { list: Object.entries(env).map(([e, n]) => `${e}: ${n}`).join("، ") } };
    }
    case "guarantee_validity_short":
      return { key: "tenders.blockers.guarantee_validity_short", values: { valid: String(b.valid_until), needed: String(b.needed_until) } };
    case "company_document_expired":
      return { key: "tenders.blockers.company_document_expired", values: { list: ((b.documents ?? []) as { title: string }[]).map((d) => d.title).join("، ") } };
    default:
      return { key: `tenders.blockers.${b.code}`, values: {} };
  }
}

/** "7 of 11" per envelope and in total; ``complete`` when every item is ready or submitted. */
export function progressText(p: [number, number]): { done: number; total: number; complete: boolean } {
  return { done: p[0], total: p[1], complete: p[1] > 0 && p[0] === p[1] };
}

/** Reminder days as typed («3، 1» or "7, 3 1"): whole days 0..365, distinct, largest first; null when invalid. */
export function parseReminderDays(text: string): number[] | null {
  const latin = text.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
  const parts = latin.split(/[\s,،؛;]+/).filter(Boolean);
  const out: number[] = [];
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const n = Number(p);
    if (n > 365) return null;
    if (!out.includes(n)) out.push(n);
  }
  return out.length > 10 ? null : out.sort((a, b) => b - a);
}

const NEXT: Record<string, string[]> = {
  to_request: ["requested", "issued", "cancelled"],
  requested: ["issued", "cancelled"],
  issued: ["ready_to_upload", "submitted", "extended", "released", "claimed"],
  ready_to_upload: ["submitted", "extended", "released", "claimed"],
  submitted: ["extended", "released", "claimed"],
  extended: ["submitted", "extended", "released", "claimed"],
};

/** The guarantee steps offered from a status (the server accepts any open step; these are the sensible ones). */
export function nextGuaranteeSteps(status: string): string[] {
  return NEXT[status] ?? [];
}

/** A day picked in the user's calendar plus a typed time ("14:30") -> ISO timestamp (the PC's own zone). */
export function combineDateTime(day: Date, time: string): string | null {
  const m = time.trim().replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).match(/^(\d{1,2})(?::(\d{2}))?$/);
  if (!m) return null;
  const h = Number(m[1]); const mi = Number(m[2] ?? 0);
  if (h > 23 || mi > 59) return null;
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, mi).toISOString();
}

export function timeOf(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
