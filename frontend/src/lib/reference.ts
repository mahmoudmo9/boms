/** v0.10.1 section 0.2: reference imports with a preview — the run's shape and the progress shown while it runs. */
export type ImportPreview = {
  dataset: string; release: string | null; rows_read: number; records: number; rejected: number;
  reasons: { reason: string; count: number }[]; examples: { part: string; row: number; reason: string }[];
  encodings: Record<string, string>; parts: string[]; complete: boolean; warnings: string[]; notes: Record<string, unknown>;
  insert: number; update: number; deactivate: number; unchanged: number; chosen_other?: string;
};
export type ImportReport = Omit<ImportPreview, "insert" | "update" | "deactivate"> & { inserted: number; updated: number; deactivated: number; seconds: number };
export type ImportRun = {
  id: string; dataset: "unlocode" | "elf"; file_name: string; release: string | null;
  status: "previewing" | "preview_ready" | "preview_failed" | "importing" | "done" | "failed" | "cancelled" | "discarded";
  stage: string | null; rows_read: number; rows_total: number | null; started_at: string | null; preview: ImportPreview | null;
  report: ImportReport | null; error: string | null; cancel_requested: boolean; created_at: string; updated_at: string;
};

export const RUNNING = new Set(["previewing", "importing"]);

/** Seconds left, from the rate so far; null until there is a total and some progress. */
export function secondsLeft(run: Pick<ImportRun, "rows_read" | "rows_total" | "started_at">, now: number): number | null {
  if (!run.rows_total || !run.rows_read || !run.started_at) return null;
  const elapsed = (now - new Date(run.started_at).getTime()) / 1000;
  if (elapsed <= 0) return null;
  const left = (run.rows_total - run.rows_read) / (run.rows_read / elapsed);
  return Math.max(0, Math.round(left));
}

/** The share done (0-100) while a total is known. */
export function percentDone(run: Pick<ImportRun, "rows_read" | "rows_total">): number | null {
  return run.rows_total ? Math.min(100, Math.round((run.rows_read / run.rows_total) * 100)) : null;
}

/** «column X not found» → its translation key and value; other reasons are shown as written. */
export function reasonKey(reason: string): { key: string; value?: string } {
  const m = /^column (.+) not found$/.exec(reason);
  if (m) return { key: "reference.reasons.column", value: m[1] };
  const known: Record<string, string> = { "bad code": "badCode", "bad ELF code": "badElf", "no country code": "noCountry",
    "code repeated in the file": "repeated", "fewer than 11 columns": "columns" };
  return known[reason] ? { key: `reference.reasons.${known[reason]}` } : { key: "", value: reason };
}
