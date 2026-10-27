import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DataTable, Pagination } from "../../components/DataTable";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, IconButton, Input, Loading, Modal, PageHeader, Select, Textarea } from "../../components/ui";
import { api, ApiError, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Product, ProductPage as ProductPageData } from "../../lib/types";
import { PartyName, stageLabel } from "../parties/shared";
import { ContactName, Money, productName, UnitInput, useInvalidateSourcing, useUnitLabel } from "./shared";

const PAGE_SIZE = 50;

interface Category {
  id: string;
  parent_id: string | null;
  name_fa: string | null;
  name_en: string | null;
}

function useCategories() {
  return useQuery({ queryKey: ["products", "categories"], queryFn: () => api<Category[]>("/api/products/categories") });
}

interface Duplicate {
  id: string;
  name_fa: string | null;
  name_en: string | null;
  score: number;
  reason: string;
}

function NewProductDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const navigate = useNavigate();
  const invalidate = useInvalidateSourcing();
  const categories = useCategories();
  const [form, setForm] = useState({ name_fa: "", name_en: "", hs_code: "", kind_note: "", default_unit_code: null as string | null, category_id: "", aliases: "" });
  const [duplicates, setDuplicates] = useState<Duplicate[] | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const create = useMutation({
    mutationFn: () => api<{ created: boolean; product?: Product; possible_duplicates: Duplicate[] }>("/api/products", {
      method: "POST",
      body: {
        name_fa: form.name_fa || null, name_en: form.name_en || null, hs_code: form.hs_code || null, kind_note: form.kind_note || null,
        default_unit_code: form.default_unit_code, category_id: form.category_id || null,
        aliases: form.aliases.split("\n").map((a) => a.trim()).filter(Boolean), confirm_duplicate: confirmed,
      },
    }),
    onSuccess: (res) => {
      if (res.created && res.product) { invalidate(); onClose(); navigate(`/sourcing/catalog/${res.product.id}`); }
      else setDuplicates(res.possible_duplicates);
    },
  });
  return (
    <Modal open wide title={t("sourcing.catalog.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" type="submit" form="new-product" busy={create.isPending} disabled={(!form.name_fa.trim() && !form.name_en.trim()) || (!!duplicates?.length && !confirmed)}>{t("common.save")}</Button></>}>
      <form id="new-product" className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label={t("parties.nameFa")} htmlFor="np-fa"><Input id="np-fa" autoFocus value={form.name_fa} onChange={(e) => { setForm({ ...form, name_fa: e.target.value }); setDuplicates(null); setConfirmed(false); }} /></Field>
        <Field label={t("parties.nameEn")} htmlFor="np-en"><Input id="np-en" dir="ltr" value={form.name_en} onChange={(e) => { setForm({ ...form, name_en: e.target.value }); setDuplicates(null); setConfirmed(false); }} /></Field>
        {duplicates && duplicates.length > 0 && (
          <div className="rounded-md bg-warning-soft p-2.5 text-sm sm:col-span-2">
            <p className="mb-1.5 font-medium text-warning">{t("sourcing.catalog.possibleDuplicates")}</p>
            <ul className="mb-2 flex flex-col gap-1">{duplicates.map((d) => (
              <li key={d.id}><Link className="text-accent hover:underline" to={`/sourcing/catalog/${d.id}`}><Bdi>{productName(d, f.lang)}</Bdi></Link> <span className="text-xs text-muted">({t(`sourcing.catalog.matchBy.${d.reason}`)})</span></li>
            ))}</ul>
            <Checkbox label={t("parties.confirmDuplicate")} checked={confirmed} onChange={setConfirmed} />
          </div>
        )}
        <Field label={t("sourcing.item.hsCode")} htmlFor="np-hs"><Input id="np-hs" dir="ltr" inputMode="numeric" value={form.hs_code} onChange={(e) => setForm({ ...form, hs_code: e.target.value.replace(/\D/g, "") })} /></Field>
        <Field label={t("sourcing.catalog.defaultUnit")} htmlFor="np-unit"><UnitInput id="np-unit" code={form.default_unit_code} text={null} onChange={(u) => setForm({ ...form, default_unit_code: u.unit_code })} /></Field>
        <Field label={t("sourcing.catalog.kindNote")} htmlFor="np-kind"><Input id="np-kind" dir="auto" value={form.kind_note} onChange={(e) => setForm({ ...form, kind_note: e.target.value })} /></Field>
        <Field label={t("sourcing.catalog.category")} htmlFor="np-cat">
          <Select id="np-cat" value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
            <option value="">—</option>
            {(categories.data ?? []).map((c) => <option key={c.id} value={c.id}>{productName(c, f.lang)}</option>)}
          </Select>
        </Field>
        <div className="sm:col-span-2"><Field label={t("sourcing.catalog.aliases")} htmlFor="np-alias" hint={t("sourcing.catalog.aliasesHint")}>
          <Textarea id="np-alias" dir="auto" rows={3} value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} />
        </Field></div>
        <div className="sm:col-span-2"><ErrorNote error={create.error} /></div>
      </form>
    </Modal>
  );
}

function CategoriesDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const categories = useCategories();
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => api("/api/products/categories", { method: "POST", body: /[؀-ۿ]/.test(name) ? { name_fa: name } : { name_en: name } }),
    onSuccess: () => { setName(""); void categories.refetch(); },
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/products/categories/${id}`, { method: "DELETE" }), onSuccess: () => void categories.refetch() });
  return (
    <Modal open title={t("sourcing.catalog.categories")} onClose={onClose}>
      <ul className="mb-3 flex flex-col gap-1">
        {(categories.data ?? []).map((c) => (
          <li key={c.id} className="flex items-center gap-2 text-sm"><Bdi>{productName(c, f.lang)}</Bdi>
            <IconButton icon="x" label={t("delete.button")} className="ms-auto" onClick={() => remove.mutate(c.id)} /></li>
        ))}
      </ul>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate(); }}>
        <Input dir="auto" aria-label={t("sourcing.catalog.category")} value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" icon="plus" busy={add.isPending}>{t("common.add")}</Button>
      </form>
      <ErrorNote error={add.error || remove.error} />
    </Modal>
  );
}

export function CatalogPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const unitLabel = useUnitLabel();
  const categories = useCategories();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState(false);
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const sort = params.get("sort") ?? "name";
  const page = Number(params.get("page") ?? 1);
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };
  const list = useQuery({
    queryKey: ["products", "list", q, category, sort, page],
    queryFn: () => api<Page<Product>>("/api/products", { query: { q, category_id: category, sort, page, page_size: PAGE_SIZE } }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<Product, unknown>[]>(() => [
    { id: "name", header: t("sourcing.catalog.product"), cell: ({ row }) => (
      <div><Link to={`/sourcing/catalog/${row.original.id}`} className="font-medium text-accent hover:underline"><Bdi>{productName(row.original, f.lang)}</Bdi></Link>
        {row.original.aliases.length > 0 && <div className="text-xs text-muted" dir="auto">{row.original.aliases.map((a) => a.alias).join(" · ")}</div>}</div>
    ) },
    { id: "hs", header: t("sourcing.item.hsCode"), cell: ({ row }) => <Bdi ltr className="font-mono text-xs">{row.original.hs_code ?? ""}</Bdi> },
    { id: "unit", header: t("sourcing.catalog.defaultUnit"), cell: ({ row }) => unitLabel(row.original.default_unit_code) },
    { id: "offers", header: t("sourcing.catalog.offers"), cell: ({ row }) => <span className="tabular-nums">{f.num(row.original.offers ?? 0)}</span> },
    { id: "last_requested", header: t("sourcing.catalog.lastRequested"), cell: ({ row }) => <span className="tabular-nums text-muted">{f.date(row.original.last_requested ?? null)}</span> },
    { id: "status", header: t("sourcing.status.label"), cell: ({ row }) => row.original.status === "archived" ? <Badge>{t("parties.archived")}</Badge> : null },
  ], [t, f, unitLabel]);
  return (
    <div>
      <PageHeader title={t("sourcing.catalog.title")} subtitle={t("sourcing.catalog.subtitle")}
        actions={<><Button onClick={() => setManaging(true)}>{t("sourcing.catalog.categories")}</Button>
          <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>{t("sourcing.catalog.new")}</Button></>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input key={q} type="search" className="max-w-xs" placeholder={t("sourcing.catalog.searchPlaceholder")} defaultValue={q}
            onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })} />
          <Select className="w-44" aria-label={t("sourcing.catalog.category")} value={category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">{t("sourcing.catalog.allCategories")}</option>
            {(categories.data ?? []).map((c) => <option key={c.id} value={c.id}>{productName(c, f.lang)}</option>)}
          </Select>
          <Select className="w-48" aria-label={t("sourcing.catalog.sort")} value={sort} onChange={(e) => set({ sort: e.target.value })}>
            {(["name", "last_requested", "offers"] as const).map((s) => <option key={s} value={s}>{t(`sourcing.catalog.sorts.${s}`)}</option>)}
          </Select>
        </div>
        <ErrorNote error={list.error} />
        <DataTable columns={columns} data={list.data?.items ?? []} loading={list.isFetching} rowKey={(r) => r.id} empty={t("sourcing.catalog.empty")} />
        <Pagination page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={(p) => set({ page: String(p) })} />
      </Card>
      {creating && <NewProductDialog onClose={() => setCreating(false)} />}
      {managing && <CategoriesDialog onClose={() => setManaging(false)} />}
    </div>
  );
}

/** v0.4.0: edit a product (names, unit, HS, category, kind, notes); aliases stay as they are (own card).
 * A rename that looks like another product answers 409 possible_duplicate: list them and ask to confirm. */
function EditProductDialog({ product, onClose, onSaved }: { product: Product; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const categories = useCategories();
  const [form, setForm] = useState({ name_fa: product.name_fa ?? "", name_en: product.name_en ?? "", hs_code: product.hs_code ?? "",
    kind_note: product.kind_note ?? "", default_unit_code: product.default_unit_code, category_id: product.category_id ?? "", notes: product.notes ?? "" });
  const [confirmed, setConfirmed] = useState(false);
  const save = useMutation({
    mutationFn: () => api(`/api/products/${product.id}`, {
      method: "PATCH",
      body: { name_fa: form.name_fa || null, name_en: form.name_en || null, hs_code: form.hs_code || null, kind_note: form.kind_note || null,
        default_unit_code: form.default_unit_code, category_id: form.category_id || null, notes: form.notes || null, confirm_duplicate: confirmed },
    }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  const duplicates = save.error instanceof ApiError && save.error.code === "possible_duplicate"
    ? (save.error.details.possible_duplicates as Duplicate[]) : null;
  const change = (patch: Partial<typeof form>) => { setForm({ ...form, ...patch }); setConfirmed(false); save.reset(); };
  return (
    <Modal open wide title={t("sourcing.catalog.edit")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" busy={save.isPending} disabled={(!form.name_fa.trim() && !form.name_en.trim()) || (!!duplicates && !confirmed)} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("parties.nameFa")} htmlFor="ep-fa"><Input id="ep-fa" value={form.name_fa} onChange={(e) => change({ name_fa: e.target.value })} /></Field>
        <Field label={t("parties.nameEn")} htmlFor="ep-en"><Input id="ep-en" dir="ltr" value={form.name_en} onChange={(e) => change({ name_en: e.target.value })} /></Field>
        {duplicates && (
          <div className="rounded-md bg-warning-soft p-2.5 text-sm sm:col-span-2">
            <p className="mb-1.5 font-medium text-warning">{t("sourcing.catalog.possibleDuplicates")}</p>
            <ul className="mb-2 flex flex-col gap-1">{duplicates.map((d) => (
              <li key={d.id}><Link className="text-accent hover:underline" to={`/sourcing/catalog/${d.id}`}><Bdi>{productName(d, f.lang)}</Bdi></Link> <span className="text-xs text-muted">({t(`sourcing.catalog.matchBy.${d.reason}`)})</span></li>
            ))}</ul>
            <Checkbox label={t("parties.confirmDuplicate")} checked={confirmed} onChange={setConfirmed} />
          </div>
        )}
        <Field label={t("sourcing.item.hsCode")} htmlFor="ep-hs"><Input id="ep-hs" dir="ltr" inputMode="numeric" value={form.hs_code} onChange={(e) => change({ hs_code: e.target.value.replace(/\D/g, "") })} /></Field>
        <Field label={t("sourcing.catalog.defaultUnit")} htmlFor="ep-unit"><UnitInput id="ep-unit" code={form.default_unit_code} text={null} onChange={(u) => change({ default_unit_code: u.unit_code })} /></Field>
        <Field label={t("sourcing.catalog.kindNote")} htmlFor="ep-kind"><Input id="ep-kind" dir="auto" value={form.kind_note} onChange={(e) => change({ kind_note: e.target.value })} /></Field>
        <Field label={t("sourcing.catalog.category")} htmlFor="ep-cat">
          <Select id="ep-cat" value={form.category_id} onChange={(e) => change({ category_id: e.target.value })}>
            <option value="">—</option>
            {(categories.data ?? []).map((c) => <option key={c.id} value={c.id}>{productName(c, f.lang)}</option>)}
          </Select>
        </Field>
        <div className="sm:col-span-2"><Field label={t("parties.notes")} htmlFor="ep-notes"><Textarea id="ep-notes" dir="auto" rows={3} value={form.notes} onChange={(e) => change({ notes: e.target.value })} /></Field></div>
        <p className="text-xs text-muted sm:col-span-2">{t("sourcing.catalog.aliasesSeparate")}</p>
        {!duplicates && <div className="sm:col-span-2"><ErrorNote error={save.error} /></div>}
      </div>
    </Modal>
  );
}

export function ProductPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const f = useFormat();
  const unitLabel = useUnitLabel();
  const invalidate = useInvalidateSourcing();
  const navigate = useNavigate();
  const [alias, setAlias] = useState("");
  const [editing, setEditing] = useState(false);
  const product = useQuery({ queryKey: ["products", "page", id], queryFn: () => api<ProductPageData>(`/api/products/${id}`) });
  const refresh = () => { void product.refetch(); invalidate(); };
  const addAlias = useMutation({ mutationFn: () => api(`/api/products/${id}/aliases`, { method: "POST", body: { alias } }), onSuccess: () => { setAlias(""); refresh(); } });
  const removeAlias = useMutation({ mutationFn: (aliasId: string) => api(`/api/products/aliases/${aliasId}`, { method: "DELETE" }), onSuccess: refresh });
  const archive = useMutation({ mutationFn: (archived: boolean) => api(`/api/products/${id}/${archived ? "unarchive" : "archive"}`, { method: "POST" }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => api(`/api/products/${id}`, { method: "DELETE" }), onSuccess: () => { invalidate(); navigate("/sourcing/catalog"); } });
  if (product.isLoading) return <Loading />;
  if (product.error || !product.data) return <ErrorNote error={product.error} />;
  const p = product.data;
  const groupLabel = (g: string) => (g.startsWith("kind:") ? t(`sourcing.compare.kinds.${g.slice(5)}`) : g.startsWith("unit:") ? unitLabel(g.slice(5)) : g.slice(5) || "—");
  const baseUnit: Record<string, string> = { "kind:weight": "kg", "kind:length": "m", "kind:volume": "m3", "kind:area": "m2", "kind:count": "pc", "kind:time": "s" };
  const perBase = (g: string) => (baseUnit[g] ? `/ ${unitLabel(baseUnit[g])}` : "");
  return (
    <div className="flex flex-col gap-4">
      <Link to="/sourcing/catalog" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><Icon name="chevronStart" size={15} /> {t("sourcing.catalog.title")}</Link>
      <PageHeader title={<Bdi>{productName(p, f.lang)}</Bdi>}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          {p.name_fa && p.name_en && <Bdi>{f.lang === "fa" ? p.name_en : p.name_fa}</Bdi>}
          {p.hs_code && <Bdi ltr className="font-mono">HS {p.hs_code}</Bdi>}
          {p.status === "archived" && <Badge>{t("parties.archived")}</Badge>}
        </span>}
        actions={<>
          <Button icon="edit" onClick={() => setEditing(true)}>{t("common.edit")}</Button>
          <Button onClick={() => archive.mutate(p.status === "archived")}>{p.status === "archived" ? t("parties.unarchive") : t("parties.archive")}</Button>
          <Button variant="ghost" onClick={() => remove.mutate()}>{t("delete.button")}</Button>
        </>} />
      <ErrorNote error={archive.error || remove.error} />
      {editing && <EditProductDialog product={p} onClose={() => setEditing(false)} onSaved={refresh} />}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card padded={false} title={t("sourcing.catalog.priceMemory")}>
            {p.prices.summary.length === 0 ? <EmptyState>{t("sourcing.catalog.noPrices")}</EmptyState> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
                    <th className="p-2 text-start">{t("sourcing.currency")}</th><th className="p-2 text-start">{t("sourcing.catalog.unitGroup")}</th>
                    <th className="p-2 text-start">{t("sourcing.catalog.period")}</th><th className="p-2 text-start">{t("sourcing.catalog.count")}</th>
                    <th className="p-2 text-start">{t("sourcing.catalog.min")}</th><th className="p-2 text-start">{t("sourcing.catalog.median")}</th><th className="p-2 text-start">{t("sourcing.catalog.max")}</th>
                  </tr></thead>
                  <tbody>
                    {p.prices.summary.flatMap((s) => (["all_time", "last_12_months"] as const).map((period) => (
                      <tr key={`${s.currency}${s.unit_group}${period}`} className="border-b border-line">
                        <td className="p-2"><Bdi ltr>{s.currency}</Bdi></td><td className="p-2">{groupLabel(s.unit_group)}</td>
                        <td className="p-2">{t(`sourcing.catalog.periods.${period}`)}</td><td className="p-2 tabular-nums">{f.num(s[period].count)}</td>
                        {(["min", "median", "max"] as const).map((k) => <td key={k} className="p-2 whitespace-nowrap"><Bdi ltr className="tabular-nums">{s[period][k] !== null ? `${f.num(s[period][k], 6)} ${perBase(s.unit_group)}` : "—"}</Bdi></td>)}
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Card padded={false} title={t("sourcing.catalog.allOffers")}>
            {p.prices.offers.length === 0 ? <EmptyState>{t("sourcing.catalog.noPrices")}</EmptyState> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
                    <th className="p-2 text-start">{t("sourcing.offer.received")}</th><th className="p-2 text-start">{t("sourcing.offer.supplier")}</th>
                    <th className="p-2 text-start">{t("sourcing.offer.unitPrice")}</th><th className="p-2 text-start">{t("sourcing.incoterm")}</th>
                    <th className="p-2 text-start">{t("sourcing.offer.moq")}</th><th className="p-2 text-start">{t("sourcing.item.quantity")}</th><th className="p-2 text-start">{t("sourcing.offer.validUntil")}</th>
                  </tr></thead>
                  <tbody>
                    {p.prices.offers.map((o) => (
                      <tr key={o.id} className="border-b border-line">
                        <td className="p-2 tabular-nums text-muted"><Link to={`/cases/${o.case_id}?tab=offers&offer=${o.offer_id}`} className="hover:underline">{f.date(o.received_at)}</Link></td>
                        <td className="p-2"><PartyName fa={o.party_fa} en={o.party_en} id={o.party_id} className="max-w-48" /><ContactName fa={o.contact_fa} en={o.contact_en} className="block max-w-48 text-xs" /></td>
                        <td className="p-2"><Money amount={o.unit_price} currency={o.currency} per={o.price_per_quantity} unit={unitLabel(o.unit_code, o.unit_text)} /></td>
                        <td className="p-2"><Bdi ltr>{[o.incoterm, o.incoterm_place].filter(Boolean).join(" ")}</Bdi></td>
                        <td className="p-2"><Bdi ltr>{o.moq ? `${f.num(o.moq)} ${o.moq_unit ?? ""}` : ""}</Bdi></td>
                        <td className="p-2 tabular-nums">{o.quantity ? f.num(o.quantity) : ""}</td>
                        <td className="p-2 tabular-nums">{o.valid_until ? f.day(o.valid_until) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Card title={t("sourcing.catalog.demand")}>
            <div className="mb-3 flex flex-wrap gap-4 text-sm">
              <span>{t("sourcing.catalog.inquiries")}: <b className="tabular-nums">{f.num(p.demand.inquiries)}</b></span>
              <span>{t("sourcing.catalog.cases")}: <b className="tabular-nums">{f.num(p.demand.cases)}</b></span>
              <span>{t("sourcing.catalog.lastRequested")}: <span className="tabular-nums">{f.date(p.demand.last_requested)}</span></span>
            </div>
            {p.demand.quantity_by_month.length > 0 && (
              <table className="mb-3 w-full text-sm">
                <thead><tr className="text-xs text-muted"><th className="p-1 text-start">{t("sourcing.catalog.month")}</th><th className="p-1 text-start">{t("sourcing.catalog.unitGroup")}</th><th className="p-1 text-start">{t("sourcing.item.quantity")}</th></tr></thead>
                <tbody>{p.demand.quantity_by_month.map((m) => (
                  <tr key={m.month + m.unit_group} className="border-t border-line"><td className="p-1"><Bdi ltr className="tabular-nums">{m.month}</Bdi></td><td className="p-1">{groupLabel(m.unit_group)}</td>
                    <td className="p-1"><Bdi ltr className="tabular-nums">{f.num(m.quantity)} {baseUnit[m.unit_group] ? unitLabel(baseUnit[m.unit_group]) : ""}</Bdi></td></tr>
                ))}</tbody>
              </table>
            )}
            <ul className="flex flex-wrap gap-2">{p.demand.buyers.map((b) => (
              <li key={b.party_id} className="flex items-center gap-1 text-sm"><PartyName fa={b.name_fa} en={b.name_en} id={b.party_id} /><span className="text-xs text-muted">×{f.num(b.requests)}</span></li>
            ))}</ul>
          </Card>
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <Card title={t("sourcing.catalog.aliases")}>
            <ul className="mb-2 flex flex-wrap gap-1.5">
              {p.aliases.map((a) => (
                <li key={a.id} className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-sm"><Bdi>{a.alias}</Bdi>
                  <button type="button" aria-label={t("delete.button")} className="text-muted hover:text-danger" onClick={() => removeAlias.mutate(a.id)}><Icon name="x" size={12} /></button></li>
              ))}
            </ul>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (alias.trim()) addAlias.mutate(); }}>
              <Input dir="auto" aria-label={t("sourcing.catalog.alias")} placeholder={t("sourcing.catalog.aliasPlaceholder")} value={alias} onChange={(e) => setAlias(e.target.value)} />
              <Button type="submit" icon="plus" busy={addAlias.isPending}>{t("common.add")}</Button>
            </form>
            <ErrorNote error={addAlias.error || removeAlias.error} />
          </Card>
          <Card padded={false} title={t("sourcing.catalog.suppliersByOffers")}>
            {p.suppliers_by_offers.length === 0 ? <EmptyState>{t("sourcing.catalog.noSuppliers")}</EmptyState> : (
              <ul className="divide-y divide-line">{p.suppliers_by_offers.map((s) => (
                <li key={s.party_id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
                  <PartyName fa={s.name_fa} en={s.name_en} id={s.party_id} />
                  <span className="text-xs text-muted">{t("sourcing.catalog.offersCount", { count: s.offers })}</span>
                  <span className="ms-auto"><Money amount={s.last_price} currency={s.currency} per={s.price_per_quantity} unit={unitLabel(s.unit_code, s.unit_text)} /></span>
                </li>
              ))}</ul>
            )}
          </Card>
          <Card padded={false} title={t("sourcing.catalog.suppliersByCapability")}>
            {p.suppliers_by_capability.length === 0 ? <EmptyState>{p.hs_code ? t("sourcing.catalog.noSuppliers") : t("sourcing.catalog.noHs")}</EmptyState> : (
              <ul className="divide-y divide-line">{p.suppliers_by_capability.map((s) => (
                <li key={s.party_id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
                  <PartyName fa={s.name_fa} en={s.name_en} id={s.party_id} />
                  {s.supplier_stage && <Badge>{stageLabel(t, "supplier", s.supplier_stage)}</Badge>}
                  <Badge tone="accent">{t(`sourcing.rfq.match.${s.match}`)} <Bdi ltr className="ms-1">{(s.codes ?? []).join(", ")}</Bdi></Badge>
                </li>
              ))}</ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
