/** Internal tasks (v0.8.0): the owner's own reminders, not follow-ups with a party. */
export const TASK_GROUPS = ["overdue", "today", "week", "later", "done"] as const;
export type TaskGroup = (typeof TASK_GROUPS)[number];

export const TASK_KINDS = ["tender_date", "process_step", "guarantee_expiry", "warranty_end", "warranty_remind", "opening",
  "contract", "invoice_issue", "manual"] as const;

export interface TaskRow {
  id: string;
  title: string;
  due_on: string;
  due_at: string | null;
  status: "open" | "done" | "cancelled";
  done_at: string | null;
  done_note: string | null;
  priority: "normal" | "high";
  case_id: string | null;
  case_title?: string | null;
  party_id: string | null;
  source: string;
  source_kind: string;
  source_id: string | null;
  remind_of_due: string | null;
  remind_days_before: number | null;
  notes: string | null;
}

export interface TasksResponse {
  today: string;
  groups: Record<TaskGroup, TaskRow[]>;
  counts: Record<TaskGroup, number>;
  kinds: string[];
}

export interface TasksSummary {
  overdue: TaskRow[];
  today: TaskRow[];
  tomorrow: TaskRow[];
}

/** Where a task's source lives in the case page (null when it has no case). */
export function taskLink(task: Pick<TaskRow, "case_id" | "source_kind">): string | null {
  if (!task.case_id) return null;
  const tab: Record<string, string> = {
    tender_date: "tender", opening: "tender", contract: "tender", guarantee_expiry: "tender",
    process_step: "order", invoice_issue: "delivery", warranty_end: "delivery", warranty_remind: "delivery",
  };
  return `/cases/${task.case_id}?tab=${tab[task.source_kind] ?? "tasks"}`;
}

/** The moment a task reminds about, when it differs from its own due date (for the time-left helper; a date-only
 * value counts to the end of that day, as process steps do). */
export function remindsOf(task: Pick<TaskRow, "remind_of_due" | "due_on" | "due_at">): string | null {
  if (task.due_at) return task.due_at;
  return task.remind_of_due && task.remind_of_due !== task.due_on ? `${task.remind_of_due}T23:59:00` : null;
}

/** The «کارهای من» groups (the server's rule, used for a task added or moved before the list reloads): overdue,
 * today, this week (next 7 days), later; done and cancelled together. */
export function groupTasks<T extends Pick<TaskRow, "status" | "due_on">>(rows: T[], today: string): Record<TaskGroup, T[]> {
  const out: Record<TaskGroup, T[]> = { overdue: [], today: [], week: [], later: [], done: [] };
  const week = new Date(Date.parse(`${today}T00:00:00Z`) + 7 * 86_400_000).toISOString().slice(0, 10);
  for (const r of rows) {
    if (r.status !== "open") out.done.push(r);
    else if (r.due_on < today) out.overdue.push(r);
    else if (r.due_on === today) out.today.push(r);
    else if (r.due_on <= week) out.week.push(r);
    else out.later.push(r);
  }
  return out;
}
