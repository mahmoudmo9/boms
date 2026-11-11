/** AI drafts and the review screen (v0.9.0 section 2): types and the pure decision logic. */

export type Confidence = "high" | "medium" | "low";
export type Decision = "accepted" | "edited" | "rejected" | null;

export type DraftField = {
  id: string;
  path: string;
  label: string | null;
  proposed: unknown;
  confidence: Confidence;
  source: { page?: number | null; original?: string | null; row?: number | null };
  decision: Decision;
  final: unknown;
};

export type DraftSource = { document_id?: string; name?: string; kind: "pdf" | "image" | "sheet" | "text" | "pasted"; pages?: number;
  rows?: number; preview?: string[][]; text?: string };

export type Draft = {
  id: string;
  task: string;
  target_type: string;
  target_id: string | null;
  case_id: string | null;
  status: "pending" | "ready" | "accepted" | "partly_accepted" | "rejected" | "failed" | "superseded";
  error: string | null;
  sources: DraftSource[];
  checks: { item: number; kind: string; stated: string; computed: string }[];
  fields: DraftField[];
  result: Record<string, unknown> | null;
};

export type Provider = { id: string; kind: string; label: string; enabled: boolean; base_url: string | null; models: string[]; secret_name: string | null;
  has_key: boolean; status: "unknown" | "ok" | "error"; status_detail: string | null; last_checked_at: string | null; last_latency_ms: number | null;
  local: boolean; api: boolean; missing_prices: string[]; cli: { sdk: boolean; cli: string | null; steps: string | null; sdk_version?: string } | null };

export type Usage = { spent_usd: string; cap_usd: string; percent: number; warning: 50 | 80 | null; reached: boolean; api_fallback_enabled: boolean;
  subscription_calls: number; configured: boolean };

export type Route = { id: string; task: string; primary_provider_id: string | null; primary_model: string | null; fallback_provider_id: string | null;
  fallback_model: string | null; privacy: "cloud" | "cloud_redacted" | "local_only" };

export type CallRow = { id: string; at: string; task: string; entity_type: string | null; case_id: string | null; provider: string | null; provider_kind: string | null;
  model: string | null; prompt_version: string | null; input: Record<string, unknown>; redactions: Record<string, number>; privacy: string | null;
  tokens_in: number | null; tokens_out: number | null; cost_usd: string | null; subscription: boolean; duration_ms: number | null; status: string;
  error: string | null; attempt: number };

/** Groups the fields of an extraction draft per item («items[2].unit» -> item 2); terms and other fields go to -1. */
export function groupFields(fields: DraftField[]): Map<number, DraftField[]> {
  const out = new Map<number, DraftField[]>();
  for (const f of fields) {
    const m = /^items\[(\d+)\]\./.exec(f.path);
    const key = m ? Number(m[1]) : -1;
    out.set(key, [...(out.get(key) ?? []), f]);
  }
  return out;
}

export type ReviewSummary = { total: number; accepted: number; edited: number; rejected: number; open: number; confidentOpen: number; canCommit: boolean };

/** What the review screen shows: «ثبت» needs at least one accepted or edited field; the draft must be ready. */
export function reviewSummary(draft: Pick<Draft, "status" | "fields">): ReviewSummary {
  const f = draft.fields;
  const accepted = f.filter((x) => x.decision === "accepted").length;
  const edited = f.filter((x) => x.decision === "edited").length;
  const rejected = f.filter((x) => x.decision === "rejected").length;
  const open = f.filter((x) => x.decision === null).length;
  const confidentOpen = f.filter((x) => x.decision === null && x.confidence === "high").length;
  return { total: f.length, accepted, edited, rejected, open, confidentOpen, canCommit: draft.status === "ready" && accepted + edited > 0 };
}

/** The value the owner sees for a field: the final one once decided, the proposal before. */
export function shownValue(field: DraftField): unknown {
  return field.decision === "accepted" || field.decision === "edited" ? field.final : field.proposed;
}

/** A field's value as editable text, and back (numbers stay strings; lists and objects as JSON). */
export function toText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function fromText(text: string, original: unknown): unknown {
  if (typeof original === "string" || original === null || original === undefined) return text;
  if (typeof original === "number") return Number.isNaN(Number(text)) ? text : Number(text);
  try { return JSON.parse(text); } catch { return text; }
}

/** The privacy log row in one line: «۲ فایل، ۳ صفحه، ۴٬۲۰۰ نویسه» without any content. */
export function inputDescription(input: Record<string, unknown>): { files: number; pages: number; characters: number; images: number } {
  const files = Array.isArray(input.files) ? input.files.length : 0;
  return { files, pages: Number(input.pages ?? 0), characters: Number(input.characters ?? 0), images: Number(input.images ?? 0) };
}

/** The cap bar: 0-100 with the warning tone at 50 % and 80 %. */
export function capTone(usage: Pick<Usage, "percent" | "reached">): "neutral" | "warning" | "danger" {
  if (usage.reached || usage.percent >= 100) return "danger";
  if (usage.percent >= 50) return "warning";
  return "neutral";
}

/** Polling interval for a draft: every 1.5 s while the job runs, then stop. */
export function draftPoll(status: Draft["status"] | undefined): number | false {
  return status === "pending" ? 1500 : false;
}


// ---- Claude sign-in block (v0.10.0 section 0.1.2) ------------------------------------------------------------------

export type ClaudeStatus = {
  state: "no_sdk" | "no_cli" | "signed_in" | "signed_out" | "other_account";
  sdk: boolean; sdk_version: string | null; cli: string | null; account: string; config_dir: string; logged_in: boolean;
  auth_method: string | null; email: string | null; other_accounts: string[]; can_open_console: boolean; detail: string | null;
};

export type SignInView = { tone: "success" | "warning" | "danger" | "neutral"; canLogin: boolean; canLogout: boolean; showSteps: boolean;
  otherAccounts: string[] };

/** What the sign-in block shows and offers in each state. Signing in needs the CLI and a console BOMS can open (the
 * Windows PC it runs on); another account's sign-in is named, because it does not count for this account. */
export function signInView(s: ClaudeStatus): SignInView {
  const installed = s.state !== "no_sdk" && s.state !== "no_cli";
  return {
    tone: s.state === "signed_in" ? "success" : s.state === "other_account" ? "warning" : installed ? "neutral" : "danger",
    canLogin: installed && !s.logged_in && s.can_open_console,
    canLogout: installed && s.logged_in,
    showSteps: installed && !s.logged_in,
    otherAccounts: s.state === "other_account" ? s.other_accounts : [],
  };
}

// ---- the source of the field in focus (v0.10.0 section 0.2.3) ---------------------------------------------------------

export type Rect = { x: number; y: number; w: number; h: number };

export type FieldSource = { field_id: string; kind: "pdf" | "sheet" | "pasted" | "image" | null; source_index: number | null; found: boolean;
  original: string | null; page?: number; pages?: number; rects?: Rect[]; image?: string; rows?: number[]; start?: number; end?: number };

/** CSS box (percentages of the page image) for a region, padded a little so the text is not cut by the frame.
 * Physical `left` on purpose: these are coordinates on a picture of the page, they do not mirror with the UI direction. */
export function rectStyle(r: Rect, pad = 0.004): { left: string; top: string; width: string; height: string } {
  const x = Math.max(0, r.x - pad), y = Math.max(0, r.y - pad);
  const w = Math.min(1 - x, r.w + 2 * pad), h = Math.min(1 - y, r.h + 2 * pad);
  const pct = (n: number) => `${(n * 100).toFixed(3)}%`;
  return { left: pct(x), top: pct(y), width: pct(w), height: pct(h) };
}

/** Pasted text cut into [before, highlighted, after] for the span of the field in focus. */
export function splitSpan(text: string, start?: number, end?: number): [string, string, string] {
  if (start === undefined || end === undefined || start < 0 || end <= start || start >= text.length) return [text, "", ""];
  return [text.slice(0, start), text.slice(start, Math.min(end, text.length)), text.slice(Math.min(end, text.length))];
}

/** Which source panel a field's source belongs to, and whether that panel shows a highlight. */
export function sourceFocus(src: FieldSource | null | undefined, index: number): { active: boolean; rows: Set<number> } {
  const active = Boolean(src && src.source_index === index && (src.found || src.kind === "pdf"));
  return { active, rows: new Set(active && src?.kind === "sheet" ? src.rows ?? [] : []) };
}
