/** Setad screening workspace helpers (pure, unit-tested): filter state <-> URL, column chooser, "select all results",
 * deadline and documents display. */

export type ListingSource = "setad_purchase" | "setad_tender";
export type ScreeningStatus = "new" | "starred" | "reviewing" | "converted" | "dismissed";

export interface ListingFilters {
  source: ListingSource;
  q: string;
  organizations: string[];
  provinces: string[];
  categories: string[];
  status: ScreeningStatus | null;
  new_only: boolean;
  deadline: "open" | "within" | "passed" | null;
  within_days: number;
  downloaded: boolean;
  price: "free" | "paid" | null;
  my_calls: boolean;
  include_old: boolean;
}

export const DEFAULT_FILTERS: ListingFilters = {
  source: "setad_purchase", q: "", organizations: [], provinces: [], categories: [], status: null, new_only: false,
  deadline: null, within_days: 3, downloaded: false, price: null, my_calls: false, include_old: false,
};

const LIST_KEYS = ["organizations", "provinces", "categories"] as const;
const BOOL_KEYS = ["new_only", "downloaded", "my_calls", "include_old"] as const;

/** Filters -> URL search params (only what differs from the defaults, so links stay short and shareable). */
export function filtersToParams(f: ListingFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.source !== DEFAULT_FILTERS.source) p.set("source", f.source);
  if (f.q.trim()) p.set("q", f.q.trim());
  for (const k of LIST_KEYS) for (const v of f[k]) p.append(k, v);
  if (f.status) p.set("status", f.status);
  for (const k of BOOL_KEYS) if (f[k]) p.set(k, "1");
  if (f.deadline) p.set("deadline", f.deadline);
  if (f.deadline === "within" && f.within_days !== DEFAULT_FILTERS.within_days) p.set("within_days", String(f.within_days));
  if (f.price) p.set("price", f.price);
  return p;
}

/** URL search params -> filters; unknown or invalid values fall back to the defaults. */
export function filtersFromParams(p: URLSearchParams): ListingFilters {
  const pick = <T extends string>(key: string, allowed: readonly T[]): T | null => {
    const v = p.get(key);
    return v && (allowed as readonly string[]).includes(v) ? (v as T) : null;
  };
  const days = Number(p.get("within_days"));
  const f: ListingFilters = {
    ...DEFAULT_FILTERS,
    source: pick("source", ["setad_purchase", "setad_tender"] as const) ?? DEFAULT_FILTERS.source,
    q: p.get("q") ?? "",
    status: pick("status", ["new", "starred", "reviewing", "converted", "dismissed"] as const),
    deadline: pick("deadline", ["open", "within", "passed"] as const),
    within_days: Number.isInteger(days) && days >= 1 && days <= 365 ? days : DEFAULT_FILTERS.within_days,
    price: pick("price", ["free", "paid"] as const),
  };
  for (const k of LIST_KEYS) f[k] = p.getAll(k).filter(Boolean);
  for (const k of BOOL_KEYS) f[k] = p.get(k) === "1";
  return f;
}

/** Number of active filters other than the source (for "Clear filters"). */
export function activeFilterCount(f: ListingFilters): number {
  let n = 0;
  if (f.q.trim()) n++;
  for (const k of LIST_KEYS) n += f[k].length ? 1 : 0;
  for (const k of BOOL_KEYS) n += f[k] ? 1 : 0;
  if (f.status) n++;
  if (f.deadline) n++;
  if (f.price) n++;
  return n;
}

export function clearFilters(f: ListingFilters): ListingFilters {
  return { ...DEFAULT_FILTERS, source: f.source };
}

/** Request body of POST /api/listings/query (the API rejects unknown fields). */
export function queryBody(f: ListingFilters, page: number, pageSize: number, sort: string, dir: "asc" | "desc") {
  return { ...f, q: f.q.trim() || null, page, page_size: pageSize, sort, dir };
}

// ---- column chooser ----------------------------------------------------------------------------------------

export const COLUMNS = ["row", "number", "title", "organization", "province", "category", "deadline", "price",
  "documents", "status"] as const;
export type Column = (typeof COLUMNS)[number];
const DEFAULT_HIDDEN: Record<ListingSource, Column[]> = {
  setad_purchase: ["price", "documents"],           // SetadSuite: the documents column is hidden by default
  setad_tender: ["row", "documents"],
};

export function defaultColumns(source: ListingSource): Column[] {
  return COLUMNS.filter((c) => !DEFAULT_HIDDEN[source].includes(c));
}

/** Toggle one column; the title column always stays (the row needs something to click). */
export function toggleColumn(visible: Column[], column: Column): Column[] {
  if (column === "title") return visible;
  return visible.includes(column) ? visible.filter((c) => c !== column) : COLUMNS.filter((c) => c === column || visible.includes(c));
}

/** Saved choice (localStorage) -> valid columns in table order; garbage -> defaults. */
export function parseColumns(saved: string | null, source: ListingSource): Column[] {
  try {
    const list = JSON.parse(saved ?? "null");
    if (!Array.isArray(list)) return defaultColumns(source);
    const cols = COLUMNS.filter((c) => list.includes(c) || c === "title");
    return cols.length ? cols : defaultColumns(source);
  } catch {
    return defaultColumns(source);
  }
}

// ---- selection: ticked rows or every row of the result -------------------------------------------------------

export type Selection = { mode: "ids"; ids: Set<string> } | { mode: "all"; filters: ListingFilters; total: number };

export const EMPTY_SELECTION: Selection = { mode: "ids", ids: new Set() };

export function toggleRow(sel: Selection, id: string): Selection {
  const ids = new Set(sel.mode === "ids" ? sel.ids : []);
  if (ids.has(id)) ids.delete(id);
  else ids.add(id);
  return { mode: "ids", ids };
}

export function selectAllResults(filters: ListingFilters, total: number): Selection {
  return { mode: "all", filters, total };
}

export function selectionCount(sel: Selection): number {
  return sel.mode === "all" ? sel.total : sel.ids.size;
}

export function isSelected(sel: Selection, id: string): boolean {
  return sel.mode === "all" || sel.ids.has(id);
}

/** Body of POST /api/listings/bulk: ticked ids, or the filters of the whole result. */
export function bulkBody(sel: Selection, action: string, reason?: string) {
  const target = sel.mode === "all"
    ? { filters: { ...sel.filters, q: sel.filters.q.trim() || null } }
    : { ids: [...sel.ids] };
  return { ...target, action, ...(reason ? { reason } : {}) };
}

// ---- display ----------------------------------------------------------------------------------------------------

/** Whole days left until a deadline (negative = passed); null without a deadline. */
export function daysLeft(deadline: string | null, now: Date = new Date()): number | null {
  if (!deadline) return null;
  const ms = new Date(deadline).getTime() - now.getTime();
  return ms >= 0 ? Math.floor(ms / 86_400_000) : -Math.ceil(-ms / 86_400_000);
}

export function deadlineTone(days: number | null): "danger" | "warning" | "success" | "neutral" {
  if (days === null) return "neutral";
  if (days < 0) return "neutral";
  if (days <= 1) return "danger";
  if (days <= 3) return "warning";
  return "success";
}

/** SetadSuite 0.9.19: complete (all downloaded) / partial («۱ از ۳») / empty. */
export function documentsState(d: { downloaded: number; total: number }): "complete" | "partial" | "empty" {
  if (!d.downloaded) return "empty";
  return d.total && d.downloaded >= d.total ? "complete" : "partial";
}
