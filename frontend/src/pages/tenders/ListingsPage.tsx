/** «مناقصات و فراخوان‌ها» / Tenders & Calls: the Setad screening workspace (purchase calls and tenders). The table is
 * server-side (paging, sorting, counts over the whole result); filters live in the URL so a view can be shared. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { TimeLeftBadge } from "../../components/TimeLeft";
import { useToast } from "../../components/toast";
import { Badge, Button, Checkbox, EmptyState, ErrorNote, Input, Modal, Select } from "../../components/ui";
import { api, apiBlob } from "../../lib/api";
import {
  activeFilterCount, bulkBody, clearFilters, COLUMNS, type Column, DEFAULT_FILTERS, documentsState,
  EMPTY_SELECTION, filterStorageKey, filtersFromParams, filtersToParams, isSelected, type ListingFilters, type ListingSource,
  paramsToRemember, parseColumns, queryBody, rememberedParams,
  selectAllResults, type Selection, selectionCount, toggleColumn, toggleRow,
} from "../../lib/listings";
import { useFormat } from "../../lib/prefs";
import { finishedJobs, listingJobState, type TrackedJob } from "../../lib/setadFields";
import type { ListingDetail, ListingPage, ListingRow } from "../../lib/types";
import { ConnectionBar, useAgent } from "./ConnectionBar";
import { ConvertDialog } from "./ConvertDialog";
import { DismissDialog, ListingPanel, type PanelTab } from "./ListingPanel";

const PAGE_SIZES = [100, 200, 500, 1000];
const SORT_OF: Partial<Record<Column, string>> = { number: "number", title: "title", organization: "organization",
  province: "province", category: "category", deadline: "deadline", price: "price", status: "status" };

function load(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function save(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private window: not remembered */ }
}

/** Organisation filter: multi-select with search (SetadSuite 0.9.21). */
function OrganizationPicker({ filters, onChange }: { filters: ListingFilters; onChange: (v: string[]) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const facet = useQuery({
    queryKey: ["listings", "facet", "organization", filters.source, filters.q, q],
    queryFn: () => api<{ value: string; n: number }[]>("/api/listings/facets/organization",
      { method: "POST", body: { ...filters, organizations: [], q: filters.q.trim() || null }, query: { q } }),
    enabled: open,
  });
  const chosen = filters.organizations;
  const label = chosen.length === 0 ? t("listings.allOrganizations") : chosen.length === 1 ? chosen[0] : t("listings.nOrganizations", { n: f.num(chosen.length) });
  return (
    <>
      <button type="button" data-testid="org-picker" onClick={() => setOpen(true)}
        className="h-9 max-w-40 shrink-0 truncate rounded-md border border-line-strong bg-surface px-3 text-start text-sm xl:max-w-64" title={label}>{label}</button>
      {open && (
        <Modal open title={t("listings.organization")} onClose={() => setOpen(false)}
          footer={<><Button variant="ghost" onClick={() => onChange([])}>{t("common.clear")}</Button><Button onClick={() => setOpen(false)}>{t("common.close")}</Button></>}>
          <Input dir="auto" aria-label={t("listings.searchOrganizations")} placeholder={t("listings.searchOrganizations")} value={q} onChange={(e) => setQ(e.target.value)} />
          <ul className="mt-2 max-h-80 overflow-y-auto">
            {(facet.data ?? []).map((o) => (
              <li key={o.value} className="flex items-center justify-between gap-2 py-0.5">
                <Checkbox label={o.value} checked={chosen.includes(o.value)}
                  onChange={(v) => onChange(v ? [...chosen, o.value] : chosen.filter((x) => x !== o.value))} />
                <span className="text-xs text-muted tabular-nums">{f.num(o.n)}</span>
              </li>
            ))}
          </ul>
        </Modal>
      )}
    </>
  );
}

function FacetSelect({ field, filters, value, onChange }: { field: "province" | "category"; filters: ListingFilters; value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation();
  const facet = useQuery({
    queryKey: ["listings", "facet", field, filters.source],
    queryFn: () => api<{ value: string; n: number }[]>(`/api/listings/facets/${field}`, { method: "POST", body: { source: filters.source } }),
  });
  return (
    <Select aria-label={t(`listings.${field}`)} className="w-auto shrink-0" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{t(`listings.all_${field}`)}</option>
      {(facet.data ?? []).map((o) => <option key={o.value} value={o.value}>{o.value}</option>)}
    </Select>
  );
}

export function ListingsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => filtersFromParams(params), [params]);
  const panelId = params.get("listing");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "deadline", dir: "asc" });
  const [pageSize, setPageSize] = useState(() => Number(load("boms.listings.pageSize")) || 200);
  const [columns, setColumns] = useState<Column[]>(() => parseColumns(load(`boms.listings.columns.${filters.source}`), filters.source));
  const [chooser, setChooser] = useState(false);
  const [selection, setSelection] = useState<Selection>(EMPTY_SELECTION);
  const [dismissing, setDismissing] = useState(false);
  const [converting, setConverting] = useState<string | null>(null);
  const [density, setDensity] = useState<"compact" | "comfortable">(() => (load("boms.listings.density") === "comfortable" ? "comfortable" : "compact"));
  const [panelTab, setPanelTab] = useState<PanelTab>("fields");
  const [search, setSearch] = useState(filters.q);
  useEffect(() => { setColumns(parseColumns(load(`boms.listings.columns.${filters.source}`), filters.source)); }, [filters.source]);
  useEffect(() => { setPage(1); setSelection(EMPTY_SELECTION); }, [params]);
  // v0.6.0: open with the tab's remembered filters (default: deadline open, sorted by deadline) unless the link
  // carries its own; remember every change per tab
  useEffect(() => {
    if ([...params.keys()].some((k) => k !== "listing")) return;
    const source = (load("boms.listings.tab") === "setad_tender" ? "setad_tender" : "setad_purchase") as ListingSource;
    const p = rememberedParams(source, load(filterStorageKey(source)));
    if (params.get("listing")) p.set("listing", params.get("listing")!);
    if (p.toString() !== params.toString()) { setSearch(p.get("q") ?? ""); setParams(p, { replace: true }); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    save("boms.listings.tab", filters.source);
    save(filterStorageKey(filters.source), paramsToRemember(filters));
  }, [filters]);
  const switchTab = (source: ListingSource) => {
    const p = rememberedParams(source, load(filterStorageKey(source)));
    setSearch(p.get("q") ?? "");
    setParams(p, { replace: true });
  };

  const update = (next: Partial<ListingFilters>) => {
    const p = filtersToParams({ ...filters, ...next });
    if (panelId) p.set("listing", panelId);
    setParams(p, { replace: true });
  };
  useEffect(() => {    // search: debounced into the URL; the input keeps its own state, so typing never loses focus
    if (search === filters.q) return;
    const id = setTimeout(() => update({ q: search }), 350);
    return () => clearTimeout(id);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = useQuery({
    queryKey: ["listings", filters, page, pageSize, sort],
    queryFn: () => api<ListingPage>("/api/listings/query", { method: "POST", body: queryBody(filters, page, pageSize, sort.key, sort.dir) }),
    placeholderData: keepPreviousData,
  });
  const data = list.data;
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const counts = data?.counts;
  const bulk = useMutation({
    mutationFn: async ({ action, reason }: { action: string; reason?: string }) => {
      if (action === "export_csv") {
        const blob = await apiBlob("/api/listings/bulk", bulkBody(selection, action));
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "setad-listings.csv";
        a.click();
        URL.revokeObjectURL(a.href);
        return;
      }
      if (action === "fetch_detail" || action === "download_files") {
        const agent = await api<{ alive: boolean }>("/api/setad/agent");
        if (!agent.alive) await api("/api/setad/agent/start", { method: "POST" });
      }
      return api("/api/listings/bulk", { method: "POST", body: bulkBody(selection, action, reason) });
    },
    onSuccess: () => { setDismissing(false); setSelection(EMPTY_SELECTION); void queryClient.invalidateQueries({ queryKey: ["listings"] }); },
  });
  const tender = filters.source === "setad_tender";
  const chip = (key: string, label: string, n: number | undefined, active: boolean, onClick: () => void) => (
    <button key={key} type="button" aria-pressed={active} onClick={onClick} data-testid={`chip-${key}`}
      className={`inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-sm ${active ? "border-accent bg-accent-soft text-accent" : "border-line hover:bg-surface-2"}`}>
      {label}{n !== undefined && <span className="text-xs tabular-nums text-muted">{f.num(n)}</span>}
    </button>
  );
  const pageIds = (data?.items ?? []).map((r) => r.id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => isSelected(selection, id));
  const setSortKey = (key: string) => setSort((s) => ({ key, dir: s.key === key && s.dir === "asc" ? "desc" : "asc" }));
  /** Open a row in the panel; a click refreshes its cached detail in the background, keyboard moves do not. */
  const openPanel = (id: string | null, refresh = true) => {
    const p = new URLSearchParams(params);
    if (id) p.set("listing", id); else p.delete("listing");
    setParams(p, { replace: true });
    if (id && refresh) void queryClient.invalidateQueries({ queryKey: ["listing", id] });
  };

  // v0.6.0: keyboard up/down moves the selected row; a row that left the filter hands the selection to the next one
  const items = data?.items ?? [];
  const prevIds = useRef<string[]>([]);
  useEffect(() => {
    const ids = items.map((r) => r.id);
    if (panelId && ids.length && !ids.includes(panelId) && !list.isPlaceholderData) {
      const at = prevIds.current.indexOf(panelId);
      if (at >= 0) openPanel(ids[Math.min(at, ids.length - 1)] ?? null);
    }
    prevIds.current = ids;
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const el = e.target as HTMLElement | null;
      if (el && (el.closest("input, textarea, select, [role=dialog]") || el.isContentEditable)) return;
      const ids = items.map((r) => r.id);
      if (!ids.length) return;
      e.preventDefault();
      const at = panelId ? ids.indexOf(panelId) : -1;
      const next = ids[Math.max(0, Math.min(ids.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
      openPanel(next, false);
      requestAnimationFrame(() => scroller.current?.querySelector(`[data-listing="${next}"]`)?.scrollIntoView({ block: "nearest" }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useJobWatcher();
  const agent = useAgent();
  const comfortable = density === "comfortable";

  return (
    <div className="flex h-full min-h-0 flex-col gap-2" data-testid="screening-workspace">
      <div className="flex shrink-0 flex-wrap items-end gap-x-4 gap-y-1 border-b border-line">
        <h1 className="pb-2 text-lg font-semibold">{t("nav.tenders")}</h1>
        <div className="flex gap-1" role="tablist">
          {(["setad_purchase", "setad_tender"] as const).map((src) => (
            <button key={src} type="button" role="tab" aria-selected={filters.source === src} data-testid={`tab-${src}`}
              onClick={() => switchTab(src)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${filters.source === src ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
              {t(`listings.sources.${src}`)}
            </button>
          ))}
        </div>
      </div>
      <div className="shrink-0"><ConnectionBar source={filters.source} /></div>

      <div className="flex shrink-0 items-center gap-2 overflow-x-auto pb-0.5" data-testid="filters">
        <Input dir="auto" className="w-40 shrink-0 xl:w-56" aria-label={t("listings.search")} placeholder={t("listings.search")} data-testid="listing-search"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        <OrganizationPicker filters={filters} onChange={(organizations) => update({ organizations })} />
        <FacetSelect field="province" filters={filters} value={filters.provinces[0] ?? ""} onChange={(v) => update({ provinces: v ? [v] : [] })} />
        <FacetSelect field="category" filters={filters} value={filters.categories[0] ?? ""} onChange={(v) => update({ categories: v ? [v] : [] })} />
        <Select aria-label={t("listings.deadline")} className="w-auto shrink-0" value={filters.deadline ?? ""}
          onChange={(e) => update({ deadline: (e.target.value || null) as ListingFilters["deadline"] })}>
          <option value="">{t("listings.anyDeadline")}</option>
          <option value="open">{t("listings.deadlines.open")}</option>
          <option value="within">{t("listings.deadlines.within")}</option>
          <option value="passed">{t("listings.deadlines.passed")}</option>
        </Select>
        {filters.deadline === "within" && <Input type="number" min={1} max={365} dir="ltr" className="w-20 shrink-0" aria-label={t("listings.withinDays")}
          value={filters.within_days} onChange={(e) => update({ within_days: Math.max(1, Number(e.target.value) || 1) })} />}
        {activeFilterCount(filters) > 0 && <Button variant="ghost" data-testid="clear-filters"
          onClick={() => { setSearch(""); setParams(filtersToParams(clearFilters(filters)), { replace: true }); }}>
          <span className="whitespace-nowrap">{t("listings.clearFilters")} ({f.num(activeFilterCount(filters))})</span></Button>}
      </div>

      <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto pb-0.5" data-testid="chips">
        {chip("all", t("listings.chips.all"), counts?.all, !filters.status && !filters.new_only && !filters.downloaded && !filters.my_calls && !filters.price,
          () => update({ status: null, new_only: false, downloaded: false, my_calls: false, price: null }))}
        {chip("new", t("listings.chips.new"), counts?.new, filters.new_only, () => update({ new_only: !filters.new_only }))}
        {(["starred", "reviewing", "converted", "dismissed"] as const).map((st) =>
          chip(st, t(`listings.chips.${st}`), counts?.[st], filters.status === st, () => update({ status: filters.status === st ? null : st })))}
        {chip("downloaded", t("listings.chips.downloaded"), counts?.downloaded, filters.downloaded, () => update({ downloaded: !filters.downloaded }))}
        {chip("soon", t("listings.chips.soon"), counts?.soon, filters.deadline === "within" && filters.within_days === 3,
          () => update(filters.deadline === "within" ? { deadline: DEFAULT_FILTERS.deadline } : { deadline: "within", within_days: 3 }))}
        {tender && chip("free", t("listings.chips.free"), counts?.free, filters.price === "free", () => update({ price: filters.price === "free" ? null : "free" }))}
        {tender && chip("paid", t("listings.chips.paid"), counts?.paid, filters.price === "paid", () => update({ price: filters.price === "paid" ? null : "paid" }))}
        {tender && chip("my_calls", t("listings.chips.my_calls"), counts?.my_calls, filters.my_calls, () => update({ my_calls: !filters.my_calls }))}
        <span className="ms-auto shrink-0 whitespace-nowrap ps-2"><Checkbox label={t("listings.includeOld")} checked={filters.include_old} onChange={(v) => update({ include_old: v })} /></span>
      </div>

      {selectionCount(selection) > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-md border border-accent bg-accent-soft px-3 py-1.5 text-sm" data-testid="bulk-bar">
          <span>{t("listings.selected", { n: f.num(selectionCount(selection)) })}</span>
          {selection.mode === "ids" && allOnPage && total > pageIds.length && (
            <button type="button" className="text-accent hover:underline" data-testid="select-all-results"
              onClick={() => setSelection(selectAllResults(filters, total))}>{t("listings.selectAllResults", { n: f.num(total) })}</button>)}
          <span className="ms-auto flex flex-wrap gap-1.5">
            <Button onClick={() => bulk.mutate({ action: "star" })}>★ {t("listings.star")}</Button>
            <Button onClick={() => bulk.mutate({ action: "unstar" })}>{t("listings.unstar")}</Button>
            <Button onClick={() => setDismissing(true)}>{t("listings.dismiss")}</Button>
            <Button onClick={() => bulk.mutate({ action: "fetch_detail" })}>{t("listings.fetchDetail")}</Button>
            <Button onClick={() => bulk.mutate({ action: "download_files" })}>{t("listings.download")}</Button>
            <Button onClick={() => bulk.mutate({ action: "export_csv" })}>{t("listings.exportCsv")}</Button>
            <Button variant="ghost" onClick={() => setSelection(EMPTY_SELECTION)}>{t("common.cancel")}</Button>
          </span>
          <ErrorNote error={bulk.error} />
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 gap-3">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col rounded-md border border-line bg-surface" data-testid="table-area">
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-1.5 text-sm">
            <span className="text-muted" data-testid="listing-total">{t("listings.total", { n: f.num(total) })}</span>
            <span className="ms-auto flex items-center gap-1">
              <Button variant="ghost" data-testid="density" aria-pressed={comfortable}
                onClick={() => { const next = comfortable ? "compact" : "comfortable"; setDensity(next); save("boms.listings.density", next); }}>
                {t(comfortable ? "listings.densityCompact" : "listings.densityComfortable")}</Button>
              <span className="relative">
                <Button variant="ghost" onClick={() => setChooser(!chooser)} data-testid="column-chooser">{t("listings.columns")}</Button>
                {chooser && (
                  <div className="absolute end-0 z-30 mt-1 w-52 rounded-md border border-line bg-surface p-2 shadow-lg">
                    {COLUMNS.map((c) => (
                      <Checkbox key={c} label={t(`listings.cols.${c}`)} checked={columns.includes(c)} disabled={c === "title"}
                        onChange={() => { const next = toggleColumn(columns, c); setColumns(next); save(`boms.listings.columns.${filters.source}`, JSON.stringify(next)); }} />
                    ))}
                  </div>
                )}
              </span>
            </span>
          </div>
          <ErrorNote error={list.error} />
          <div ref={scroller} className="min-h-0 flex-1 overflow-auto" data-testid="table-scroll">
            {data && data.items.length === 0 ? <EmptyState>{t("listings.empty")}</EmptyState> : (
              <table className="w-full text-sm" data-testid="listing-table">
                <thead className="sticky top-0 z-10"><tr className="border-b border-line bg-surface-2 text-xs text-muted">
                  <th className="w-8 bg-surface-2 p-2"><input type="checkbox" aria-label={t("listings.selectPage")} className="h-4 w-4 accent-[var(--accent)]" checked={allOnPage}
                    onChange={(e) => setSelection(e.target.checked ? { mode: "ids", ids: new Set(pageIds) } : EMPTY_SELECTION)} /></th>
                  {columns.map((c) => (
                    <th key={c} className="bg-surface-2 p-2 text-start whitespace-nowrap">
                      {SORT_OF[c] ? <button type="button" className="hover:text-fg" onClick={() => setSortKey(SORT_OF[c]!)}>
                        {t(`listings.cols.${c}`)}{sort.key === SORT_OF[c] ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}</button> : t(`listings.cols.${c}`)}
                    </th>
                  ))}
                </tr></thead>
                <tbody>
                  {items.map((r, i) => (
                    <Row key={r.id} row={r} n={(page - 1) * pageSize + i + 1} columns={columns} active={r.id === panelId} comfortable={comfortable}
                      job={listingJobState(agent.data, r.id, "download_files") ?? listingJobState(agent.data, r.id, "fetch_detail")}
                      jobKind={listingJobState(agent.data, r.id, "download_files") ? "download" : "detail"}
                      checked={isSelected(selection, r.id)} onCheck={() => setSelection(toggleRow(selection, r.id))} onOpen={() => openPanel(r.id)} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-line px-3 py-1.5 text-sm" data-testid="paging">
            <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(1)}>«</Button>
            <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("listings.prev")}</Button>
            <span className="tabular-nums">{t("listings.pageOf", { page: f.num(page), pages: f.num(pages) })}</span>
            <Button variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("listings.next")}</Button>
            <Button variant="ghost" disabled={page >= pages} onClick={() => setPage(pages)}>»</Button>
            <Select aria-label={t("listings.pageSize")} className="ms-auto w-auto min-w-24" value={pageSize}
              onChange={(e) => { const v = Number(e.target.value); setPageSize(v); save("boms.listings.pageSize", String(v)); setPage(1); }}>
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{f.num(n)}</option>)}
            </Select>
          </div>
        </div>
        {panelId && (
          <div className="absolute inset-y-0 end-0 z-20 flex w-[min(28rem,100%)] shadow-xl xl:static xl:z-auto xl:w-[26rem] xl:shrink-0 xl:shadow-none" data-testid="panel-slot">
            <ListingPanel id={panelId} onClose={() => openPanel(null)} onConvert={setConverting} tab={panelTab} onTab={setPanelTab} />
          </div>
        )}
      </div>
      {converting && <ConvertDialog id={converting} onClose={() => setConverting(null)} />}
      {dismissing && <DismissDialog onClose={() => setDismissing(false)} busy={bulk.isPending} error={bulk.error}
        onConfirm={(reason) => bulk.mutate({ action: "dismiss", reason })} />}
    </div>
  );
}

/** When a Setad command finishes, refresh its listings (rows and an open panel) and tell the owner what happened. */
function useJobWatcher() {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();
  const agent = useAgent();
  const seen = useRef<Map<string, TrackedJob>>(new Map());
  useEffect(() => {
    const jobs = agent.data?.jobs;
    if (!jobs) return;
    const [done, now] = finishedJobs(seen.current, jobs);
    for (const { id, job } of done) {
      void queryClient.invalidateQueries({ queryKey: ["listings"] });
      for (const lid of job.listing_ids) void queryClient.invalidateQueries({ queryKey: ["listing", lid] });
      if (job.command !== "download_files" && job.command !== "fetch_detail") continue;
      void api<JobResult>(`/api/setad/jobs/${id}`).then((r) => {
        if (r.status === "failed") { toast(r.error || t("listings.job.failed"), "error"); return; }
        const res = r.result ?? {};
        if (job.command === "fetch_detail") {
          const failed = (res.listings ?? []).filter((x) => x.result === "failed").length;
          toast(t("listings.job.detailDone", { n: f.num((res.listings ?? []).length - failed), failed: f.num(failed) }), failed ? "error" : "success");
          return;
        }
        const c = res.totals ?? {};
        const first = (res.listings ?? []).find((x) => (x.counts?.downloaded ?? 0) + (x.counts?.skipped ?? 0) > 0);
        toast(<span className="flex flex-col gap-1">
          <span>{t("listings.job.downloadDone", { downloaded: f.num(c.downloaded ?? 0), skipped: f.num(c.skipped ?? 0), failed: f.num((c.failed ?? 0) + (c.restricted ?? 0)) })}</span>
          {first && <button type="button" className="self-start text-accent hover:underline" onClick={() => void openFolder(first.listing_id)}>{t("listings.openFolder")}</button>}
        </span>, (c.failed ?? 0) && !(c.downloaded ?? 0) ? "error" : "success");
      }).catch(() => undefined);
    }
    seen.current = now;
  }, [agent.data?.jobs]); // eslint-disable-line react-hooks/exhaustive-deps
}

interface JobResult {
  status: string; error: string | null;
  result: { listings?: { listing_id: string; result: string; counts?: Record<string, number> }[]; totals?: Record<string, number> } | null;
}

async function openFolder(listingId: string) {
  const d = await api<ListingDetail>(`/api/listings/${listingId}`);
  const file = d.files.find((x) => x.state === "downloaded");
  if (file) await api(`/api/listings/files/${file.id}/open`, { method: "POST", query: { folder: true } });
}

function Row({ row, n, columns, active, checked, comfortable, job, jobKind, onCheck, onOpen }: {
  row: ListingRow; n: number; columns: Column[]; active: boolean; checked: boolean; comfortable: boolean;
  job: ReturnType<typeof listingJobState>; jobKind: "download" | "detail"; onCheck: () => void; onOpen: () => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const docs = documentsState(row.documents);
  const clip = comfortable ? "" : "truncate";
  const cell = (c: Column) => {
    switch (c) {
      case "row": return <span className="tabular-nums text-muted">{row.is_new && <span className="me-1 inline-block h-2 w-2 rounded-full bg-accent" aria-label={t("listings.new")} />}{f.num(n)}</span>;
      case "number": return <Bdi ltr className="font-mono text-xs">{row.external_no}</Bdi>;
      case "title": return <span className={`flex min-w-0 ${comfortable ? "flex-col" : "items-center gap-1.5"}`}>
        <button type="button" className={`block max-w-[22rem] text-start font-medium hover:underline ${clip}`} onClick={onOpen} dir="auto" title={row.title}>
          {row.is_new && !columns.includes("row") && <span className="me-1 inline-block h-2 w-2 rounded-full bg-accent" aria-label={t("listings.new")} />}{row.title}</button>
        {row.warn.length > 0 && <span className="shrink-0 text-xs text-danger" title={row.warn.join("، ")}>⚠{comfortable && <> <Bdi>{row.warn.join("، ")}</Bdi></>}</span>}
        {job && <span className="shrink-0 rounded bg-accent-soft px-1.5 text-2xs text-accent" data-testid="row-job">
          {job.state === "queued" ? t(`listings.job.${jobKind}QueuedShort`) : job.total ? t(`listings.job.${jobKind}RunningShort`, { n: f.num(job.done ?? 0), total: f.num(job.total) }) : t(`listings.job.${jobKind}StartedShort`)}</span>}</span>;
      case "organization": return <span className={`block max-w-[12rem] text-xs ${clip}`} dir="auto" title={row.organization}>{row.organization}</span>;
      case "province": return <span className={`block max-w-[9rem] text-xs ${clip}`} title={`${row.province}${row.city ? ` · ${row.city}` : ""}`}>{row.province}{row.city ? ` · ${row.city}` : ""}</span>;
      case "category": return <span className={`block max-w-[8rem] text-xs ${clip}`}>{row.category || row.goods_group || row.service_group}</span>;
      case "deadline": return row.deadline ? <span className={`flex items-center gap-1.5 whitespace-nowrap text-xs ${comfortable ? "flex-wrap" : ""}`}>
        <span className="tabular-nums">{f.date(row.deadline, true)}</span>
        <TimeLeftBadge at={row.deadline} estimate={!row.deadline_exact && row.source === "setad_purchase"} /></span> : "—";
      case "price": return row.document_price === null ? "—" : Number(row.document_price) === 0
        ? <Badge tone="success">{t("listings.free")}</Badge> : <Bdi ltr className="tabular-nums text-xs">{f.num(row.document_price)}</Bdi>;
      case "documents": return docs === "empty" ? <span className="text-xs text-muted">—</span>
        : <span className="flex items-center gap-1 whitespace-nowrap text-xs"><Badge tone={docs === "complete" ? "success" : "warning"}>{t(`listings.docs.${docs}`)}</Badge>
          {docs === "partial" && <span className="tabular-nums text-muted">{t("listings.docsOf", { n: f.num(row.documents.downloaded), total: f.num(row.documents.total) })}</span>}</span>;
      case "status": return <span className="flex items-center gap-1 whitespace-nowrap text-xs"><Badge tone={row.status === "converted" ? "success" : row.status === "starred" ? "warning" : row.status === "dismissed" ? "neutral" : "accent"}>{t(`listings.status.${row.status}`)}</Badge>
        {row.in_my_calls && <span className={`max-w-[8rem] text-muted ${clip}`}>{row.site_state_name || t("listings.inMyCalls")}</span>}</span>;
    }
  };
  return (
    <tr className={`border-b border-line ${comfortable ? "align-top" : "h-10 align-middle"} ${active ? "bg-accent-soft" : "hover:bg-surface-2"}`} data-listing={row.id}
      aria-selected={active}>
      <td className="px-2 py-1"><input type="checkbox" aria-label={row.external_no} className="h-4 w-4 accent-[var(--accent)]" checked={checked} onChange={onCheck} /></td>
      {columns.map((c) => <td key={c} className={`px-2 ${comfortable ? "py-2" : "py-1 whitespace-nowrap"}`}>{cell(c)}</td>)}
    </tr>
  );
}
