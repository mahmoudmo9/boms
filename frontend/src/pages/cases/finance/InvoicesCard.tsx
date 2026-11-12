/** Sales invoices of the case (v0.8.0): a partial invoice from the delivered quantities or «invoice the rest», the
 * draft (VAT % with a note, issue, delete), the issued invoice (print / PDF / Word, Moadian tax ID and status, credit
 * and debit notes, cancel with a reason). */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Modal, RadioGroup, Select } from "../../../design/components";
import { api, ApiError } from "../../../lib/api";
import { MOADIAN_TONE, PAYMENT_TONE, type SalesInvoice } from "../../../lib/finance";
import { useFormat } from "../../../lib/prefs";
import type { CaseExecution } from "../../../lib/types";
import { Money } from "../../sourcing/shared";
import { OutputButtons, ReasonDialog } from "../execution/shared";
import { useFinanceRun, type Body } from "./shared";

interface InvoicingRow { sales_order_item_id: string; description: string; unit: string | null; unit_price: string; ordered: string;
  delivered: string; invoiced: string; to_invoice: string }

function NewInvoiceDialog({ caseId, orderId, onClose }: { caseId: string; orderId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useFinanceRun(caseId);
  const state = useQuery({ queryKey: ["invoicing", orderId], queryFn: () => api<{ items: InvoicingRow[] }>(`/api/sales-orders/${orderId}/invoicing`) });
  const [qty, setQty] = useState<Record<string, string>>({});
  const [language, setLanguage] = useState<"" | "fa" | "en">("");
  const [reason, setReason] = useState("");
  const rows = state.data?.items ?? [];
  const value = (r: InvoicingRow) => qty[r.sales_order_item_id] ?? (Number(r.to_invoice) ? String(Number(r.to_invoice)) : "");
  const lines = rows.filter((r) => Number(value(r)) > 0).map((r) => ({ sales_order_item_id: r.sales_order_item_id, quantity: value(r) }));
  const over = rows.some((r) => Number(value(r)) > Number(r.delivered) - Number(r.invoiced));
  const save = () => run.mutateAsync({ path: "/api/sales-invoices", body: { sales_order_id: orderId, lines, ...(language ? { language } : {}),
    ...(reason.trim() ? { over_delivered_reason: reason.trim() } : {}) } }).then(onClose);
  return (
    <Modal open wide title={t("finance.invoices.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" data-testid="invoice-create" disabled={!lines.length || (over && !reason.trim())} busy={run.isPending} onClick={() => void save()}>{t("finance.invoices.createDraft")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="invoice-dialog">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted"><tr>
            <th className="text-start">{t("finance.invoices.item")}</th><th className="text-end">{t("finance.invoices.ordered")}</th>
            <th className="text-end">{t("finance.invoices.delivered")}</th><th className="text-end">{t("finance.invoices.invoiced")}</th>
            <th className="text-end">{t("finance.invoices.quantity")}</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.sales_order_item_id}>
              <td dir="auto">{r.description}</td><td className="text-end tabular-nums">{f.num(r.ordered)}</td>
              <td className="text-end tabular-nums">{f.num(r.delivered)}</td><td className="text-end tabular-nums">{f.num(r.invoiced)}</td>
              <td className="text-end"><Input className="w-24" dir="ltr" inputMode="decimal" aria-label={`${t("finance.invoices.quantity")} ${r.description}`}
                value={value(r)} onChange={(e) => setQty({ ...qty, [r.sales_order_item_id]: e.target.value })} /></td>
            </tr>))}</tbody>
        </table>
        <div className="flex flex-wrap gap-3">
          <Field label={t("finance.invoices.language")} htmlFor="inv-lang">
            <Select id="inv-lang" value={language} onChange={(e) => setLanguage(e.target.value as "" | "fa" | "en")}>
              <option value="">{t("finance.invoices.languageAuto")}</option><option value="fa">{t("finance.invoices.fa")}</option>
              <option value="en">{t("finance.invoices.en")}</option></Select>
          </Field>
          {over && <Field label={t("finance.invoices.overReason")} htmlFor="inv-over"><Input id="inv-over" className="w-80" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        </div>
        <ErrorNote error={run.error ?? state.error} />
      </div>
    </Modal>
  );
}

function NoteDialog({ caseId, invoice, kind, onClose }: { caseId: string; invoice: SalesInvoice; kind: "credit-note" | "debit-note"; onClose: () => void }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const [form, setForm] = useState({ reason: "", description: "", quantity: "1", unit_price: "" });
  return (
    <Modal open title={t(`finance.invoices.${kind === "credit-note" ? "creditNote" : "debitNote"}`)} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="note-save"
        disabled={!form.reason.trim() || !form.description.trim() || !Number(form.unit_price)} busy={run.isPending}
        onClick={() => void run.mutateAsync({ path: `/api/sales-invoices/${invoice.id}/${kind}`, body: { reason: form.reason,
          lines: [{ description: form.description, quantity: form.quantity, unit_price: form.unit_price }] } }).then(onClose)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2" data-testid="note-dialog">
        <Field label={t("finance.reason")} htmlFor="note-reason"><Input id="note-reason" dir="auto" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        <Field label={t("finance.invoices.description")} htmlFor="note-desc"><Input id="note-desc" dir="auto" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label={t("finance.invoices.quantity")} htmlFor="note-qty"><Input id="note-qty" dir="ltr" inputMode="decimal" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></Field>
        <Field label={`${t("finance.invoices.unitPrice")} (${invoice.currency})`} htmlFor="note-price"><Input id="note-price" dir="ltr" inputMode="decimal" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} /></Field>
        <div className="sm:col-span-2"><ErrorNote error={run.error} /></div>
      </div>
    </Modal>
  );
}

function Moadian({ caseId, invoice }: { caseId: string; invoice: SalesInvoice }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const [form, setForm] = useState({ moadian_status: invoice.moadian_status, moadian_tax_id: invoice.moadian_tax_id ?? "", moadian_note: invoice.moadian_note ?? "" });
  return (
    <div className="flex flex-wrap items-end gap-2" data-testid="moadian-form">
      <Field label={t("finance.moadian.status")} htmlFor={`md-st-${invoice.id}`}>
        <Select id={`md-st-${invoice.id}`} value={form.moadian_status} onChange={(e) => setForm({ ...form, moadian_status: e.target.value as SalesInvoice["moadian_status"] })}>
          {(["not_required", "not_sent", "sent", "accepted", "rejected"] as const).map((s) => <option key={s} value={s}>{t(`finance.moadian.statuses.${s}`)}</option>)}
        </Select>
      </Field>
      <Field label={t("finance.moadian.taxId")} htmlFor={`md-id-${invoice.id}`}><Input id={`md-id-${invoice.id}`} className="w-64" dir="ltr" value={form.moadian_tax_id} onChange={(e) => setForm({ ...form, moadian_tax_id: e.target.value })} /></Field>
      <Field label={t("finance.moadian.note")} htmlFor={`md-note-${invoice.id}`}><Input id={`md-note-${invoice.id}`} className="w-48" dir="auto" value={form.moadian_note} onChange={(e) => setForm({ ...form, moadian_note: e.target.value })} /></Field>
      <Button data-testid="moadian-save" busy={run.isPending} onClick={() => run.mutate({ path: `/api/sales-invoices/${invoice.id}/moadian`,
        body: { moadian_status: form.moadian_status, moadian_tax_id: form.moadian_tax_id || null, moadian_note: form.moadian_note || null } })}>{t("common.save")}</Button>
      <ErrorNote error={run.error} />
    </div>
  );
}

/** v0.9.0: the first domestic invoice asks how VAT applies; the choice becomes the default for later invoices. */
function VatDecisionDialog({ caseId, invoiceId, rate, onClose }: { caseId: string; invoiceId: string; rate: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useFinanceRun(caseId);
  const [mode, setMode] = useState<"apply" | "zero">(rate ? "apply" : "zero");
  const [reason, setReason] = useState("");
  return (
    <Modal open title={t("finance.vatDecision.title")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="vat-decision-save" busy={run.isPending}
        disabled={mode === "zero" ? !reason.trim() : !rate}
        onClick={() => void run.mutateAsync({ path: `/api/sales-invoices/${invoiceId}/issue`, body: { vat_decision: mode,
          ...(mode === "zero" ? { vat_reason: reason.trim() } : {}) } }).then(onClose)}>{t("finance.invoices.issue")}</Button></>}>
      <div className="flex flex-col gap-3 text-sm" data-testid="vat-decision">
        <p>{t("finance.vatDecision.text")}</p>
        <RadioGroup label={t("finance.vatDecision.title")} inline={false} value={mode} onChange={setMode} options={[
          { value: "apply", disabled: !rate, label: rate ? t("finance.vatDecision.apply", { rate: f.num(rate) }) : t("finance.vatDecision.noParameter") },
          { value: "zero", label: t("finance.vatDecision.zero") }]} />
        {mode === "zero" && <Field label={t("finance.reason")} htmlFor="vat-zero-reason"><Input id="vat-zero-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <p className="text-xs text-muted">{t("finance.vatDecision.becomesDefault")}</p>
        <ErrorNote error={run.error} />
      </div>
    </Modal>
  );
}

function InvoiceItem({ caseId, invoice, readOnly }: { caseId: string; invoice: SalesInvoice; readOnly?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useFinanceRun(caseId);
  const [open, setOpen] = useState(invoice.status === "draft");
  const [dialog, setDialog] = useState<"credit-note" | "debit-note" | "cancel" | null>(null);
  const [vat, setVat] = useState({ rate: invoice.vat_rate, note: invoice.vat_note ?? "" });
  const [vatAsk, setVatAsk] = useState<{ rate: string | null } | null>(null);
  const go = (path: string, body?: Body, method: "POST" | "PATCH" | "DELETE" = "POST") => run.mutate({ path, body, method });
  return (
    <li className="flex flex-col gap-2 px-4 py-2 text-sm" data-testid="sales-invoice" data-invoice={invoice.id} data-status={invoice.status}>
      <button type="button" className="flex flex-wrap items-center gap-2 text-start" onClick={() => setOpen(!open)}>
        <bdi dir="ltr" className="font-mono">{invoice.number ?? t("finance.invoices.draftNo")}</bdi>
        <Badge>{t(`finance.invoices.kinds.${invoice.kind}`)}</Badge>
        <Badge tone={invoice.status === "issued" ? "success" : invoice.status === "cancelled" ? "danger" : "warning"}>{t(`finance.invoices.statuses.${invoice.status}`)}</Badge>
        {invoice.kind === "invoice" && invoice.status === "issued" && <Badge tone={PAYMENT_TONE[invoice.payment_status]}>{t(`finance.paymentStatus.${invoice.payment_status}`)}</Badge>}
        {invoice.status === "issued" && <Badge tone={MOADIAN_TONE[invoice.moadian_status]}>{t(`finance.moadian.statuses.${invoice.moadian_status}`)}</Badge>}
        <span className="ms-auto"><Money amount={invoice.total} currency={invoice.currency} /></span>
        {invoice.status === "issued" && invoice.kind === "invoice" && <span className="text-xs text-muted">{t("finance.balance")}: <Money amount={invoice.balance_due} currency={invoice.currency} /></span>}
      </button>
      {open && (
        <div className="flex flex-col gap-2 rounded-xl border border-line p-3">
          <table className="w-full text-xs"><tbody>{invoice.lines.map((l) => (
            <tr key={l.id}><td dir="auto">{l.description}</td><td className="text-end tabular-nums">{f.num(l.quantity)} {l.unit ?? ""}</td>
              <td className="text-end tabular-nums">{f.num(l.unit_price)}</td><td className="text-end tabular-nums">{f.num(l.total)}</td></tr>))}</tbody></table>
          <p className="text-xs text-muted">{t("finance.invoices.totals", { subtotal: f.num(invoice.subtotal), vat: f.num(invoice.vat_amount), rate: f.num(invoice.vat_rate), total: f.num(invoice.total), cur: invoice.currency })}
            {invoice.issue_date && ` · ${t("finance.invoices.issued")} ${f.day(invoice.issue_date)}`}{invoice.due_date && ` · ${t("finance.invoices.due")} ${f.day(invoice.due_date)}`}
            {invoice.corrects_number && ` · ${t("finance.invoices.corrects")} ${invoice.corrects_number}`}</p>
          {invoice.status === "draft" && !readOnly && (
            <div className="flex flex-col gap-2">
              {invoice.missing_for_issue.length > 0 && (
                <p className="rounded-md bg-warning-soft px-3 py-2 text-warning" role="alert" data-testid="issue-missing">
                  {t("finance.invoices.missing")}: {invoice.missing_for_issue.map((m) => t(`finance.invoices.missingFields.${m.replace(".", "_")}`)).join("، ")}{" "}
                  <Link className="underline" to={invoice.missing_for_issue.some((m) => m.startsWith("company")) ? "/settings/letterhead" : `/parties/${invoice.customer.id}`}>{t("finance.invoices.fillIn")}</Link>
                </p>)}
              <div className="flex flex-wrap items-end gap-2">
                <Field label={t("finance.invoices.vatRate")} htmlFor={`vat-${invoice.id}`}><Input id={`vat-${invoice.id}`} className="w-20" dir="ltr" inputMode="decimal" value={vat.rate} onChange={(e) => setVat({ ...vat, rate: e.target.value })} /></Field>
                <Field label={t("finance.invoices.vatNote")} htmlFor={`vatn-${invoice.id}`}><Input id={`vatn-${invoice.id}`} className="w-56" dir="auto" value={vat.note} onChange={(e) => setVat({ ...vat, note: e.target.value })} /></Field>
                <Button onClick={() => go(`/api/sales-invoices/${invoice.id}`, { vat_rate: vat.rate, vat_note: vat.note || null }, "PATCH")}>{t("finance.invoices.saveVat")}</Button>
                <Button variant="primary" data-testid="invoice-issue" onClick={() => void run.mutateAsync({ path: `/api/sales-invoices/${invoice.id}/issue` })
                  .catch((err) => { if (err instanceof ApiError && err.code === "vat_decision_required") setVatAsk({ rate: (err.details.rate as string | null) ?? null }); })}>{t("finance.invoices.issue")}</Button>
                <Button variant="ghost" onClick={() => go(`/api/sales-invoices/${invoice.id}`, undefined, "DELETE")}>{t("common.remove")}</Button>
              </div>
            </div>)}
          {invoice.status !== "cancelled" && <OutputButtons base={`/api/sales-invoices/${invoice.id}`} outputs={[]} />}
          {invoice.status === "issued" && !readOnly && (
            <div className="flex flex-col gap-2">
              <Moadian caseId={caseId} invoice={invoice} />
              {invoice.kind === "invoice" && <div className="flex flex-wrap gap-2">
                <Button onClick={() => setDialog("credit-note")} data-testid="credit-note">{t("finance.invoices.creditNote")}</Button>
                <Button onClick={() => setDialog("debit-note")}>{t("finance.invoices.debitNote")}</Button>
                <Button variant="ghost" onClick={() => setDialog("cancel")}>{t("finance.invoices.cancel")}</Button>
              </div>}
            </div>)}
          <ErrorNote error={run.error} />
        </div>)}
      {(dialog === "credit-note" || dialog === "debit-note") && <NoteDialog caseId={caseId} invoice={invoice} kind={dialog} onClose={() => setDialog(null)} />}
      {vatAsk && <VatDecisionDialog caseId={caseId} invoiceId={invoice.id} rate={vatAsk.rate} onClose={() => setVatAsk(null)} />}
      {dialog === "cancel" && <ReasonDialog title={t("finance.invoices.cancel")} label={t("finance.reason")} busy={run.isPending} error={run.error}
        onClose={() => setDialog(null)} onSave={(reason) => void run.mutateAsync({ path: `/api/sales-invoices/${invoice.id}/cancel`, body: { reason } }).then(() => setDialog(null))} />}
    </li>
  );
}

export function InvoicesCard({ caseId, invoices, execution, readOnly }: { caseId: string; invoices: SalesInvoice[]; execution: CaseExecution | undefined; readOnly?: boolean }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const [dialogFor, setDialogFor] = useState<string | null>(null);
  const orders = readOnly ? [] : (execution?.sales_orders ?? []).filter((o) => !["draft", "cancelled"].includes(o.status));
  return (
    <Card padded={false} title={t("finance.invoices.title")} actions={<span className="flex flex-wrap gap-1.5">{orders.map((o) => (
      <span key={o.id} className="flex gap-1.5">
        <Button icon="plus" data-testid="invoice-new" onClick={() => setDialogFor(o.id)}>{t("finance.invoices.new")}</Button>
        <Button data-testid="invoice-rest" busy={run.isPending} onClick={() => run.mutate({ path: `/api/sales-orders/${o.id}/invoice-rest` })}>{t("finance.invoices.rest")}</Button>
      </span>))}</span>}>
      <div className="px-4"><ErrorNote error={run.error} /></div>
      {invoices.length === 0 ? <EmptyState>{t("finance.invoices.none")}</EmptyState> : (
        <ul className="max-h-[32rem] divide-y divide-line overflow-y-auto">{invoices.map((inv) => <InvoiceItem key={inv.id} caseId={caseId} invoice={inv} readOnly={readOnly} />)}</ul>)}
      {dialogFor && <NewInvoiceDialog caseId={caseId} orderId={dialogFor} onClose={() => setDialogFor(null)} />}
    </Card>
  );
}
