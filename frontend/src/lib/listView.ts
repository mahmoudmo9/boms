/** v0.10.1 section 1.10, a rule for every paged or sorted list: page, page size and sort live in the URL query string
 * (with the filters and the selected row), so they survive a live update, a reload and back/forward. The page goes
 * back to 1 only when the owner changes a filter or the sort. */
import { useSearchParams } from "react-router";

export interface ListView { page: number; size: number; sort: string; dir: "asc" | "desc" }
export type ViewDefaults = { size: number; sort?: string; dir?: "asc" | "desc"; sizes?: readonly number[] };

const keys = (prefix: string) => ({ page: `${prefix}page`, size: `${prefix}size`, sort: `${prefix}sort`, dir: `${prefix}dir` });

export function readView(p: URLSearchParams, d: ViewDefaults, prefix = ""): ListView {
  const k = keys(prefix);
  const page = Number(p.get(k.page));
  const size = Number(p.get(k.size));
  const dir = p.get(k.dir);
  return {
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    size: Number.isInteger(size) && size >= 1 && size <= 1000 && (!d.sizes || d.sizes.includes(size)) ? size : d.size,
    sort: p.get(k.sort) ?? d.sort ?? "",
    dir: dir === "asc" || dir === "desc" ? dir : d.dir ?? "asc",
  };
}

/** The params with the view changed. A new sort or size sends the page back to 1; so does ``resetPage`` (a filter
 * change made elsewhere). Defaults are left out of the URL. */
export function writeView(p: URLSearchParams, next: Partial<ListView>, d: ViewDefaults, prefix = "", resetPage = false): URLSearchParams {
  const k = keys(prefix);
  const out = new URLSearchParams(p);
  const cur = readView(p, d, prefix);
  const view = { ...cur, ...next };
  if (resetPage || (next.sort !== undefined && next.sort !== cur.sort) || (next.dir !== undefined && next.dir !== cur.dir)
      || (next.size !== undefined && next.size !== cur.size)) {
    if (next.page === undefined) view.page = 1;
  }
  const set = (key: string, value: string, def: string) => { if (value === def) out.delete(key); else out.set(key, value); };
  set(k.page, String(view.page), "1");
  set(k.size, String(view.size), String(d.size));
  set(k.sort, view.sort, d.sort ?? "");
  set(k.dir, view.dir, d.dir ?? "asc");
  return out;
}

/** Carry the view (without the page) onto freshly built filter params: a filter change keeps sort and size. */
export function keepView(from: URLSearchParams, to: URLSearchParams, prefix = ""): URLSearchParams {
  const k = keys(prefix);
  for (const key of [k.size, k.sort, k.dir]) { const v = from.get(key); if (v !== null) to.set(key, v); }
  to.delete(k.page);
  return to;
}

/** The view of one list on this page and its setter (a page change is a history entry, so back/forward walk it). */
export function useListView(d: ViewDefaults, prefix = ""): [ListView, (next: Partial<ListView>) => void] {
  const [params, setParams] = useSearchParams();
  const view = readView(params, d, prefix);
  const set = (next: Partial<ListView>) => setParams((prev) => writeView(prev, next, d, prefix), { replace: next.page === undefined });
  return [view, set];
}
