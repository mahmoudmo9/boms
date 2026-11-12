/** Live page updates (v0.10.0 section 6): what a notice of the change feed refreshes. Pure, tested without a browser.
 *
 * The feed says *what* changed (a job's status, a record's type and id, Setad file downloads, the agent's progress);
 * the open page refetches the queries that show it. Known record types and job types refresh their own query roots;
 * anything else refreshes every active query (correct, if a little more than needed). Lookups, suggestions and
 * amounts in words never depend on the feed. Notices arrive at least once: `Seen` drops repeated keys. */

export type Notice =
  | { kind: "job"; key: string; id: string; type: string; status: "queued" | "running" | "done" | "failed"; lane: string; at: string }
  | { kind: "record"; key: string; entity_type: string; entity_id: string | null; action: string; source?: string; at: string }
  | { kind: "agent"; key: string; command: string | null; listing_id: string | null; files_done: number | null; files_total: number | null;
      pages_done: number | null; pages_total: number | null; connected: boolean | null; at: string };

/** ``overflow``: a source had more changes than one read holds; the newest were sent and the rest are not named. */
export type Batch = { cursor: string; notices: Notice[]; overflow?: boolean };

/** After an overflow everything shown is refreshed, at most once per ``OVERFLOW_GAP_MS`` (the feed repeats its
 * overlap window for a few seconds, so the same burst overflows on several reads in a row). */
export const OVERFLOW_GAP_MS = 3000;
export function refreshAll(batch: Batch, lastRefresh: number, now: number): boolean {
  return !!batch.overflow && now - lastRefresh >= OVERFLOW_GAP_MS;
}

/** Query roots that never follow the feed. */
export const NEVER = new Set(["lookup", "words", "search", "suggest", "calc"]);

const LISTING = ["listings", "listing", "setad-agent", "setad-run", "setad-origin", "tender-by-listing", "listing-convert", "command-center"];
const CASE = ["case", "cases", "command-center", "case-tasks", "tasks", "events"];

/** Record type -> query roots it shows up in. */
export const RECORD_ROOTS: Record<string, string[]> = {
  listing: LISTING,
  harvest_run: ["listings", "setad-run", "setad-agent", "command-center"],
  setad_agent: ["setad-agent", "listings"],
  party: ["parties", "party", "contacts", "funnel", "interactions", "command-center", "party-finance", "party-execution", "ratings"],
  contact: ["contacts", "party", "parties"],
  interaction: ["interactions", "interaction", "party", "parties", "command-center"],
  followup: ["parties", "party", "command-center", "tasks", "funnel"],
  task: ["tasks", "case-tasks", "command-center", "case"],
  case: CASE,
  inquiry: ["inquiry", "inquiries", "sourcing", "command-center", "case"],
  line_item: ["inquiry", "case", "coverage", "comparison", "offers", "sourcing"],
  rfq: ["rfqs", "case", "inquiry", "sourcing", "command-center"],
  offer: ["offers", "comparison", "coverage", "case", "sourcing"],
  product: ["products", "product-templates"],
  cost_sheet: ["cost-sheets", "cost-sheet", "costing", "case"],
  quote: ["quotes", "quote", "case-quotes", "case", "command-center"],
  document: ["documents", "document", "document-text", "case", "folders", "company-documents"],
  ai_draft: ["ai", "case", "inquiry", "offers", "party"],
  ai_provider: ["ai"], ai_route: ["ai"],
  backup_run: ["system"], job: ["system"],
  sales_order: ["execution", "case", "fin", "finance", "command-center"],
  purchase_order: ["execution", "case", "fin", "finance", "command-center"],
  shipment: ["execution", "case", "command-center"],
  setting: ["settings"], app_user: ["settings"], reference: ["reference"], codes: ["codes"], basedata: ["basedata"],
};

/** Job type -> query roots (any job also refreshes the system page). */
export const JOB_ROOTS: Record<string, string[]> = {
  "backup.run": ["system"], "backup.restore_test": ["system"],
  "ai.task": ["ai", "case", "inquiry", "offers", "party"], "ai.purge_log": ["ai"],
  "documents.extract_text": ["documents", "document", "document-text", "case"],
  "folders.sync": ["folders"],
  "quotes.expire": ["quotes", "quote", "case-quotes", "case", "command-center"],
  "sourcing.expire": ["offers", "rfqs", "case", "sourcing", "command-center"],
  "execution.claim_followups": ["execution", "case", "tasks", "command-center"],
};

/** The query roots one batch refreshes; `"*"` means every active query (an unknown type). */
export function rootsFor(notices: Notice[]): Set<string> {
  const out = new Set<string>();
  for (const n of notices) {
    if (n.kind === "agent") { ["setad-agent", "listing"].forEach((r) => out.add(r)); continue; }
    if (n.kind === "job") {
      out.add("system");
      if (n.status === "done" || n.status === "failed") (JOB_ROOTS[n.type] ?? ["*"]).forEach((r) => out.add(r));
      continue;
    }
    (RECORD_ROOTS[n.entity_type] ?? ["*"]).forEach((r) => out.add(r));
  }
  return out;
}

/** Whether a query (by its key) is refreshed by these roots. */
export function matches(queryKey: readonly unknown[], roots: Set<string>): boolean {
  const root = String(queryKey[0] ?? "");
  if (NEVER.has(root)) return false;
  return roots.has("*") || roots.has(root);
}

/** Remembers the keys already handled (bounded), so a notice repeated by the overlap window is dropped. */
export class Seen {
  private keys = new Set<string>();
  constructor(private readonly max = 2000) {}
  /** The notices not seen before (and remembers them). */
  fresh(notices: Notice[]): Notice[] {
    const out = notices.filter((n) => !this.keys.has(n.key));
    for (const n of out) {
      this.keys.add(n.key);
      if (this.keys.size > this.max) this.keys.delete(this.keys.values().next().value as string);
    }
    return out;
  }
}

/** The last known state of jobs (for buttons that started one), from the notices. */
export function jobStates(prev: Record<string, Notice & { kind: "job" }>, notices: Notice[]): Record<string, Notice & { kind: "job" }> {
  let next = prev;
  for (const n of notices) {
    if (n.kind !== "job") continue;
    const old = next[n.id];
    if (old && old.at > n.at) continue;
    if (next === prev) next = { ...prev };
    next[n.id] = n;
  }
  return next;
}

export type Transport = "stream" | "polling" | "offline";

/** After this many stream errors without a message in between, the browser falls back to polling. */
export const STREAM_FAILURES_BEFORE_POLLING = 3;
export const POLL_MS = 2000;

/** Next transport after a stream error, given the failures so far. */
export function afterStreamError(failures: number): Transport {
  return failures >= STREAM_FAILURES_BEFORE_POLLING ? "polling" : "stream";
}
