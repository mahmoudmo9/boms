/** Supplier invoices of the case (v0.8.0): recorded against a PO (lines default to received, not invoiced) or for a
 * service party without one; the matching table (ordered / received / invoiced, price difference); approve (a reason
 * when it differs), dispute (with a claim), cancel. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DateInput } from "../../../components/DateInput";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Select } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { PAYMENT_TONE, type PurchaseInvoice } from "../../../lib/finance";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseExecution } from "../../../lib/types";
import { Money } from "../../sourcing/shared";
import { partyName, ReasonDialog } from "../execution/shared";
import { useFinanceRun } from "./shared";

function NewSupplierInvoice({ caseId, execution, onClose }: { caseId: string; execution: CaseExecution | undefined; onClose: () => void }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const pos = (execution?.purchase_orders ?? []).filter((p) => !["draft", "cancelled", "superseded"].includes(p.status));
  const [form, setForm] = useState({ purchase_order_id: pos[0]?.id ?? "", supplier_invoice_no: "", invoice_date: new Date() as Date | null, vat_amount: "" });
  return (
    <Modal open title={t("finance.supplier.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="supplier-invoice-save"
        disabled={!form.purchase_order_id || !form.supplier_invoice_no.trim() || !form.invoice_date} busy={run.isPending}
        onClick={() => void run.mutateAsync({ path: "/api/purchase-invoices", body: { purchase_order_id: form.purchase_order_id,
          supplier_invoice_no: form.supplier_invoice_no.trim(), invoice_date: toDateString(form.invoice_date!), vat_amount: form.vat_amount || null } }).then(onClose)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2" data-testid="supplier-invoice-dialog">
        <Field label={t("finance.supplier.po")} htmlFor="pi-po"><Select id="pi-po" value={form.purchase_order_id} onChange={(e) => setForm({ ...form, purchase_order_id: e.target.value })}>
          {pos.map((p) => <option key={p.id} value={p.id}>{p.number}</option>)}</Select></Field>
        <Field label={t("finance.supplier.number")} htmlFor="pi-no"><Input id="pi-no" dir="ltr" value={form.supplier_invoice_no} onChange={(e) => setForm({ ...form, supplier_invoice_no: e.target.value })} /></Field>
        <Field label={t("finance.supplier.date")} htmlFor="pi-date"><DateInput id="pi-date" value={form.invoice_date} onChange={(d) => setForm({ ...form, invoice_date: d })} /></Field>
        <Field label={t("finance.supplier.vat")} htmlFor="pi-vat"><Input id="pi-vat" dir="ltr" inputMode="decimal" value={form.vat_amount} onChange={(e) => setForm({ ...form, vat_amount: e.target.value })} /></Field>
        <p className="text-xs text-muted sm:col-span-2">{t("finance.supplier.linesHint")}</p>
        <div className="sm:col-span-2"><ErrorNote error={run.error} /></div>
      </div>
    </Modal>
  );
}

function LinePrices({ caseId, invoice }: { caseId: string; invoice: PurchaseInvoice }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const rows = invoice.matching.rows.filter((r) => Number(r.this_invoice) > 0);
  if (!rows.length || !["received", "disputed"].includes(invoice.status)) return null;
  return (
    <div className="flex flex-wrap items-end gap-2">
      {rows.map((r) => (
        <Field key={r.purchase_order_item_id} label={`${t("finance.supplier.invoicePrice")} — ${r.description}`} htmlFor={`pp-${r.purchase_order_item_id}`}>
          <Input id={`pp-${r.purchase_order_item_id}`} className="w-28" dir="ltr" inputMode="decimal" value={prices[r.purchase_order_item_id] ?? r.invoice_price ?? ""}
            onChange={(e) => setPrices({ ...prices, [r.purchase_order_item_id]: e.target.value })} />
        </Field>))}
      <Button data-testid="supplier-prices-save" onClick={() => run.mutate({ path: `/api/purchase-invoices/${invoice.id}`, method: "PATCH", body: {
        lines: rows.map((r) => ({ purchase_order_item_id: r.purchase_order_item_id, quantity: r.this_invoice,
          unit_price: prices[r.purchase_order_item_id] ?? r.invoice_price })) } })}>{t("finance.supplier.savePrices")}</Button>
      <ErrorNote error={run.error} />
    </div>
  );
}

function SupplierInvoiceItem({ caseId, invoice, claims, readOnly }: { caseId: string; invoice: PurchaseInvoice; claims: { id: string; kind: string }[]; readOnly?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useFinanceRun(caseId);
  const [dialog, setDialog] = useState<"approve" | "dispute" | "cancel" | null>(null);
  const [claim, setClaim] = useState("");
  const approve = (reason?: string) => run.mutateAsync({ path: `/api/purchase-invoices/${invoice.id}/approve`, body: reason ? { reason } : {} })
    .then(() => setDialog(null)).catch((err) => { if (err instanceof ApiError && err.code === "invoice_differences") setDialog("approve"); });
  return (
    <li className="flex flex-col gap-2 px-4 py-2 text-sm" data-testid="supplier-invoice" data-status={invoice.status}>
      <span className="flex flex-wrap items-center gap-2">
        <bdi dir="ltr" className="font-mono">{invoice.supplier_invoice_no}</bdi>
        <span dir="auto" className="text-muted">{partyName(invoice.supplier, f.lang)}</span>
        {invoice.purchase_order_number && <bdi dir="ltr" className="text-xs text-muted">{invoice.purchase_order_number}</bdi>}
        <Badge tone={invoice.status === "approved" ? "success" : invoice.status === "disputed" ? "danger" : invoice.status === "cancelled" ? "neutral" : "warning"}>{t(`finance.supplier.statuses.${invoice.status}`)}</Badge>
        {invoice.status !== "cancelled" && <Badge tone={PAYMENT_TONE[invoice.payment_status]}>{t(`finance.paymentStatus.${invoice.payment_status}`)}</Badge>}
        <span className="ms-auto"><Money amount={invoice.total} currency={invoice.currency} /></span>
      </span>
      {invoice.matching.rows.length > 0 && (
        <table className="w-full text-xs" data-testid="matching-table">
          <thead className="text-muted"><tr><th className="text-start">{t("finance.invoices.item")}</th><th className="text-end">{t("finance.invoices.ordered")}</th>
            <th className="text-end">{t("finance.supplier.received")}</th><th className="text-end">{t("finance.invoices.invoiced")}</th>
            <th className="text-end">{t("finance.supplier.poPrice")}</th><th className="text-end">{t("finance.supplier.invoicePrice")}</th><th /></tr></thead>
          <tbody>{invoice.matching.rows.map((r) => (
            <tr key={r.purchase_order_item_id} className={r.flags.length ? "text-danger" : ""}>
              <td dir="auto">{r.description}</td><td className="text-end tabular-nums">{f.num(r.ordered)}</td><td className="text-end tabular-nums">{f.num(r.received)}</td>
              <td className="text-end tabular-nums">{f.num(r.invoiced)}</td><td className="text-end tabular-nums">{f.num(r.po_price)}</td>
              <td className="text-end tabular-nums">{r.invoice_price ? f.num(r.invoice_price) : "—"}</td>
              <td>{r.flags.map((fl) => <Badge key={fl} tone="danger">{t(`finance.supplier.flags.${fl}`)}</Badge>)}</td>
            </tr>))}</tbody>
        </table>)}
      {!readOnly && <LinePrices caseId={caseId} invoice={invoice} />}
      {!readOnly && ["received", "disputed"].includes(invoice.status) && (
        <span className="flex flex-wrap gap-2">
          <Button variant="primary" data-testid="supplier-approve" onClick={() => void approve()}>{t("finance.supplier.approve")}</Button>
          <Button onClick={() => setDialog("dispute")}>{t("finance.supplier.dispute")}</Button>
          <Button variant="ghost" onClick={() => setDialog("cancel")}>{t("finance.supplier.cancel")}</Button>
        </span>)}
      {invoice.difference_reason && <p className="text-xs text-muted">{t("finance.supplier.differenceReason")}: <span dir="auto">{invoice.difference_reason}</span></p>}
      <ErrorNote error={run.error instanceof ApiError && run.error.code === "invoice_differences" ? null : run.error} />
      {dialog === "approve" && <ReasonDialog title={t("finance.supplier.approveWithDifferences")} label={t("finance.reason")} busy={run.isPending}
        onClose={() => setDialog(null)} onSave={(reason) => void approve(reason)} />}
      {dialog === "cancel" && <ReasonDialog title={t("finance.supplier.cancel")} label={t("finance.reason")} busy={run.isPending} error={run.error}
        onClose={() => setDialog(null)} onSave={(reason) => void run.mutateAsync({ path: `/api/purchase-invoices/${invoice.id}/cancel`, body: { reason } }).then(() => setDialog(null))} />}
      {dialog === "dispute" && (
        <Modal open title={t("finance.supplier.dispute")} onClose={() => setDialog(null)} footer={<Button onClick={() => setDialog(null)}>{t("common.cancel")}</Button>}>
          <Field label={t("finance.supplier.claim")} htmlFor="pi-claim"><Select id="pi-claim" value={claim} onChange={(e) => setClaim(e.target.value)}>
            <option value="">—</option>{claims.map((c) => <option key={c.id} value={c.id}>{t(`execution.claims.kinds.${c.kind}`)}</option>)}</Select></Field>
          <ReasonDialogInline onSave={(reason) => void run.mutateAsync({ path: `/api/purchase-invoices/${invoice.id}/dispute`, body: { reason, claim_id: claim || null } }).then(() => setDialog(null))} />
        </Modal>)}
    </li>
  );
}

function ReasonDialogInline({ onSave }: { onSave: (reason: string) => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  return (
    <div className="mt-3 flex items-end gap-2">
      <Field label={t("finance.reason")} htmlFor="pi-dispute-reason"><Input id="pi-dispute-reason" className="w-72" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <Button variant="primary" disabled={!reason.trim()} onClick={() => onSave(reason.trim())}>{t("common.save")}</Button>
    </div>
  );
}

export function SupplierInvoicesCard({ caseId, invoices, execution, readOnly }: { caseId: string; invoices: PurchaseInvoice[]; execution: CaseExecution | undefined; readOnly?: boolean }) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const claims = (execution?.claims ?? []).map((c) => ({ id: c.id, kind: c.kind }));
  return (
    <Card padded={false} title={t("finance.supplier.title")} actions={readOnly ? undefined : <Button icon="plus" data-testid="supplier-invoice-new" onClick={() => setAdding(true)}>{t("finance.supplier.new")}</Button>}>
      {invoices.length === 0 ? <EmptyState>{t("finance.supplier.none")}</EmptyState> : (
        <ul className="max-h-[32rem] divide-y divide-line overflow-y-auto">{invoices.map((inv) => <SupplierInvoiceItem key={inv.id} caseId={caseId} invoice={inv} claims={claims} readOnly={readOnly} />)}</ul>)}
      {adding && <NewSupplierInvoice caseId={caseId} execution={execution} onClose={() => setAdding(false)} />}
    </Card>
  );
}
