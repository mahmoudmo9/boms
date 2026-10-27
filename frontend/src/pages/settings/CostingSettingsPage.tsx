/** Settings -> Costing: tax parameters (rates are data, a new rate is a new row) and cost templates. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, Input, Modal, PageHeader, Select } from "../../components/ui";
import { DateInput } from "../../components/DateInput";
import { api } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import type { CostTemplate, CostTemplateLine, DealType, TaxKind, TaxParameter } from "../../lib/types";

const KINDS = ["purchase", "freight_international", "insurance", "bank_fees", "customs_duty", "levy", "customs_clearance",
  "storage", "inspection", "freight_domestic", "export_clearance", "vat", "other"] as const;
const BASES = ["total", "per_unit", "percent_of_cif", "percent_of_purchase"] as const;
const ALLOCATIONS = ["by_value", "by_quantity", "equal", "manual"] as const;

function NewParameterDialog({ kinds, onClose, onSaved }: { kinds: TaxKind[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [form, setForm] = useState({ kind: "duty_default", name: "", rate_percent: "", deal_type: "all", effective_from: toDateString(new Date()) as string | null, note: "" });
  const save = useMutation({
    mutationFn: () => api("/api/tax-parameters", { method: "POST", body: { ...form, note: form.note || null } }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  return (
    <Modal open title={t("costing.params.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={save.isPending} disabled={!form.name.trim() || !form.rate_percent || !form.effective_from} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("costing.params.kind")} htmlFor="tp-kind">
          <Select id="tp-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {kinds.map((k) => <option key={k.code} value={k.code}>{f.lang === "fa" ? k.label_fa : k.label_en}</option>)}
          </Select>
        </Field>
        <Field label={t("costing.params.dealType")} htmlFor="tp-deal">
          <Select id="tp-deal" value={form.deal_type} onChange={(e) => setForm({ ...form, deal_type: e.target.value })}>
            {["all", "import", "export", "domestic"].map((d) => <option key={d} value={d}>{t(`costing.dealTypes.${d}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("costing.params.name")} htmlFor="tp-name"><Input id="tp-name" dir="auto" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={t("costing.params.rate")} htmlFor="tp-rate"><Input id="tp-rate" dir="ltr" inputMode="decimal" value={form.rate_percent} onChange={(e) => setForm({ ...form, rate_percent: e.target.value })} /></Field>
        <Field label={t("costing.params.from")} htmlFor="tp-from"><DateInput id="tp-from" value={form.effective_from ? fromDateString(form.effective_from) : null} onChange={(d) => setForm({ ...form, effective_from: d ? toDateString(d) : null })} /></Field>
        <Field label={t("parties.notes")} htmlFor="tp-note"><Input id="tp-note" dir="auto" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
      </div>
      <p className="mt-2 text-xs text-muted">{t("costing.params.newRowHint")}</p>
      <ErrorNote error={save.error} />
    </Modal>
  );
}

function ConfirmDialog({ param, onClose, onSaved }: { param: TaxParameter; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [by, setBy] = useState("");
  const [on, setOn] = useState<string | null>(toDateString(new Date()));
  const save = useMutation({
    mutationFn: () => api(`/api/tax-parameters/${param.id}`, { method: "PATCH", body: { confirmed_by: by, confirmed_on: on } }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  return (
    <Modal open title={t("costing.params.confirm")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={save.isPending} disabled={!by.trim() || !on} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3">
        <p className="text-sm">{param.name} · {param.rate_percent} %</p>
        <Field label={t("costing.params.confirmedBy")} htmlFor="pc-by"><Input id="pc-by" dir="auto" value={by} onChange={(e) => setBy(e.target.value)} /></Field>
        <Field label={t("costing.params.confirmedOn")} htmlFor="pc-on"><DateInput id="pc-on" value={on ? fromDateString(on) : null} onChange={(d) => setOn(d ? toDateString(d) : null)} /></Field>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

function ParametersCard() {
  const { t } = useTranslation();
  const f = useFormat();
  const kinds = useQuery({ queryKey: ["tax-kinds"], queryFn: () => api<TaxKind[]>("/api/tax-parameters/kinds") });
  const params = useQuery({ queryKey: ["tax-parameters"], queryFn: () => api<TaxParameter[]>("/api/tax-parameters") });
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<TaxParameter | null>(null);
  const end = useMutation({ mutationFn: (p: TaxParameter) => api(`/api/tax-parameters/${p.id}`, { method: "PATCH", body: { effective_to: toDateString(new Date()) } }), onSuccess: () => void params.refetch() });
  const kindLabel = (code: string) => { const k = kinds.data?.find((x) => x.code === code); return k ? (f.lang === "fa" ? k.label_fa : k.label_en) : code; };
  return (
    <Card padded={false} title={t("costing.params.title")} actions={<Button icon="plus" onClick={() => setAdding(true)}>{t("costing.params.new")}</Button>}>
      <p className="px-4 pt-3 text-xs text-muted">{t("costing.params.hint")}</p>
      {(params.data ?? []).length === 0 ? <EmptyState>{t("costing.params.none")}</EmptyState> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line text-xs text-muted">
              {["kind", "name", "rate", "dealType", "period", "confirmed", ""].map((h) => <th key={h} className="p-2 text-start">{h ? t(`costing.params.columns.${h}`) : ""}</th>)}
            </tr></thead>
            <tbody>{(params.data ?? []).map((p) => (
              <tr key={p.id} className="border-b border-line">
                <td className="p-2">{kindLabel(p.kind)}</td><td className="p-2" dir="auto">{p.name}</td>
                <td className="p-2 tabular-nums">{f.num(p.rate_percent)} %</td><td className="p-2">{t(`costing.dealTypes.${p.deal_type}`)}</td>
                <td className="p-2 tabular-nums">{f.day(p.effective_from)} – {p.effective_to ? f.day(p.effective_to) : "…"}</td>
                <td className="p-2">{p.confirmed_on ? <span className="text-xs"><span dir="auto">{p.confirmed_by}</span> · <span className="tabular-nums">{f.day(p.confirmed_on)}</span></span>
                  : <Badge tone="warning">{t("costing.params.unconfirmed")}</Badge>}</td>
                <td className="p-2 text-end whitespace-nowrap">
                  {!p.confirmed_on && <Button variant="ghost" onClick={() => setConfirming(p)}>{t("costing.params.confirm")}</Button>}
                  {!p.effective_to && <Button variant="ghost" onClick={() => end.mutate(p)}>{t("costing.params.end")}</Button>}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <ErrorNote error={params.error || end.error} />
      {adding && kinds.data && <NewParameterDialog kinds={kinds.data} onClose={() => setAdding(false)} onSaved={() => void params.refetch()} />}
      {confirming && <ConfirmDialog param={confirming} onClose={() => setConfirming(null)} onSaved={() => void params.refetch()} />}
    </Card>
  );
}

function TemplateEditor({ template, onClose, onSaved }: { template: CostTemplate | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState(template?.name ?? "");
  const [nameFa, setNameFa] = useState(template?.name_fa ?? "");
  const [dealType, setDealType] = useState<DealType>(template?.deal_type ?? "import");
  const [isDefault, setIsDefault] = useState(template?.is_default ?? false);
  const [lines, setLines] = useState<CostTemplateLine[]>(template?.lines.map(({ id: _id, ...l }) => l) ?? []);
  const setLine = (i: number, patch: Partial<CostTemplateLine>) => setLines(lines.map((l, j) => (i === j ? { ...l, ...patch } : l)));
  const move = (i: number, d: number) => { const next = [...lines]; const [x] = next.splice(i, 1); next.splice(i + d, 0, x); setLines(next); };
  const body = { name, name_fa: nameFa || null, is_default: isDefault, lines };
  const save = useMutation({
    mutationFn: () => (template ? api(`/api/cost-templates/${template.id}`, { method: "PATCH", body })
      : api("/api/cost-templates", { method: "POST", body: { ...body, deal_type: dealType } })),
    onSuccess: () => { onSaved(); onClose(); },
  });
  return (
    <Modal open wide title={template ? t("costing.templates.edit") : t("costing.templates.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="flex max-h-[68vh] flex-col gap-3 overflow-y-auto pe-1">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("costing.templates.name")} htmlFor="ct-name"><Input id="ct-name" dir="ltr" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("costing.templates.nameFa")} htmlFor="ct-namefa"><Input id="ct-namefa" dir="rtl" value={nameFa} onChange={(e) => setNameFa(e.target.value)} /></Field>
          <Field label={t("costing.dealType")} htmlFor="ct-deal">
            <Select id="ct-deal" className="w-auto min-w-32" value={dealType} disabled={!!template} onChange={(e) => setDealType(e.target.value as DealType)}>
              {(["import", "export", "domestic"] as const).map((d) => <option key={d} value={d}>{t(`costing.dealTypes.${d}`)}</option>)}
            </Select>
          </Field>
        </div>
        <Checkbox label={t("costing.templates.default")} checked={isDefault} onChange={setIsDefault} />
        <ol className="flex flex-col gap-1.5">
          {lines.map((l, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1.5 rounded-md bg-surface-2 p-1.5">
              <span className="w-6 text-xs text-muted tabular-nums">{i + 1}</span>
              <Select className="w-auto min-w-36" aria-label={t("costing.lines.kind")} value={l.kind} onChange={(e) => setLine(i, { kind: e.target.value as CostTemplateLine["kind"] })}>
                {KINDS.map((k) => <option key={k} value={k}>{t(`costing.kinds.${k}`)}</option>)}
              </Select>
              <Input dir="ltr" className="w-40" aria-label={t("costing.templates.labelEn")} placeholder={t("costing.templates.labelEn")} value={l.label_en ?? ""} onChange={(e) => setLine(i, { label_en: e.target.value || null })} />
              <Input dir="rtl" className="w-40" aria-label={t("costing.templates.labelFa")} placeholder={t("costing.templates.labelFa")} value={l.label_fa ?? ""} onChange={(e) => setLine(i, { label_fa: e.target.value || null })} />
              <Select className="w-auto min-w-32" aria-label={t("costing.lines.basis")} value={l.basis} onChange={(e) => setLine(i, { basis: e.target.value as CostTemplateLine["basis"] })}>
                {BASES.map((b) => <option key={b} value={b}>{t(`costing.bases.${b}`)}</option>)}
              </Select>
              <Select className="w-auto min-w-28" aria-label={t("costing.lines.allocation")} value={l.allocation} onChange={(e) => setLine(i, { allocation: e.target.value as CostTemplateLine["allocation"] })}>
                {ALLOCATIONS.map((a) => <option key={a} value={a}>{t(`costing.allocations.${a}`)}</option>)}
              </Select>
              <Checkbox label={t("costing.lines.paidBefore")} checked={l.paid_before_receipt} onChange={(v) => setLine(i, { paid_before_receipt: v })} />
              <span className="ms-auto flex gap-1">
                <Button variant="ghost" disabled={i === 0} aria-label={t("costing.templates.up")} onClick={() => move(i, -1)}>↑</Button>
                <Button variant="ghost" disabled={i === lines.length - 1} aria-label={t("costing.templates.down")} onClick={() => move(i, 1)}>↓</Button>
                <Button variant="ghost" onClick={() => setLines(lines.filter((_, j) => j !== i))}>{t("common.remove")}</Button>
              </span>
            </li>
          ))}
        </ol>
        <div><Button icon="plus" onClick={() => setLines([...lines, { kind: "other", label_en: "", label_fa: null, basis: "total", allocation: "by_value", paid_before_receipt: false, tax_kind: null }])}>{t("costing.lines.add")}</Button></div>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

function TemplatesCard() {
  const { t } = useTranslation();
  const f = useFormat();
  const templates = useQuery({ queryKey: ["cost-templates", "all"], queryFn: () => api<CostTemplate[]>("/api/cost-templates", { query: { include_archived: true } }) });
  const [editing, setEditing] = useState<CostTemplate | "new" | null>(null);
  const archive = useMutation({ mutationFn: (x: CostTemplate) => api(`/api/cost-templates/${x.id}`, { method: "PATCH", body: { status: x.status === "active" ? "archived" : "active" } }), onSuccess: () => void templates.refetch() });
  return (
    <Card padded={false} title={t("costing.templates.title")} actions={<Button icon="plus" onClick={() => setEditing("new")}>{t("costing.templates.new")}</Button>}>
      <ul className="divide-y divide-line">
        {(templates.data ?? []).map((x) => (
          <li key={x.id} className={`flex flex-wrap items-center gap-2 px-4 py-2 text-sm ${x.status === "archived" ? "opacity-60" : ""}`}>
            <button type="button" className="font-medium text-accent hover:underline" onClick={() => setEditing(x)}>{f.lang === "fa" ? x.name_fa || x.name : x.name}</button>
            <Badge>{t(`costing.dealTypes.${x.deal_type}`)}</Badge>
            {x.is_default && <Badge tone="success">{t("costing.templates.isDefault")}</Badge>}
            <span className="text-xs text-muted">{t("costing.templates.lines", { count: x.lines.length, n: f.num(x.lines.length) })}</span>
            <Button variant="ghost" className="ms-auto" onClick={() => archive.mutate(x)}>{x.status === "active" ? t("parties.archive") : t("parties.unarchive")}</Button>
          </li>
        ))}
      </ul>
      <ErrorNote error={templates.error || archive.error} />
      {editing && <TemplateEditor template={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => void templates.refetch()} />}
    </Card>
  );
}

export function CostingSettingsPage() {
  const { t } = useTranslation();
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <PageHeader title={t("nav.sub.costing")} subtitle={t("costing.settingsSubtitle")} />
      <ParametersCard />
      <TemplatesCard />
    </div>
  );
}
