/** Actual costs of the case (v0.8.0): owned rows (each with its own FX rate) and read-only rows from tender costs,
 * guarantee fees and payment bank fees. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DateInput } from "../../../components/DateInput";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Select } from "../../../components/ui";
import { COST_KINDS, type CostRow } from "../../../lib/finance";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import { CurrencySelect, Money } from "../../sourcing/shared";
import { useFinanceRun } from "./shared";

function NewCost({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const [form, setForm] = useState({ kind: "freight_international", description: "", amount: "", currency: "IRR" as string | null,
    fx_rate_to_base: "", vat_amount: "", incurred_on: new Date() as Date | null, status: "incurred" });
  const foreign = form.currency !== "IRR";
  return (
    <Modal open title={t("finance.costs.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="cost-save" busy={run.isPending}
        disabled={!form.description.trim() || !Number(form.amount) || !form.currency || (foreign && !Number(form.fx_rate_to_base))}
        onClick={() => void run.mutateAsync({ path: `/api/cases/${caseId}/actual-costs`, body: { kind: form.kind, description: form.description.trim(),
          amount: form.amount, currency: form.currency, fx_rate_to_base: foreign ? form.fx_rate_to_base : null, vat_amount: form.vat_amount || null,
          incurred_on: form.incurred_on ? toDateString(form.incurred_on) : null, status: form.status } }).then(onClose)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2" data-testid="cost-dialog">
        <Field label={t("finance.costs.kind")} htmlFor="ac-kind"><Select id="ac-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {COST_KINDS.map((k) => <option key={k} value={k}>{t(`finance.profit.lines.${k}`)}</option>)}</Select></Field>
        <Field label={t("finance.invoices.description")} htmlFor="ac-desc"><Input id="ac-desc" dir="auto" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label={t("finance.amount")} htmlFor="ac-amount"><span className="flex gap-1.5"><Input id="ac-amount" dir="ltr" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <CurrencySelect value={form.currency} onChange={(v) => setForm({ ...form, currency: v })} /></span></Field>
        {foreign && <Field label={t("finance.fxRate", { cur: form.currency })} htmlFor="ac-rate"><Input id="ac-rate" dir="ltr" inputMode="decimal" value={form.fx_rate_to_base} onChange={(e) => setForm({ ...form, fx_rate_to_base: e.target.value })} /></Field>}
        <Field label={t("finance.costs.vat")} htmlFor="ac-vat"><Input id="ac-vat" dir="ltr" inputMode="decimal" value={form.vat_amount} onChange={(e) => setForm({ ...form, vat_amount: e.target.value })} /></Field>
        <Field label={t("finance.costs.date")} htmlFor="ac-date"><DateInput id="ac-date" value={form.incurred_on} onChange={(d) => setForm({ ...form, incurred_on: d })} /></Field>
        <Field label={t("finance.costs.status")} htmlFor="ac-status"><Select id="ac-status" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
          <option value="incurred">{t("finance.costs.statuses.incurred")}</option><option value="expected">{t("finance.costs.statuses.expected")}</option></Select></Field>
        <div className="sm:col-span-2"><ErrorNote error={run.error} /></div>
      </div>
    </Modal>
  );
}

export function CostsCard({ caseId, costs, readOnly }: { caseId: string; costs: CostRow[]; readOnly?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useFinanceRun(caseId);
  const [adding, setAdding] = useState(false);
  return (
    <Card padded={false} title={t("finance.costs.title")} actions={readOnly ? undefined : <Button icon="plus" data-testid="cost-new" onClick={() => setAdding(true)}>{t("finance.costs.new")}</Button>}>
      {costs.length === 0 ? <EmptyState>{t("finance.costs.none")}</EmptyState> : (
        <ul className="max-h-96 divide-y divide-line overflow-y-auto">{costs.map((c) => (
          <li key={`${c.source}-${c.id ?? c.source_id}`} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm" data-testid="actual-cost">
            <Badge>{t(`finance.profit.lines.${c.kind}`)}</Badge><span dir="auto" className="min-w-0 flex-1 truncate">{c.description}</span>
            {c.read_only && <Badge tone="neutral">{t(`finance.costs.sources.${c.source}`)}</Badge>}
            <Money amount={c.amount} currency={c.currency} />
            {c.currency !== "IRR" && c.base_amount && <span className="text-xs text-muted"><Money amount={c.base_amount} currency="IRR" /></span>}
            <Badge tone={c.status === "paid" ? "success" : c.status === "expected" ? "neutral" : "warning"}>{t(`finance.costs.statuses.${c.status}`)}</Badge>
            {c.incurred_on && <span className="text-xs text-muted tabular-nums">{f.day(c.incurred_on)}</span>}
            {!readOnly && !c.read_only && c.status !== "paid" && <Button variant="ghost" onClick={() => run.mutate({ path: `/api/actual-costs/${c.id}`, method: "DELETE" })}>{t("common.remove")}</Button>}
          </li>))}</ul>)}
      <div className="px-4"><ErrorNote error={run.error} /></div>
      {adding && <NewCost caseId={caseId} onClose={() => setAdding(false)} />}
    </Card>
  );
}
