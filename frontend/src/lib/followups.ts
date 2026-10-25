/** Pure helpers for follow-ups and the quick-log form (unit-tested). */

export type QuickDue = "tomorrow" | "3days" | "week";

const pad = (n: number) => String(n).padStart(2, "0");

/** Local calendar date -> "YYYY-MM-DD" (never via UTC, so late evenings do not jump a day). */
export function toDateString(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** "YYYY-MM-DD" -> Date at local midnight. */
export function fromDateString(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function quickDueDate(today: Date, kind: QuickDue): string {
  const days = kind === "tomorrow" ? 1 : kind === "3days" ? 3 : 7;
  return toDateString(new Date(today.getFullYear(), today.getMonth(), today.getDate() + days));
}

export interface QuickLogForm {
  partyId: string | null;
  channel: string;
  direction: string;
  occurredAt: Date | null;
  followupAction: string;
  followupDue: string | null;
  noFollowup: boolean;
  noFollowupReason: string;
}

/** Save is allowed only with a party, channel, direction, time and exactly one next-action path. */
export function canSaveQuickLog(form: QuickLogForm): boolean {
  if (!form.partyId || !form.channel || !form.direction || !form.occurredAt) return false;
  if (form.noFollowup) return form.noFollowupReason.trim().length > 0;
  return form.followupAction.trim().length > 0 && !!form.followupDue;
}
