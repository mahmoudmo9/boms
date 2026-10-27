/** Costing tab: versioned cost sheets (lines grid, FX, cost of money, pricing, breakdown, quote gate). Every number
 * comes from the server; the page only sends what the owner typed. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Loading, Modal, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { gateChecklist, gridTarget, marginMarkupView } from "../../lib/costing";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import type { CaseCosting, CaseDetail, CostLine, CostSheet, CostTemplate, CostGate, DealType, GateFailure, Quote, TaxParameter } from "../../lib/types";
import { CurrencySelect, Money, StatusBadge, useInvalidateSourcing } from "../sourcing/shared";

const KINDS = ["purchase", "freight_international", "insurance", "bank_fees", "customs_duty", "levy", "customs_clearance",
  "storage", "inspection", "freight_domestic", "export_clearance", "vat", "other"] as const;
const BASES = ["total", "per_unit", "percent_of_cif", "percent_of_purchase"] as const;
const ALLOCATIONS = ["by_value", "by_quantity", "equal", "manual"] as const;
const DEAL_TYPES: DealType[] = ["import", "export", "domestic"];

/** Text input that keeps its own value while typing and sends it on blur / Enter (only when changed). */
function CommitInput({ value, onCommit, disabled, grid, rows, ...rest }: {
  value: string | null;
  onCommit: (v: string | null) => void;
  disabled?: boolean;
  grid?: { row: number; column: string };
  rows?: number;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => { setText(value ?? ""); }, [value]);
  const commit = () => { const v = text.trim() === "" ? null : text.trim(); if (v !== (value ?? null)) onCommit(v); };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!grid || rows === undefined) return;
    const target = gridTarget(e.key, grid.row, grid.column, rows);
    if (target) {
      e.preventDefault();
      commit();
      const el = document.querySelector<HTMLInputElement>(`[data-grid="${target}"]`);
      el?.focus();
      el?.select();
    }
  };
  return <Input {...rest} disabled={disabled} value={text} data-grid={grid ? `${grid.row}-${grid.column}` : undefined}
    onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={onKeyDown} />;
}

type Body = Record<string, unknown>;

function useSheetMutations(sheetId: string, onDone: () => void) {
  return {
    patchSheet: useMutation({ mutationFn: (body: Body) => api(`/api/cost-sheets/${sheetId}`, { method: "PATCH", body }), onSuccess: onDone }),
    patchLine: useMutation({ mutationFn: ({ id, body }: { id: string; body: Body }) => api(`/api/cost-sheets/lines/${id}`, { method: "PATCH", body }), onSuccess: onDone }),
    addLine: useMutation({ mutationFn: (body: Body) => api(`/api/cost-sheets/${sheetId}/lines`, { method: "POST", body }), onSuccess: onDone }),
    deleteLine: useMutation({ mutationFn: (id: string) => api(`/api/cost-sheets/lines/${id}`, { method: "DELETE" }), onSuccess: onDone }),
    setFx: useMutation({ mutationFn: (body: Body) => api(`/api/cost-sheets/${sheetId}/fx`, { method: "PUT", body }), onSuccess: onDone }),
    deleteFx: useMutation({ mutationFn: (id: string) => api(`/api/cost-sheets/fx/${id}`, { method: "DELETE" }), onSuccess: onDone }),
  };
}

function NewSheetDialog({ caseData, onClose, onCreated }: { caseData: CaseDetail; onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [dealType, setDealType] = useState<DealType>("import");
  const [currency, setCurrency] = useState<string | null>("IRR");
  const [template, setTemplate] = useState<string>("");
  const templates = useQuery({ queryKey: ["cost-templates"], queryFn: () => api<CostTemplate[]>("/api/cost-templates") });
  const options = (templates.data ?? []).filter((x) => x.deal_type === dealType);
  const create = useMutation({
    mutationFn: () => api<CostSheet>("/api/cost-sheets", { method: "POST", body: {
      case_id: caseData.id, deal_type: dealType, pricing_currency: currency, language: f.lang,
      ...(template === "blank" ? { blank: true } : template ? { template_id: template } : {}) } }),
    onSuccess: (s) => { onCreated(s.id); onClose(); },
  });
  return (
    <Modal open title={t("costing.newSheet")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={create.isPending} disabled={!currency} onClick={() => create.mutate()}>{t("costing.create")}</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label={t("costing.dealType")} htmlFor="ns-deal">
          <Select id="ns-deal" className="w-auto min-w-40" value={dealType} onChange={(e) => { setDealType(e.target.value as DealType); setTemplate(""); }}>
            {DEAL_TYPES.map((d) => <option key={d} value={d}>{t(`costing.dealTypes.${d}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("costing.pricingCurrency")} htmlFor="ns-cur" hint={t("costing.pricingCurrencyHint")}>
          <CurrencySelect id="ns-cur" allowEmpty={false} value={currency} onChange={setCurrency} />
        </Field>
        <Field label={t("costing.template")} htmlFor="ns-tpl">
          <Select id="ns-tpl" className="w-auto min-w-56" value={template} onChange={(e) => setTemplate(e.target.value)}>
            <option value="">{t("costing.defaultTemplate")}</option>
            {options.map((x) => <option key={x.id} value={x.id}>{f.lang === "fa" ? x.name_fa || x.name : x.name}</option>)}
            <option value="blank">{t("costing.blankSheet")}</option>
          </Select>
        </Field>
        <p className="text-xs text-muted">{t("costing.prefillHint")}</p>
        <ErrorNote error={create.error} />
      </div>
    </Modal>
  );
}

function FxCard({ sheet, editable, onChanged }: { sheet: CostSheet; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useSheetMutations(sheet.id, onChanged);
  const kinds = useQuery({ queryKey: ["cost-sheets", "rate-kinds"], queryFn: () => api<string[]>("/api/cost-sheets/rate-kinds") });
  const used = new Set((sheet.computation?.fx_used ?? []).map((x) => `${x.from_currency}-${x.to_currency}`));
  const missing = sheet.compute_error?.code === "fx_missing" ? sheet.compute_error.details as { from_currency: string; to_currency: string } : null;
  const [form, setForm] = useState({ from_currency: missing?.from_currency ?? "USD" as string | null, rate: "", rate_kind: "", source_note: "", as_of: toDateString(new Date()) as string | null });
  useEffect(() => { if (missing) setForm((x) => ({ ...x, from_currency: missing.from_currency })); }, [missing?.from_currency]);
  return (
    <Card title={t("costing.fx.title")}>
      {missing && <p className="mb-2 rounded-md bg-danger-soft px-2.5 py-1.5 text-sm text-danger" role="alert">
        {t("costing.fx.missing", { pair: `${missing.from_currency} → ${missing.to_currency}` })}</p>}
      {sheet.fx.length === 0 ? <EmptyState>{t("costing.fx.none")}</EmptyState> : (
        <ul className="mb-3 flex flex-col gap-1 text-sm">
          {sheet.fx.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-2">
              <Bdi ltr className="font-mono">{x.from_currency} → {x.to_currency}</Bdi>
              <Bdi ltr className="tabular-nums">{f.num(x.rate, 10)}</Bdi>
              {x.rate_kind && <Badge>{x.rate_kind}</Badge>}
              <span className="text-xs text-muted tabular-nums">{f.day(x.as_of)}</span>
              {x.source_note && <span className="text-xs text-muted" dir="auto">{x.source_note}</span>}
              {used.has(`${x.from_currency}-${x.to_currency}`) && <Badge tone="accent">{t("costing.fx.used")}</Badge>}
              {editable && <button type="button" className="ms-auto text-xs text-danger hover:underline" onClick={() => m.deleteFx.mutate(x.id)}>{t("delete.button")}</button>}
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <form className="grid gap-2 sm:grid-cols-[auto_auto_minmax(0,1fr)_minmax(0,1fr)] sm:items-end" onSubmit={(e) => {
          e.preventDefault();
          m.setFx.mutate({ from_currency: form.from_currency, to_currency: sheet.pricing_currency, rate: form.rate, as_of: form.as_of,
            rate_kind: form.rate_kind || null, source_note: form.source_note || null });
        }}>
          <Field label={t("costing.fx.from")} htmlFor="fx-from"><CurrencySelect id="fx-from" allowEmpty={false} value={form.from_currency} onChange={(v) => setForm({ ...form, from_currency: v })} /></Field>
          <Field label={t("costing.fx.rate", { to: sheet.pricing_currency })} htmlFor="fx-rate"><Input id="fx-rate" dir="ltr" inputMode="decimal" className="w-36" value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} /></Field>
          <Field label={t("costing.fx.kind")} htmlFor="fx-kind">
            <Input id="fx-kind" dir="auto" list="fx-kinds" value={form.rate_kind} placeholder={t("costing.fx.kindPlaceholder")} onChange={(e) => setForm({ ...form, rate_kind: e.target.value })} />
            <datalist id="fx-kinds">{(kinds.data ?? []).map((k) => <option key={k} value={k} />)}</datalist>
          </Field>
          <Field label={t("costing.fx.source")} htmlFor="fx-src"><Input id="fx-src" dir="auto" value={form.source_note} onChange={(e) => setForm({ ...form, source_note: e.target.value })} /></Field>
          <Field label={t("costing.fx.asOf")} htmlFor="fx-asof"><DateInput id="fx-asof" value={form.as_of ? fromDateString(form.as_of) : null} onChange={(d) => setForm({ ...form, as_of: d ? toDateString(d) : null })} /></Field>
          <div><Button type="submit" busy={m.setFx.isPending} disabled={!form.rate || !form.as_of || form.from_currency === sheet.pricing_currency}>{t("costing.fx.save")}</Button></div>
        </form>
      )}
      <ErrorNote error={m.setFx.error || m.deleteFx.error} />
    </Card>
  );
}

function LineRow({ line, index, rows, sheet, editable, params, onChanged }: {
  line: CostLine; index: number; rows: number; sheet: CostSheet; editable: boolean; params: TaxParameter[]; onChanged: () => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useSheetMutations(sheet.id, onChanged);
  const patch = (body: Record<string, unknown>) => m.patchLine.mutate({ id: line.id, body });
  const computed = sheet.computation?.lines.find((x) => x.line_id === line.id);
  const percent = line.basis.startsWith("percent");
  const item = sheet.items.find((i) => i.id === line.line_item_id);
  const tip = computed ? [
    computed.fx ? `${computed.fx.from_currency}→${computed.fx.to_currency} ${computed.fx.rate} (${computed.fx.as_of})` : "",
    ...Object.entries(computed.shares).map(([id, a]) => `${sheet.items.find((i) => i.id === id)?.name ?? id}: ${a}`),
  ].filter(Boolean).join("\n") : "";
  const warn = sheet.warnings.filter((w) => w.line_id === line.id);
  return (
    <tr className="border-b border-line align-top">
      <td className="p-1.5 text-xs text-muted">{t(`costing.kinds.${line.kind}`)}</td>
      <td className="p-1.5">
        <CommitInput dir="auto" className="min-w-40" aria-label={t("costing.lines.label")} value={line.label} disabled={!editable} onCommit={(v) => v && patch({ label: v })} />
        {item && <div className="mt-0.5 text-xs text-muted"><Bdi>{item.name}</Bdi>{line.source_offer_item_id && <> · {t("costing.lines.fromOffer")}</>}</div>}
        {warn.map((w) => <div key={w.code} className="mt-0.5 text-xs text-warning">{t(`costing.warnings.${w.code}`, { defaultValue: w.code })}</div>)}
      </td>
      <td className="p-1.5">
        <Select className="w-auto min-w-32" aria-label={t("costing.lines.basis")} value={line.basis} disabled={!editable}
          onChange={(e) => patch(e.target.value.startsWith("percent") ? { basis: e.target.value, amount: null, currency: null } : { basis: e.target.value, percent: null, tax_parameter_id: null })}>
          {BASES.map((b) => <option key={b} value={b}>{t(`costing.bases.${b}`)}</option>)}
        </Select>
      </td>
      <td className="p-1.5">
        {percent ? (
          <div className="flex flex-col gap-1">
            <CommitInput dir="ltr" inputMode="decimal" className="w-24" aria-label={t("costing.lines.percent")} value={line.percent} disabled={!editable}
              grid={{ row: index, column: "value" }} rows={rows} onCommit={(v) => patch({ percent: v })} />
            {(line.kind === "customs_duty" || line.kind === "levy" || line.kind === "vat" || line.tax_parameter_id) && (
              <Select className="w-auto min-w-32 text-xs" aria-label={t("costing.lines.parameter")} value={line.tax_parameter_id ?? ""} disabled={!editable}
                onChange={(e) => patch({ tax_parameter_id: e.target.value || null })}>
                <option value="">{t("costing.lines.noParameter")}</option>
                {params.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.rate_percent}% · {f.day(p.effective_from)}{p.confirmed_on ? "" : " ⚠"}</option>)}
              </Select>
            )}
          </div>
        ) : (
          <div className="flex gap-1">
            <CommitInput dir="ltr" inputMode="decimal" className="w-40" aria-label={t("costing.lines.amount")} value={line.amount} disabled={!editable}
              grid={{ row: index, column: "value" }} rows={rows} onCommit={(v) => patch({ amount: v, currency: line.currency ?? sheet.pricing_currency })} />
            <CurrencySelect className="w-24" value={line.currency} onChange={(v) => editable && patch({ currency: v })} />
          </div>
        )}
      </td>
      <td className="p-1.5">
        {line.scope === "case" && line.basis === "total" ? (
          <Select className="w-auto min-w-28" aria-label={t("costing.lines.allocation")} value={line.allocation} disabled={!editable}
            onChange={(e) => patch({ allocation: e.target.value })}>
            {ALLOCATIONS.map((a) => <option key={a} value={a}>{t(`costing.allocations.${a}`)}</option>)}
          </Select>
        ) : <span className="text-xs text-muted">{line.scope === "item" ? t("costing.lines.itemLine") : t("costing.lines.perItem")}</span>}
      </td>
      <td className="p-1.5 text-center">
        <input type="checkbox" aria-label={t("costing.lines.paidBefore")} className="h-4 w-4 accent-[var(--accent)]" checked={line.paid_before_receipt}
          disabled={!editable || line.kind === "purchase"} onChange={(e) => patch({ paid_before_receipt: e.target.checked })} />
      </td>
      <td className="p-1.5 text-end" title={tip}>{computed ? <Money amount={computed.total} currency={sheet.pricing_currency} /> : "—"}
        {computed?.vat && <div className="text-xs text-muted">{t("costing.lines.vatSeparate")}</div>}</td>
      <td className="p-1.5">{editable && <button type="button" className="text-xs text-danger hover:underline" onClick={() => m.deleteLine.mutate(line.id)}>{t("delete.button")}</button>}</td>
    </tr>
  );
}

function AddLineForm({ sheet, onChanged }: { sheet: CostSheet; onChanged: () => void }) {
  const { t } = useTranslation();
  const m = useSheetMutations(sheet.id, onChanged);
  const [kind, setKind] = useState<string>("other");
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState<string>("case");
  const [basis, setBasis] = useState<string>("total");
  return (
    <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => {
      e.preventDefault();
      m.addLine.mutate({ kind, label: label || t(`costing.kinds.${kind}`), scope: scope === "case" ? "case" : "item",
        line_item_id: scope === "case" ? null : scope, basis }, { onSuccess: () => setLabel("") });
    }}>
      <Select className="w-auto min-w-36" aria-label={t("costing.lines.kind")} value={kind} onChange={(e) => setKind(e.target.value)}>
        {KINDS.map((k) => <option key={k} value={k}>{t(`costing.kinds.${k}`)}</option>)}
      </Select>
      <Input dir="auto" className="w-48" aria-label={t("costing.lines.label")} placeholder={t("costing.lines.label")} value={label} onChange={(e) => setLabel(e.target.value)} />
      <Select className="w-auto min-w-36" aria-label={t("costing.lines.scope")} value={scope} onChange={(e) => setScope(e.target.value)}>
        <option value="case">{t("costing.lines.wholeCase")}</option>
        {sheet.items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
      </Select>
      <Select className="w-auto min-w-32" aria-label={t("costing.lines.basis")} value={basis} onChange={(e) => setBasis(e.target.value)}>
        {BASES.map((b) => <option key={b} value={b}>{t(`costing.bases.${b}`)}</option>)}
      </Select>
      <Button type="submit" icon="plus" busy={m.addLine.isPending}>{t("costing.lines.add")}</Button>
      <ErrorNote error={m.addLine.error} />
    </form>
  );
}

function LinesCard({ sheet, editable, onChanged }: { sheet: CostSheet; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  const params = useQuery({ queryKey: ["tax-parameters"], queryFn: () => api<TaxParameter[]>("/api/tax-parameters") });
  const applicable = (params.data ?? []).filter((p) => p.deal_type === "all" || p.deal_type === sheet.deal_type);
  return (
    <Card padded={false} title={t("costing.lines.title")}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
            {["kind", "label", "basis", "value", "allocation", "paidBefore", "computed", ""].map((h) => <th key={h} className="p-1.5 text-start whitespace-nowrap">{h ? t(`costing.lines.columns.${h}`) : ""}</th>)}
          </tr></thead>
          <tbody>{sheet.lines.map((line, i) => <LineRow key={line.id} line={line} index={i} rows={sheet.lines.length} sheet={sheet} editable={editable} params={applicable} onChanged={onChanged} />)}</tbody>
        </table>
      </div>
      <div className="px-4 py-2">
        <p className="text-xs text-muted">{t("costing.lines.gridHint")}</p>
        {editable && <AddLineForm sheet={sheet} onChanged={onChanged} />}
      </div>
    </Card>
  );
}

function PercentField({ id, label, value, onCommit, disabled, suffix = "%" }: { id: string; label: string; value: string | number | null; onCommit: (v: string | null) => void; disabled: boolean; suffix?: string }) {
  return (
    <Field label={label} htmlFor={id}>
      <div className="flex items-center gap-1"><CommitInput id={id} dir="ltr" inputMode="decimal" className="w-24" value={value === null ? null : String(value)} disabled={disabled} onCommit={onCommit} /><span className="text-xs text-muted">{suffix}</span></div>
    </Field>
  );
}

function MoneyTimeCard({ sheet, editable, onChanged }: { sheet: CostSheet; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  const m = useSheetMutations(sheet.id, onChanged);
  const c = sheet.computation;
  const set = (key: string, number = false) => (v: string | null) => m.patchSheet.mutate({ [key]: v === null ? 0 : number ? Number(v) : v });
  return (
    <Card title={t("costing.money.title")}>
      <div className="grid gap-3 sm:grid-cols-3">
        <PercentField id="cm-sp" label={t("costing.money.supplierPrepay")} value={sheet.supplier_prepay_percent} disabled={!editable} onCommit={set("supplier_prepay_percent")} />
        <PercentField id="cm-cp" label={t("costing.money.customerPrepay")} value={sheet.customer_prepay_percent} disabled={!editable} onCommit={set("customer_prepay_percent")} />
        <PercentField id="cm-days" label={t("costing.money.days")} value={sheet.days_from_payment_to_receipt} disabled={!editable} onCommit={set("days_from_payment_to_receipt", true)} suffix={t("settings.days")} />
        <PercentField id="cm-rate" label={t("costing.money.annualRate")} value={sheet.annual_cost_of_money_percent} disabled={!editable} onCommit={set("annual_cost_of_money_percent")} />
        <PercentField id="cm-g" label={t("costing.money.guarantee")} value={sheet.guarantee_percent} disabled={!editable} onCommit={set("guarantee_percent")} />
        <PercentField id="cm-gd" label={t("costing.money.guaranteeDays")} value={sheet.guarantee_days} disabled={!editable} onCommit={set("guarantee_days", true)} suffix={t("settings.days")} />
      </div>
      {c && (
        <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
          <dt className="text-muted">{t("costing.money.exposure")}</dt>
          <dd title={`${t("costing.money.supplierPrepayment")}: ${c.exposure.supplier_prepayment}\n${t("costing.money.paidBefore")}: ${c.exposure.paid_before_receipt}\n${t("costing.money.customerPrepayment")}: −${c.exposure.customer_prepayment}`}>
            <Money amount={c.exposure.exposure} currency={c.currency} /></dd>
          <dt className="text-muted">{t("costing.money.costOfMoney")}</dt>
          <dd title={`${c.cost_of_money.cash_tied_up} × ${c.cost_of_money.annual_percent}% × ${c.cost_of_money.days} / 365`}><Money amount={c.cost_of_money.amount} currency={c.currency} /></dd>
          <dt className="text-muted">{t("costing.money.guaranteeCost")}</dt>
          <dd><Money amount={c.guarantee.amount} currency={c.currency} /></dd>
        </dl>
      )}
      <p className="mt-2 text-xs text-muted">{t("costing.money.hint")}</p>
      <ErrorNote error={m.patchSheet.error} />
    </Card>
  );
}

function PricingCard({ sheet, editable, onChanged }: { sheet: CostSheet; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useSheetMutations(sheet.id, onChanged);
  const c = sheet.computation;
  const [open, setOpen] = useState<string | null>(null);
  const totals = c ? marginMarkupView(c.totals, (v) => f.num(v, 2)) : null;
  return (
    <Card padded={false} title={t("costing.pricing.title")}>
      <div className="flex flex-wrap items-end gap-3 px-4 py-3">
        <Field label={t("costing.pricing.method")} htmlFor="pr-method">
          <Select id="pr-method" className="w-auto min-w-28" value={sheet.pricing_method} disabled={!editable} onChange={(e) => m.patchSheet.mutate({ pricing_method: e.target.value })}>
            <option value="margin">{t("costing.pricing.margin")}</option><option value="markup">{t("costing.pricing.markup")}</option>
          </Select>
        </Field>
        <PercentField id="pr-target" label={t("costing.pricing.target")} value={sheet.target_percent} disabled={!editable} onCommit={(v) => m.patchSheet.mutate({ target_percent: v })} />
        <Field label={t("costing.pricing.rounding")} htmlFor="pr-round">
          <div className="flex gap-1">
            <Select id="pr-round" className="w-auto min-w-28" value={sheet.rounding} disabled={!editable}
              onChange={(e) => m.patchSheet.mutate({ rounding: e.target.value, rounding_step: e.target.value === "none" ? null : sheet.rounding_step ?? "1000" })}>
              {(["none", "nearest", "up"] as const).map((r) => <option key={r} value={r}>{t(`costing.pricing.roundings.${r}`)}</option>)}
            </Select>
            {sheet.rounding !== "none" && <CommitInput dir="ltr" inputMode="decimal" className="w-24" aria-label={t("costing.pricing.step")} value={sheet.rounding_step} disabled={!editable} onCommit={(v) => m.patchSheet.mutate({ rounding_step: v })} />}
          </div>
        </Field>
        <Field label={t("costing.pricing.minPrice", { currency: sheet.pricing_currency })} htmlFor="pr-min">
          <CommitInput id="pr-min" dir="ltr" inputMode="decimal" className="w-36" value={sheet.min_acceptable_price} disabled={!editable} onCommit={(v) => m.patchSheet.mutate({ min_acceptable_price: v })} />
        </Field>
        <PercentField id="pr-valid" label={t("costing.pricing.validity")} value={sheet.validity_days} disabled={!editable} suffix={t("settings.days")} onCommit={(v) => m.patchSheet.mutate({ validity_days: v === null ? null : Number(v) })} />
      </div>
      <ErrorNote error={m.patchSheet.error} />
      {c && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-surface-2 text-xs text-muted">
              {["item", "quantity", "landed", "unitCost", "unitPrice", "total", "margin", "markup", "minUnit"].map((h) => <th key={h} className="p-1.5 text-start whitespace-nowrap">{t(`costing.pricing.columns.${h}`)}</th>)}
            </tr></thead>
            <tbody>
              {c.items.map((r) => (
                <tr key={r.item_id} className={`border-b border-line align-top ${r.below_minimum ? "bg-danger-soft" : ""}`}>
                  <td className="p-1.5">
                    <button type="button" className="text-start hover:underline" aria-expanded={open === r.item_id} onClick={() => setOpen(open === r.item_id ? null : r.item_id)}><Bdi>{r.name}</Bdi></button>
                    {r.manual && <Badge tone="warning">{t("costing.pricing.manual")}</Badge>}
                    {open === r.item_id && (
                      <ul className="mt-1 text-xs whitespace-nowrap text-muted" data-testid="breakdown">
                        {r.lines.map((ln) => <li key={ln.line_id}>{sheet.lines.find((x) => x.id === ln.line_id)?.label ?? t(`costing.kinds.${ln.kind}`)}: <Money amount={ln.amount} currency={c.currency} /></li>)}
                        <li>{t("costing.money.costOfMoney")}: <Money amount={r.cost_of_money} currency={c.currency} /></li>
                        <li>{t("costing.money.guaranteeCost")}: <Money amount={r.guarantee} currency={c.currency} /></li>
                        {Number(r.vat) > 0 && <li>{t("costing.pricing.vat")}: <Money amount={r.vat} currency={c.currency} /></li>}
                      </ul>
                    )}
                  </td>
                  <td className="p-1.5 tabular-nums">{r.quantity ? f.num(r.quantity) : <span className="text-danger">{t("costing.pricing.noQuantity")}</span>}</td>
                  <td className="p-1.5"><Money amount={r.landed_cost} currency={c.currency} /></td>
                  <td className="p-1.5"><Money amount={r.unit_cost} currency={c.currency} /></td>
                  <td className="p-1.5">
                    {editable ? (
                      <CommitInput dir="ltr" inputMode="decimal" className="w-32" aria-label={t("costing.pricing.columns.unitPrice")} value={sheet.price_overrides[r.item_id] ?? null}
                        placeholder={r.unit_price && !r.manual ? f.num(r.unit_price) : ""}
                        onCommit={(v) => m.patchSheet.mutate({ price_overrides: { ...sheet.price_overrides, [r.item_id]: v } })} />
                    ) : <Money amount={r.unit_price} currency={c.currency} />}
                  </td>
                  <td className="p-1.5"><Money amount={r.total_price} currency={c.currency} /></td>
                  <td className="p-1.5 tabular-nums" data-testid="item-margin">{r.margin_percent === null ? "—" : `${f.num(r.margin_percent)} %`}</td>
                  <td className="p-1.5 tabular-nums" data-testid="item-markup">{r.markup_percent === null ? "—" : `${f.num(r.markup_percent)} %`}</td>
                  <td className="p-1.5">
                    <CommitInput dir="ltr" inputMode="decimal" className="w-28" aria-label={t("costing.pricing.columns.minUnit")} value={sheet.item_min_prices[r.item_id] ?? null} disabled={!editable}
                      onCommit={(v) => m.patchSheet.mutate({ item_min_prices: { ...sheet.item_min_prices, [r.item_id]: v } })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totals && (
            <dl className="grid gap-x-6 gap-y-1 px-4 py-3 text-sm sm:grid-cols-4" data-testid="totals">
              <div><dt className="text-xs text-muted">{t("costing.pricing.cost")}</dt><dd><Money amount={c.totals.cost_before_vat} currency={c.currency} /></dd></div>
              <div><dt className="text-xs text-muted">{t("costing.pricing.priceBeforeVat")}</dt><dd className="font-semibold"><Money amount={c.totals.price_before_vat} currency={c.currency} /></dd></div>
              <div><dt className="text-xs text-muted">{t("costing.pricing.marginTotal")}</dt><dd className="font-semibold tabular-nums">{totals.margin}</dd></div>
              <div><dt className="text-xs text-muted">{t("costing.pricing.markupTotal")}</dt><dd className="font-semibold tabular-nums">{totals.markup}</dd></div>
              <div><dt className="text-xs text-muted">{t("costing.pricing.profit")}</dt><dd><Money amount={c.totals.profit} currency={c.currency} /></dd></div>
              <div><dt className="text-xs text-muted">{t("costing.pricing.vat")}</dt><dd><Money amount={c.totals.vat} currency={c.currency} /></dd></div>
              <div><dt className="text-xs text-muted">{t("costing.pricing.priceWithVat")}</dt><dd><Money amount={c.totals.price_with_vat} currency={c.currency} /></dd></div>
            </dl>
          )}
        </div>
      )}
    </Card>
  );
}

/** The quote gate as a checklist: every condition in a fixed order, failed ones with their details. */
export function GateChecklist({ failures, overrides, day, onOverride }: {
  failures: GateFailure[]; overrides?: CostGate["overrides"]; day: (iso: string) => string; onOverride?: (code: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <ul className="flex flex-col gap-1 text-sm" data-testid="gate-checklist">
      {gateChecklist(failures, overrides).map((r) => (
        <li key={r.code} className="flex flex-wrap items-center gap-2" data-ok={r.ok}>
          <span aria-hidden className={r.ok ? "text-success" : "text-danger"}>{r.ok ? "✓" : "✗"}</span>
          <span>{t(`costing.gate.conditions.${r.code}`, { defaultValue: r.code })}</span>
          {r.failure?.code === "validity_too_long" && <span className="text-xs text-muted">{t("costing.gate.maxValid")}: <span className="tabular-nums">{day(String(r.failure.max_valid_until))}</span></span>}
          {r.failure?.code === "fx_missing" && <Bdi ltr className="text-xs text-muted">{String(r.failure.from_currency)} → {String(r.failure.to_currency)}</Bdi>}
          {r.failure?.code === "unconfirmed_parameter" && <span className="text-xs text-muted">{(r.failure.parameters as string[]).join("، ")}</span>}
          {r.overridden && <span className="text-xs text-muted">{t("costing.gate.overridden")}: <span dir="auto">{r.overridden}</span></span>}
          {!r.ok && onOverride && (r.code === "fx_stale" || r.code === "unconfirmed_parameter") && (
            <Button variant="ghost" onClick={() => onOverride(r.code)}>{t("costing.gate.override")}</Button>
          )}
        </li>
      ))}
    </ul>
  );
}

function GateCard({ sheet, onChanged, onQuote }: { sheet: CostSheet; onChanged: () => void; onQuote: (id: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [overriding, setOverriding] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const override = useMutation({
    mutationFn: () => api(`/api/cost-sheets/${sheet.id}/override`, { method: "POST", body: { kind: overriding, reason } }),
    onSuccess: () => { setOverriding(null); setReason(""); onChanged(); },
  });
  const quote = useMutation({
    mutationFn: () => api<Quote>("/api/quotes", { method: "POST", body: { case_id: sheet.case_id, cost_sheet_id: sheet.id } }),
    onSuccess: (q) => onQuote(q.id),
  });
  return (
    <Card title={<span className="flex items-center gap-2">{t("costing.gate.title")}{sheet.gate.ok ? <Badge tone="success">{t("costing.gate.ok")}</Badge> : <Badge tone="warning">{t("costing.gate.blocked")}</Badge>}</span>}>
      <GateChecklist failures={sheet.gate.failures} overrides={sheet.gate.overrides} day={f.day}
        onOverride={sheet.status !== "superseded" ? setOverriding : undefined} />
      <p className="mt-2 text-xs text-muted">{t("costing.gate.validUntil")}: <span className="tabular-nums">{f.day(sheet.gate.valid_until)}</span>
        {sheet.gate.valid_until_capped && <> · {t("costing.gate.capped")}</>}</p>
      {sheet.gate.ok && <div className="mt-2"><Button variant="primary" icon="plus" busy={quote.isPending} onClick={() => quote.mutate()}>{t("costing.gate.createQuote")}</Button></div>}
      <ErrorNote error={quote.error} />
      {overriding && (
        <Modal open title={t("costing.gate.override")} onClose={() => setOverriding(null)}
          footer={<><Button onClick={() => setOverriding(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!reason.trim()} busy={override.isPending} onClick={() => override.mutate()}>{t("common.save")}</Button></>}>
          <p className="mb-2 text-sm">{t(`costing.gate.conditions.${overriding}`)}</p>
          <Field label={t("sourcing.reason")} htmlFor="ov-reason"><Input id="ov-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <ErrorNote error={override.error} />
        </Modal>
      )}
    </Card>
  );
}

function SheetEditor({ sheetId, onChanged, onQuote, onSelect }: { sheetId: string; onChanged: () => void; onQuote: (id: string) => void; onSelect: (id: string | null) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const sheet = useQuery({ queryKey: ["cost-sheet", sheetId], queryFn: () => api<CostSheet>(`/api/cost-sheets/${sheetId}`) });
  const refresh = () => { void sheet.refetch(); onChanged(); };
  const m = useSheetMutations(sheetId, refresh);
  const finalize = useMutation({ mutationFn: () => api(`/api/cost-sheets/${sheetId}/finalize`, { method: "POST" }), onSuccess: refresh });
  const version = useMutation({ mutationFn: () => api<CostSheet>(`/api/cost-sheets/${sheetId}/new-version`, { method: "POST" }), onSuccess: (s) => { onChanged(); onSelect(s.id); } });
  const remove = useMutation({ mutationFn: () => api(`/api/cost-sheets/${sheetId}`, { method: "DELETE" }), onSuccess: () => { onChanged(); onSelect(null); } });
  if (sheet.isLoading) return <Loading />;
  if (sheet.error || !sheet.data) return <ErrorNote error={sheet.error} />;
  const s = sheet.data;
  const editable = s.status === "draft";
  const general = s.warnings.filter((w) => !w.line_id);
  return (
    <div className="flex flex-col gap-4" data-sheet={s.id}>
      <Card title={<span className="flex flex-wrap items-center gap-2">{t("costing.sheet", { version: f.num(s.version) })}<StatusBadge group="costSheet" status={s.status} />
        <Badge>{t(`costing.dealTypes.${s.deal_type}`)}</Badge><Bdi ltr>{s.pricing_currency}</Bdi></span>}
        actions={<>
          {editable && <Button variant="primary" busy={finalize.isPending} onClick={() => finalize.mutate()}>{t("costing.finalize")}</Button>}
          <Button busy={version.isPending} onClick={() => version.mutate()}>{t("costing.newVersion")}</Button>
          {editable && <Button variant="ghost" onClick={() => remove.mutate()}>{t("delete.button")}</Button>}
        </>}>
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t("costing.sheetDate")} htmlFor="sh-date" hint={t("costing.sheetDateHint")}>
            <DateInput id="sh-date" value={fromDateString(s.sheet_date)} onChange={(d) => editable && d && m.patchSheet.mutate({ sheet_date: toDateString(d) })} />
          </Field>
          <div className="min-w-64 flex-1"><Field label={t("parties.notes")} htmlFor="sh-notes">
            <Textarea id="sh-notes" dir="auto" rows={1} disabled={!editable} defaultValue={s.notes ?? ""} key={s.notes ?? ""}
              onBlur={(e) => editable && e.target.value !== (s.notes ?? "") && m.patchSheet.mutate({ notes: e.target.value || null })} />
          </Field></div>
        </div>
        {!editable && <p className="mt-2 text-xs text-muted">{t("costing.readOnly")}</p>}
        {general.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1" role="alert">
            {general.map((w, i) => <li key={i} className="rounded-md bg-warning-soft px-2.5 py-1 text-sm text-warning">{t(`costing.warnings.${w.code}`, { defaultValue: w.code, ...w, as_of: w.as_of ? f.day(String(w.as_of)) : undefined })}</li>)}
          </ul>
        )}
        {s.compute_error && s.compute_error.code !== "fx_missing" && <p className="mt-2 text-sm text-danger">{t(`errors.${s.compute_error.code}`, { defaultValue: s.compute_error.message })}</p>}
        <ErrorNote error={finalize.error || version.error || remove.error || m.patchSheet.error} />
      </Card>
      <FxCard sheet={s} editable={editable} onChanged={refresh} />
      <LinesCard sheet={s} editable={editable} onChanged={refresh} />
      <MoneyTimeCard sheet={s} editable={editable} onChanged={refresh} />
      <PricingCard sheet={s} editable={editable} onChanged={refresh} />
      <GateCard sheet={s} onChanged={refresh} onQuote={onQuote} />
    </div>
  );
}

export function CostingTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const invalidate = useInvalidateSourcing();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const costing = useQuery({ queryKey: ["costing", caseData.id], queryFn: () => api<CaseCosting>(`/api/cases/${caseData.id}/costing`) });
  const selected = params.get("sheet") ?? costing.data?.current?.sheet_id ?? costing.data?.sheets[0]?.id ?? null;
  const select = (id: string | null) => setParams(id ? { tab: "costing", sheet: id } : { tab: "costing" }, { replace: true });
  const refresh = () => { void costing.refetch(); invalidate(); };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {(costing.data?.sheets ?? []).map((s) => (
          <button key={s.id} type="button" onClick={() => select(s.id)} aria-pressed={s.id === selected}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm ${s.id === selected ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"}`}>
            {t("costing.version", { version: f.num(s.version) })}<StatusBadge group="costSheet" status={s.status} />
          </button>
        ))}
        <Button variant="primary" icon="plus" className="ms-auto" disabled={caseData.status !== "open"} onClick={() => setCreating(true)}>{t("costing.newSheet")}</Button>
      </div>
      <ErrorNote error={costing.error} />
      {costing.data && costing.data.sheets.length === 0 && <Card><EmptyState>{t("costing.empty")}</EmptyState></Card>}
      {selected && <SheetEditor key={selected} sheetId={selected} onChanged={refresh} onSelect={select}
        onQuote={(id) => { invalidate(); setParams({ tab: "quotes", quote: id }); }} />}
      {creating && <NewSheetDialog caseData={caseData} onClose={() => setCreating(false)} onCreated={(id) => { refresh(); select(id); }} />}
    </div>
  );
}
