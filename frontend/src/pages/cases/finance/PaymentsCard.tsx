/** Payments of the case and their allocation (v0.8.0): each record with its real rate (or «نرخ ثبت نشده» to
 * complete), the allocated and unallocated amounts; allocation from the oldest-first suggestion, confirmed by the owner. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Modal } from "../../../components/ui";
import { api } from "../../../lib/api";
import type { PaymentRecordRow, Suggestion } from "../../../lib/finance";
import { useFormat } from "../../../lib/prefs";
import { Money } from "../../sourcing/shared";
import { useFinanceRun } from "./shared";

function AllocateDialog({ caseId, record, onClose }: { caseId: string; record: PaymentRecordRow; onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useFinanceRun(caseId);
  const view = useQuery({ queryKey: ["allocation", record.id], queryFn: () => api<{ suggestion: Suggestion[] }>(`/api/payment-records/${record.id}/allocation`) });
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const [rates, setRates] = useState<Record<number, string>>({});
  const rows = view.data?.suggestion ?? [];
  const chosen = rows.map((s, i) => ({ s, i, amount: amounts[i] ?? s.amount ?? "", rate: rates[i] ?? "" }))
    .filter((x) => Number(x.amount) > 0 && (!x.s.needs_rate || Number(x.rate) > 0));
  const target = (s: Suggestion) => (s.sales_invoice_id ? { sales_invoice_id: s.sales_invoice_id } : s.purchase_invoice_id
    ? { purchase_invoice_id: s.purchase_invoice_id } : { actual_cost_id: s.actual_cost_id });
  return (
    <Modal open wide title={t("finance.payments.allocate")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="allocation-confirm" disabled={!chosen.length} busy={run.isPending}
        onClick={() => void run.mutateAsync({ path: `/api/payment-records/${record.id}/allocations`, body: { allocations: chosen.map((x) => ({
          ...target(x.s), amount: x.amount, ...(x.s.needs_rate ? { fx_rate: x.rate } : {}) })) } }).then(onClose)}>{t("finance.payments.confirm")}</Button></>}>
      <div className="flex flex-col gap-2 text-sm" data-testid="allocation-dialog">
        <p className="text-muted">{t("finance.payments.unallocatedOf", { amount: f.num(record.unallocated), cur: record.amount_currency })}</p>
        {rows.length === 0 && <EmptyState>{t("finance.payments.nothingOpen")}</EmptyState>}
        {rows.map((s, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2 rounded-md border border-line px-3 py-2">
            <span className="min-w-40" dir="auto">{s.label}</span>
            <span className="text-xs text-muted">{t("finance.balance")}: <Money amount={s.balance} currency={s.currency} />{s.due_date && ` · ${f.day(s.due_date)}`}</span>
            <Field label={`${t("finance.amount")} (${record.amount_currency})`} htmlFor={`al-${i}`}>
              <Input id={`al-${i}`} className="w-36" dir="ltr" inputMode="decimal" value={amounts[i] ?? s.amount ?? ""} onChange={(e) => setAmounts({ ...amounts, [i]: e.target.value })} /></Field>
            {s.needs_rate && <Field label={t("finance.payments.rate", { from: record.amount_currency, to: s.currency })} htmlFor={`alr-${i}`}>
              <Input id={`alr-${i}`} className="w-36" dir="ltr" inputMode="decimal" value={rates[i] ?? ""} onChange={(e) => setRates({ ...rates, [i]: e.target.value })} /></Field>}
          </div>))}
        <ErrorNote error={run.error ?? view.error} />
      </div>
    </Modal>
  );
}

function RateForm({ caseId, record }: { caseId: string; record: PaymentRecordRow }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const [rate, setRate] = useState("");
  return (
    <span className="flex items-end gap-1.5">
      <Input className="w-32" dir="ltr" inputMode="decimal" aria-label={t("finance.fxRate", { cur: record.amount_currency })} value={rate} onChange={(e) => setRate(e.target.value)} />
      <Button disabled={!Number(rate)} busy={run.isPending} onClick={() => run.mutate({ path: `/api/payment-records/${record.id}`, method: "PATCH", body: { fx_rate_to_base: rate } })}>{t("finance.payments.saveRate")}</Button>
      <ErrorNote error={run.error} />
    </span>
  );
}

export function PaymentsCard({ caseId, payments, readOnly }: { caseId: string; payments: PaymentRecordRow[]; readOnly?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [allocating, setAllocating] = useState<PaymentRecordRow | null>(null);
  return (
    <Card padded={false} title={t("finance.payments.title")}>
      {payments.length === 0 ? <EmptyState>{t("finance.payments.none")}</EmptyState> : (
        <ul className="max-h-96 divide-y divide-line overflow-y-auto">{payments.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm" data-testid="payment-record" data-payment={r.id}>
            <Badge tone={r.direction === "in" ? "success" : "accent"}>{t(`finance.payments.direction.${r.direction}`)}</Badge>
            <span className="tabular-nums text-muted">{f.day(r.paid_on)}</span>
            <Money amount={r.amount} currency={r.amount_currency} />
            {r.fx_rate_to_base && <span className="text-xs text-muted">@ <bdi dir="ltr">{f.num(r.fx_rate_to_base)}</bdi> = <Money amount={r.base_amount} currency="IRR" /></span>}
            {r.rate_missing && <><Badge tone="danger">{t("finance.payments.rateMissing")}</Badge>{!readOnly && <RateForm caseId={caseId} record={r} />}</>}
            <span className="ms-auto text-xs">{Number(r.unallocated) > 0
              ? <span className="text-warning">{t("finance.payments.unallocated")}: <Money amount={r.unallocated} currency={r.amount_currency} /></span>
              : <span className="text-success">{t("finance.payments.allocated")}</span>}</span>
            {!readOnly && Number(r.unallocated) > 0 && <Button data-testid="allocate" onClick={() => setAllocating(r)}>{t("finance.payments.allocate")}</Button>}
          </li>))}</ul>)}
      {allocating && <AllocateDialog caseId={caseId} record={allocating} onClose={() => setAllocating(null)} />}
    </Card>
  );
}
