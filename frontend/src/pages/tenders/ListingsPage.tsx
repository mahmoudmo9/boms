/** «مناقصات و فراخوان‌ها» / Tenders & Calls: the Setad screening workspace (purchase calls and tenders). The table is
 * server-side (paging, sorting, counts over the whole result); filters live in the URL so a view can be shared. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Badge, Button, Checkbox, EmptyState, ErrorNote, Input, Modal, PageHeader, Select } from "../../components/ui";
import { api, apiBlob } from "../../lib/api";
import {
  activeFilterCount, bulkBody, clearFilters, COLUMNS, type Column, daysLeft, deadlineTone, documentsState,
  EMPTY_SELECTION, filtersFromParams, filtersToParams, isSelected, type ListingFilters, parseColumns, queryBody,
  selectAllResults, type Selection, selectionCount, toggleColumn, toggleRow,
} from "../../lib/listings";
import { useFormat } from "../../lib/prefs";
import type { ListingPage, ListingRow } from "../../lib/types";
import { ConnectionBar } from "./ConnectionBar";
import { ConvertDialog } from "./ConvertDialog";
import { DismissDialog, ListingPanel } from "./ListingPanel";

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
        className="h-9 max-w-64 truncate rounded-md border border-line-strong bg-surface px-3 text-start text-sm">{label}</button>
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
    <Select aria-label={t(`listings.${field}`)} className="w-auto min-w-36" value={value} onChange={(e) => onChange(e.target.value)}>
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
  const [search, setSearch] = useState(filters.q);
  useEffect(() => { setColumns(parseColumns(load(`boms.listings.columns.${filters.source}`), filters.source)); }, [filters.source]);
  useEffect(() => { setPage(1); setSelection(EMPTY_SELECTION); }, [params]);

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
      className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm ${active ? "border-accent bg-accent-soft text-accent" : "border-line hover:bg-surface-2"}`}>
      {label}{n !== undefined && <span className="text-xs tabular-nums text-muted">{f.num(n)}</span>}
    </button>
  );
  const pageIds = (data?.items ?? []).map((r) => r.id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => isSelected(selection, id));
  const setSortKey = (key: string) => setSort((s) => ({ key, dir: s.key === key && s.dir === "asc" ? "desc" : "asc" }));
  const openPanel = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("listing", id); else p.delete("listing");
    setParams(p, { replace: true });
  };

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title={t("nav.tenders")} subtitle={t("listings.subtitle")} />
      <div className="flex gap-1 border-b border-line" role="tablist">
        {(["setad_purchase", "setad_tender"] as const).map((src) => (
          <button key={src} type="button" role="tab" aria-selected={filters.source === src} data-testid={`tab-${src}`}
            onClick={() => setParams(filtersToParams({ ...clearFilters(filters), source: src }), { replace: true })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${filters.source === src ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
            {t(`listings.sources.${src}`)}
          </button>
        ))}
      </div>
      <ConnectionBar source={filters.source} />

      <div className="flex flex-wrap items-center gap-2">
        <Input dir="auto" className="w-64" aria-label={t("listings.search")} placeholder={t("listings.search")} data-testid="listing-search"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        <OrganizationPicker filters={filters} onChange={(organizations) => update({ organizations })} />
        <FacetSelect field="province" filters={filters} value={filters.provinces[0] ?? ""} onChange={(v) => update({ provinces: v ? [v] : [] })} />
        <FacetSelect field="category" filters={filters} value={filters.categories[0] ?? ""} onChange={(v) => update({ categories: v ? [v] : [] })} />
        <Select aria-label={t("listings.deadline")} className="w-auto min-w-36" value={filters.deadline ?? ""}
          onChange={(e) => update({ deadline: (e.target.value || null) as ListingFilters["deadline"] })}>
          <option value="">{t("listings.anyDeadline")}</option>
          <option value="open">{t("listings.deadlines.open")}</option>
          <option value="within">{t("listings.deadlines.within")}</option>
          <option value="passed">{t("listings.deadlines.passed")}</option>
        </Select>
        {filters.deadline === "within" && <Input type="number" min={1} max={365} dir="ltr" className="w-20" aria-label={t("listings.withinDays")}
          value={filters.within_days} onChange={(e) => update({ within_days: Math.max(1, Number(e.target.value) || 1) })} />}
        {activeFilterCount(filters) > 0 && <Button variant="ghost" data-testid="clear-filters"
          onClick={() => { setSearch(""); setParams(filtersToParams(clearFilters(filters)), { replace: true }); }}>
          {t("listings.clearFilters")} ({f.num(activeFilterCount(filters))})</Button>}
      </div>

      <div className="flex flex-wrap items-center gap-1.5" data-testid="chips">
        {chip("all", t("listings.chips.all"), counts?.all, !filters.status && !filters.new_only && !filters.downloaded && !filters.my_calls && !filters.price,
          () => update({ status: null, new_only: false, downloaded: false, my_calls: false, price: null }))}
        {chip("new", t("listings.chips.new"), counts?.new, filters.new_only, () => update({ new_only: !filters.new_only }))}
        {(["starred", "reviewing", "converted", "dismissed"] as const).map((s) =>
          chip(s, t(`listings.chips.${s}`), counts?.[s], filters.status === s, () => update({ status: filters.status === s ? null : s })))}
        {chip("downloaded", t("listings.chips.downloaded"), counts?.downloaded, filters.downloaded, () => update({ downloaded: !filters.downloaded }))}
        {chip("soon", t("listings.chips.soon"), counts?.soon, filters.deadline === "within" && filters.within_days === 3,
          () => update(filters.deadline === "within" ? { deadline: null } : { deadline: "within", within_days: 3 }))}
        {tender && chip("free", t("listings.chips.free"), counts?.free, filters.price === "free", () => update({ price: filters.price === "free" ? null : "free" }))}
        {tender && chip("paid", t("listings.chips.paid"), counts?.paid, filters.price === "paid", () => update({ price: filters.price === "paid" ? null : "paid" }))}
        {tender && chip("my_calls", t("listings.chips.my_calls"), counts?.my_calls, filters.my_calls, () => update({ my_calls: !filters.my_calls }))}
        <span className="ms-auto"><Checkbox label={t("listings.includeOld")} checked={filters.include_old} onChange={(v) => update({ include_old: v })} /></span>
      </div>

      {selectionCount(selection) > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-accent bg-accent-soft px-3 py-2 text-sm" data-testid="bulk-bar">
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

      <div className="flex min-w-0 flex-col gap-3 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1 rounded-md border border-line bg-surface">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-sm">
            <span className="text-muted" data-testid="listing-total">{t("listings.total", { n: f.num(total) })}</span>
            <span className="ms-auto relative">
              <Button variant="ghost" onClick={() => setChooser(!chooser)} data-testid="column-chooser">{t("listings.columns")}</Button>
              {chooser && (
                <div className="absolute end-0 z-20 mt-1 w-52 rounded-md border border-line bg-surface p-2 shadow-lg">
                  {COLUMNS.map((c) => (
                    <Checkbox key={c} label={t(`listings.cols.${c}`)} checked={columns.includes(c)} disabled={c === "title"}
                      onChange={() => { const next = toggleColumn(columns, c); setColumns(next); save(`boms.listings.columns.${filters.source}`, JSON.stringify(next)); }} />
                  ))}
                </div>
              )}
            </span>
          </div>
          <ErrorNote error={list.error} />
          {data && data.items.length === 0 ? <EmptyState>{t("listings.empty")}</EmptyState> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="listing-table">
                <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
                  <th className="w-8 p-2"><input type="checkbox" aria-label={t("listings.selectPage")} className="h-4 w-4 accent-[var(--accent)]" checked={allOnPage}
                    onChange={(e) => setSelection(e.target.checked ? { mode: "ids", ids: new Set(pageIds) } : EMPTY_SELECTION)} /></th>
                  {columns.map((c) => (
                    <th key={c} className="p-2 text-start whitespace-nowrap">
                      {SORT_OF[c] ? <button type="button" className="hover:text-fg" onClick={() => setSortKey(SORT_OF[c]!)}>
                        {t(`listings.cols.${c}`)}{sort.key === SORT_OF[c] ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}</button> : t(`listings.cols.${c}`)}
                    </th>
                  ))}
                </tr></thead>
                <tbody>
                  {(data?.items ?? []).map((r, i) => (
                    <Row key={r.id} row={r} n={(page - 1) * pageSize + i + 1} columns={columns} active={r.id === panelId}
                      checked={isSelected(selection, r.id)} onCheck={() => setSelection(toggleRow(selection, r.id))} onOpen={() => openPanel(r.id)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2 text-sm">
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
        {panelId && <ListingPanel id={panelId} onClose={() => openPanel(null)} onConvert={setConverting} />}
      </div>
      {converting && <ConvertDialog id={converting} onClose={() => setConverting(null)} />}
      {dismissing && <DismissDialog onClose={() => setDismissing(false)} busy={bulk.isPending} error={bulk.error}
        onConfirm={(reason) => bulk.mutate({ action: "dismiss", reason })} />}
    </div>
  );
}

function Row({ row, n, columns, active, checked, onCheck, onOpen }: {
  row: ListingRow; n: number; columns: Column[]; active: boolean; checked: boolean; onCheck: () => void; onOpen: () => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const days = daysLeft(row.deadline);
  const docs = documentsState(row.documents);
  const cell = (c: Column) => {
    switch (c) {
      case "row": return <span className="tabular-nums text-muted">{row.is_new && <span className="me-1 inline-block h-2 w-2 rounded-full bg-accent" aria-label={t("listings.new")} />}{f.num(n)}</span>;
      case "number": return <Bdi ltr className="font-mono text-xs">{row.external_no}</Bdi>;
      case "title": return <span className="flex flex-col">
        <button type="button" className="max-w-[18rem] text-start font-medium hover:underline" onClick={onOpen} dir="auto">
          {row.is_new && !columns.includes("row") && <span className="me-1 inline-block h-2 w-2 rounded-full bg-accent" aria-label={t("listings.new")} />}{row.title}</button>
        {row.warn.length > 0 && <span className="text-xs text-danger">⚠ <Bdi>{row.warn.join("، ")}</Bdi></span>}</span>;
      case "organization": return <span className="block max-w-[10rem] text-xs" dir="auto">{row.organization}</span>;
      case "province": return <span className="text-xs">{row.province}{row.city ? ` · ${row.city}` : ""}</span>;
      case "category": return <span className="text-xs">{row.category || row.goods_group || row.service_group}</span>;
      case "deadline": return row.deadline ? <span className="flex flex-col whitespace-nowrap text-xs">
        <span className="tabular-nums">{f.day(row.deadline.slice(0, 10))}</span>
        <Badge tone={deadlineTone(days)}>{days !== null && days < 0 ? t("listings.passed") : t("listings.daysLeft", { count: days ?? 0, n: f.num(days ?? 0) })}</Badge></span> : "—";
      case "price": return row.document_price === null ? "—" : Number(row.document_price) === 0
        ? <Badge tone="success">{t("listings.free")}</Badge> : <Bdi ltr className="tabular-nums text-xs">{f.num(row.document_price)}</Bdi>;
      case "documents": return docs === "empty" ? <span className="text-xs text-muted">—</span>
        : <span className="flex flex-col text-xs"><Badge tone={docs === "complete" ? "success" : "warning"}>{t(`listings.docs.${docs}`)}</Badge>
          {docs === "partial" && <span className="tabular-nums text-muted">{t("listings.docsOf", { n: f.num(row.documents.downloaded), total: f.num(row.documents.total) })}</span>}</span>;
      case "status": return <span className="flex flex-col gap-0.5 text-xs"><Badge tone={row.status === "converted" ? "success" : row.status === "starred" ? "warning" : row.status === "dismissed" ? "neutral" : "accent"}>{t(`listings.status.${row.status}`)}</Badge>
        {row.in_my_calls && <span className="text-muted">{row.site_state_name || t("listings.inMyCalls")}</span>}</span>;
    }
  };
  return (
    <tr className={`border-b border-line align-top ${active ? "bg-accent-soft" : "hover:bg-surface-2"}`} data-listing={row.id}>
      <td className="p-2"><input type="checkbox" aria-label={row.external_no} className="h-4 w-4 accent-[var(--accent)]" checked={checked} onChange={onCheck} /></td>
      {columns.map((c) => <td key={c} className="p-2">{cell(c)}</td>)}
    </tr>
  );
}
