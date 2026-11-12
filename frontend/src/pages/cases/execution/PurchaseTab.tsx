/** Case tab «خرید» (v0.7.0): purchase orders per supplier, approval, outputs, sending (with the customer-prepayment
 * gate), confirmation, ready date, production status, revisions, supplier milestones and receipts. */
import { DraftMessageButton } from "../../../components/AiActions";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Badge, Bdi, Button, Card, Checkbox, DateInput, EmptyState, ErrorNote, ErrorState, Field, Input, Loading, Modal, Select, Textarea } from "../../../design/components";
import { ApiError } from "../../../lib/api";
import { manualPoSteps, PO_TONE } from "../../../lib/execution";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseDetail, ClaimSuggestion, PurchaseOrderRow, ReceiptRow } from "../../../lib/types";
import { Money } from "../../sourcing/shared";
import { dateOrNull, FilePick, MilestonesCard, OutputButtons, PartyLink, ReasonDialog, useExecution, useRun, type Body, type Method } from "./shared";
import { IncotermField } from "../../../components/fields";

type Run = (path: string, body?: Body, method?: Method) => Promise<unknown>;

/** "Open claim" from a failed inspection or a damaged / short receipt: the claim is created, then shown on its tab. */
export function OpenClaimButton({ suggestion, caseId }: { suggestion: ClaimSuggestion; caseId: string }) {
  const { t } = useTranslation();
  const m = useRun(caseId);
  const [, setParams] = useSearchParams();
  const body = Object.fromEntries(Object.entries(suggestion).filter(([k, v]) => k !== "case_id" && v !== null && v !== undefined));
  return (
    <span className="inline-flex items-center gap-1.5">
      <Button variant="danger" busy={m.isPending} data-testid="open-claim"
        onClick={() => m.mutateAsync({ path: "/api/claims", body }).then(() => setParams({ tab: "delivery" }, { replace: true }))}>{t("execution.claims.open")}</Button>
      <ErrorNote error={m.error} />
    </span>
  );
}

function SendDialog({ po, onClose, run }: { po: PurchaseOrderRow; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const [channel, setChannel] = useState("email");
  const [gate, setGate] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const send = () => run(`/api/purchase-orders/${po.id}/mark-sent`, { channel, ...(gate ? { confirm_without_prepayment: true, reason } : {}) })
    .then(onClose, (err) => { if (err instanceof ApiError && err.code === "customer_prepayment_missing") setGate(true); setError(err); });
  return (
    <Modal open title={t("execution.purchase.markSent")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="sent-save" disabled={gate && !reason.trim()} onClick={send}>{t("execution.purchase.markSent")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="send-dialog">
        <Field label={t("execution.purchase.channel")} htmlFor="po-channel"><Select id="po-channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
          {["email", "whatsapp", "phone", "in_person", "letter", "other"].map((c) => <option key={c} value={c}>{t(`execution.purchase.channels.${c}`)}</option>)}</Select></Field>
        {gate && <div className="flex flex-col gap-2 rounded-md bg-warning-soft p-2 text-sm text-warning" role="alert" data-testid="prepayment-gate">
          <span>{t("execution.purchase.prepaymentMissing")}</span>
          <Field label={t("execution.purchase.prepaymentReason")} htmlFor="po-gate"><Input id="po-gate" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field></div>}
        {!gate && <ErrorNote error={error} />}
      </div>
    </Modal>
  );
}

function ConfirmDialog({ po, onClose, run }: { po: PurchaseOrderRow; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const [ref, setRef] = useState(po.supplier_ref ?? "");
  const [ready, setReady] = useState<Date | null>(dateOrNull(po.ready_due_on));
  const [doc, setDoc] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open title={t("execution.purchase.confirm")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="po-confirm-save"
        onClick={() => run(`/api/purchase-orders/${po.id}/confirm`, { supplier_ref: ref || null, confirmed_ready_on: ready ? toDateString(ready) : null,
          confirmation_document_id: doc }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="po-confirm-dialog">
        <Field label={t("execution.purchase.supplierRef")} htmlFor="po-sref"><Input id="po-sref" dir="ltr" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
        <Field label={t("execution.purchase.confirmedReady")} htmlFor="po-cready"><DateInput id="po-cready" value={ready} onChange={setReady} /></Field>
        <Field label={t("execution.purchase.confirmationDocument")} htmlFor="po-cdoc"><FilePick id="po-cdoc" value={doc} onChange={setDoc} /></Field>
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

function ReadyDateDialog({ po, onClose, run }: { po: PurchaseOrderRow; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const [ready, setReady] = useState<Date | null>(dateOrNull(po.ready_due_on));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open title={t("execution.purchase.moveReady")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!ready || !reason.trim()} data-testid="ready-save"
        onClick={() => run(`/api/purchase-orders/${po.id}/ready-date`, { ready_due_on: toDateString(ready!), reason }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label={t("execution.purchase.readyDue")} htmlFor="po-ready"><DateInput id="po-ready" value={ready} onChange={setReady} /></Field>
        <Field label={t("execution.reason")} htmlFor="po-ready-reason"><Input id="po-ready-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

function ReceiptDialog({ po, onClose, run }: { po: PurchaseOrderRow; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const [on, setOn] = useState<Date | null>(new Date());
  const [doc, setDoc] = useState<string | null>(null);
  const [lines, setLines] = useState(po.items.map((i) => ({ id: i.id, description: i.description, quantity: String(Math.max(0, Number(i.quantity) - Number(i.received_quantity))), condition: "ok" })));
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open wide title={t("execution.receipts.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="receipt-save" disabled={!on}
        onClick={() => run("/api/receipts", { purchase_order_id: po.id, received_on: toDateString(on!), document_id: doc,
          items: lines.filter((l) => Number(l.quantity) > 0 || l.condition === "short").map((l) => ({ purchase_order_item_id: l.id, quantity: l.quantity || "0", condition: l.condition })) })
          .then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="receipt-dialog">
        <div className="flex flex-wrap gap-3">
          <Field label={t("execution.receipts.receivedOn")} htmlFor="rc-on"><DateInput id="rc-on" value={on} onChange={setOn} /></Field>
          <Field label={t("execution.receipts.document")} htmlFor="rc-doc"><FilePick id="rc-doc" value={doc} onChange={setDoc} /></Field>
        </div>
        <ul className="flex flex-col gap-1.5">{lines.map((l, i) => (
          <li key={l.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="min-w-48 flex-1" dir="auto">{l.description}</span>
            <Input dir="ltr" className="w-24" aria-label={`${t("execution.receipts.quantity")} ${l.description}`} value={l.quantity}
              onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} />
            <Select aria-label={`${t("execution.receipts.condition")} ${l.description}`} className="w-auto" value={l.condition}
              onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, condition: e.target.value } : x))}>
              {["ok", "damaged", "short"].map((c) => <option key={c} value={c}>{t(`execution.receipts.conditions.${c}`)}</option>)}</Select></li>))}</ul>
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

function ReceiptsList({ rows, po, caseId }: { rows: ReceiptRow[]; po: PurchaseOrderRow; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const desc = Object.fromEntries(po.items.map((i) => [i.id, i.description]));
  if (!rows.length) return null;
  return (
    <ul className="flex flex-col gap-1.5 text-sm" data-testid="receipts">{rows.map((r) => (
      <li key={r.id} className="rounded-xl border border-line px-3 py-2">
        <span className="flex flex-wrap items-center gap-2"><b>{t("execution.receipts.title")}</b><span className="tabular-nums">{f.day(r.received_on)}</span>
          {r.claim_suggestion && <OpenClaimButton suggestion={r.claim_suggestion} caseId={caseId} />}</span>
        <ul className="text-xs">{r.items.map((i) => <li key={i.id}><span dir="auto">{desc[i.purchase_order_item_id]}</span>: <span className="tabular-nums">{f.num(i.quantity)}</span>
          {i.condition !== "ok" && <Badge tone="danger">{t(`execution.receipts.conditions.${i.condition}`)}</Badge>}</li>)}</ul>
      </li>))}</ul>
  );
}

function PoCard({ po, caseId, receipts }: { po: PurchaseOrderRow; caseId: string; receipts: ReceiptRow[] }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const run: Run = (path, body, method = "POST") => m.mutateAsync({ path, body, method });
  const [dialog, setDialog] = useState<"send" | "confirm" | "ready" | "receipt" | "cancel" | "above" | null>(null);
  const [terms, setTerms] = useState(po.terms_text ?? "");
  const draft = po.status === "draft";
  const patch = (body: Body) => m.mutate({ path: `/api/purchase-orders/${po.id}`, body, method: "PATCH" });
  const approve = (body?: Body) => run(`/api/purchase-orders/${po.id}/approve`, body).catch((err) => { if (err instanceof ApiError && err.code === "po_above_cost_sheet") setDialog("above"); });
  if (po.status === "superseded") return <p className="text-xs text-muted"><Bdi ltr>{po.number}</Bdi> · {t("execution.purchase.statuses.superseded")}</p>;
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{t("execution.purchase.title")} <Bdi ltr className="font-mono">{po.number}</Bdi>
      <Badge tone={PO_TONE[po.status]}>{t(`execution.purchase.statuses.${po.status}`)}</Badge>
      <span className="text-sm font-normal"><PartyLink party={po.supplier} /></span>
      <span className="text-xs font-normal text-muted">{po.currency} · {po.language === "fa" ? "فارسی" : "English"}</span></span>}
      actions={<span className="flex flex-wrap gap-1.5">
        {draft && <Button variant="primary" onClick={() => void approve()} data-testid="po-approve">{t("execution.purchase.approve")}</Button>}
        {po.status === "approved" && <Button variant="primary" onClick={() => setDialog("send")} data-testid="po-send">{t("execution.purchase.markSent")}</Button>}
        {po.status === "sent" && <Button variant="primary" onClick={() => setDialog("confirm")} data-testid="po-confirm">{t("execution.purchase.confirm")}</Button>}
        {manualPoSteps(po.status).map((s) => <Button key={s} variant="ghost" onClick={() => run(`/api/purchase-orders/${po.id}/status`, { status: s })} data-testid={`po-status-${s}`}>{t(`execution.purchase.statuses.${s}`)}</Button>)}
        {!["draft", "cancelled", "superseded", "received", "closed"].includes(po.status) && <Button variant="ghost" onClick={() => run(`/api/purchase-orders/${po.id}/revise`)}>{t("execution.purchase.revise")}</Button>}
        {!["cancelled", "superseded", "received", "closed"].includes(po.status) && <Button variant="ghost" onClick={() => setDialog("cancel")}>{t("execution.order.cancel")}</Button>}
        {draft && <Button variant="ghost" onClick={() => run(`/api/purchase-orders/${po.id}`, undefined, "DELETE")}>{t("common.remove")}</Button>}
      </span>}>
      <div className="flex flex-col gap-3" data-testid="purchase-order" data-po={po.id}>
        {po.above_cost_sheet.some((x) => x.check !== "fx_missing") && <p className="rounded-md bg-warning-soft px-3 py-2 text-sm text-warning" role="alert">{t("execution.purchase.aboveCost", { n: f.num(po.above_cost_sheet.filter((x) => x.check !== "fx_missing").length) })}</p>}
        {po.above_cost_sheet.filter((x) => x.check === "fx_missing").map((x) => (
          <p key={x.purchase_order_item_id} className="rounded-md bg-warning-soft px-3 py-2 text-sm text-warning" role="alert" data-testid="po-fx-missing">
            <span dir="auto">{x.description}</span>: {t("execution.purchase.fxMissing", { from: x.currency, to: x.cost_sheet_currency ?? "" })}</p>))}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Field label={t("execution.purchase.language")} htmlFor={`po-lang-${po.id}`}><Select id={`po-lang-${po.id}`} disabled={!draft} value={po.language} onChange={(e) => patch({ language: e.target.value })}>
            <option value="fa">فارسی</option><option value="en">English</option></Select></Field>
          <Field label={t("execution.purchase.incoterm")} htmlFor={`po-inc-${po.id}`}>{draft ? <IncotermField id={`po-inc-${po.id}`} value={po.incoterm} onChange={(v) => patch({ incoterm: v })} /> : <span className="text-sm">{po.incoterm ?? "—"} {po.incoterm_place ?? ""}</span>}</Field>
          <Field label={t("execution.purchase.readyDue")} htmlFor={`po-rd-${po.id}`}><span className="flex flex-wrap items-center gap-1.5">
            {draft ? <DateInput id={`po-rd-${po.id}`} value={dateOrNull(po.ready_due_on)} onChange={(d) => patch({ ready_due_on: d ? toDateString(d) : null })} />
              : <span className="text-sm tabular-nums">{po.ready_due_on ? f.day(po.ready_due_on) : "—"}</span>}
            {!draft && !["cancelled", "superseded", "received", "closed"].includes(po.status) && <Button variant="ghost" onClick={() => setDialog("ready")} data-testid="po-move-ready">{t("execution.purchase.moveReady")}</Button>}</span></Field>
          <Field label={t("execution.purchase.directToCustomer")} htmlFor={`po-direct-${po.id}`}>
            <Checkbox id={`po-direct-${po.id}`} label={t("execution.purchase.directHint")} checked={po.direct_to_customer} onChange={(v) => patch({ direct_to_customer: v })} /></Field>
        </div>
        {po.supplier_ref && <p className="text-sm">{t("execution.purchase.supplierRef")}: <Bdi ltr>{po.supplier_ref}</Bdi>{po.confirmed_ready_on && <> · {t("execution.purchase.confirmedReady")}: <span className="tabular-nums">{f.day(po.confirmed_ready_on)}</span></>}</p>}
        <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="po-items">
          <thead><tr className="border-b border-line text-xs text-muted">{["description", "quantity", "unitPrice", "total", "received"].map((h) => <th key={h} className="px-3 py-2 text-start whitespace-nowrap">{t(`execution.order.${h}`)}</th>)}</tr></thead>
          <tbody>{po.items.map((i) => (
            <tr key={i.id} className="border-b border-line">
              <td className="px-3 py-2" dir="auto">{i.description}</td>
              <td className="px-3 py-2 tabular-nums">{f.num(i.quantity)} {i.unit ?? ""}</td>
              <td className="px-3 py-2">{draft ? <Input dir="ltr" className="w-32" aria-label={`${t("execution.order.unitPrice")} ${i.description}`} defaultValue={Number(i.unit_price)}
                onBlur={(e) => Number(e.target.value) !== Number(i.unit_price) && run(`/api/purchase-order-items/${i.id}`, { unit_price: e.target.value }, "PATCH")} /> : <Money amount={i.unit_price} currency={po.currency} />}</td>
              <td className="px-3 py-2"><Money amount={i.total} currency={po.currency} /></td>
              <td className="px-3 py-2 tabular-nums text-xs">{f.num(i.received_quantity)} / {f.num(i.quantity)}</td>
            </tr>))}</tbody></table></div>
        <p className="text-sm">{t("execution.order.total")}: <b><Money amount={po.total} currency={po.currency} /></b></p>
        <Field label={t("execution.purchase.terms")} htmlFor={`po-terms-${po.id}`}><Textarea id={`po-terms-${po.id}`} dir="auto" rows={4} disabled={!draft} value={terms}
          onChange={(e) => setTerms(e.target.value)} onBlur={() => terms !== (po.terms_text ?? "") && patch({ terms_text: terms })} /></Field>
        <OutputButtons base={`/api/purchase-orders/${po.id}`} outputs={po.outputs} />
        {/* v0.9.0: the cover message drafted by AI opens in the mail client; BOMS sends nothing */}
        <DraftMessageButton target="purchase_order" targetId={po.id} onCommitted={(r) => { if (typeof r.mailto === "string") window.location.href = r.mailto; }} />
        {po.followups.length > 0 && <p className="text-xs text-muted" data-testid="po-followups">{po.followups.map((x) => `${x.action} · ${f.day(x.due_on)}`).join("، ")}</p>}
        {po.changes.length > 0 && <ul className="text-xs text-muted" data-testid="po-changes">{po.changes.map((c) => (
          <li key={c.id}>{t(`execution.fields.${c.field}`, { defaultValue: c.field })}: <bdi dir="ltr">{c.old_value ?? "—"}</bdi> → <bdi dir="ltr">{c.new_value ?? "—"}</bdi> · <span dir="auto">{c.reason}</span></li>))}</ul>}
        {po.price_override_reason && <p className="text-xs text-warning">{t("execution.purchase.priceOverride")}: <span dir="auto">{po.price_override_reason}</span></p>}
        {po.prepayment_override_reason && <p className="text-xs text-warning">{t("execution.purchase.prepaymentOverride")}: <span dir="auto">{po.prepayment_override_reason}</span></p>}
        {!po.direct_to_customer && ["sent", "confirmed", "in_production", "ready", "shipped"].includes(po.status) &&
          <span><Button onClick={() => setDialog("receipt")} data-testid="po-receipt">{t("execution.receipts.add")}</Button></span>}
        <ReceiptsList rows={receipts} po={po} caseId={caseId} />
        <ErrorNote error={m.error instanceof ApiError && m.error.code === "po_above_cost_sheet" ? null : m.error} />
      </div>
      {dialog === "send" && <SendDialog po={po} onClose={() => setDialog(null)} run={run} />}
      {dialog === "confirm" && <ConfirmDialog po={po} onClose={() => setDialog(null)} run={run} />}
      {dialog === "ready" && <ReadyDateDialog po={po} onClose={() => setDialog(null)} run={run} />}
      {dialog === "receipt" && <ReceiptDialog po={po} onClose={() => setDialog(null)} run={run} />}
      {dialog === "cancel" && <ReasonDialog title={t("execution.order.cancel")} label={t("execution.reason")} onClose={() => setDialog(null)}
        onSave={(reason) => run(`/api/purchase-orders/${po.id}/cancel`, { reason }).then(() => setDialog(null))} />}
      {dialog === "above" && <ReasonDialog title={t("execution.purchase.aboveCostTitle")} label={t("execution.purchase.aboveCostReason")} onClose={() => setDialog(null)}
        onSave={(reason) => void approve({ confirm_above_cost: true, reason }).then(() => setDialog(null))} />}
    </Card>
  );
}

export function PurchaseTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const ex = useExecution(caseData.id);
  const m = useRun(caseData.id);
  const [unresolved, setUnresolved] = useState<{ sales_order_item_id: string; description: string }[]>([]);
  if (ex.isLoading) return <Loading />;
  if (ex.error || !ex.data) return <ErrorState error={ex.error} onRetry={() => void ex.refetch()} />;
  const d = ex.data;
  const orders = d.sales_orders.filter((o) => ["confirmed", "in_progress", "delivered"].includes(o.status));
  return (
    <div className="flex flex-col gap-4" data-testid="purchase-tab">
      {orders.map((so) => (
        <div key={so.id} className="flex flex-wrap items-center gap-2 text-sm">
          <Button variant="primary" busy={m.isPending} data-testid="create-pos"
            onClick={() => m.mutateAsync({ path: `/api/sales-orders/${so.id}/purchase-orders` }).then((r) => setUnresolved((r as { unresolved: typeof unresolved }).unresolved))}>
            {t("execution.purchase.create", { number: so.number })}</Button>
          <span className="text-xs text-muted">{t("execution.purchase.createHint")}</span>
        </div>))}
      {orders.length === 0 && <EmptyState>{t("execution.purchase.needOrder")}</EmptyState>}
      {unresolved.length > 0 && <div className="rounded-md bg-warning-soft px-3 py-2 text-sm text-warning" role="alert" data-testid="unresolved">
        {t("execution.purchase.unresolved")}: {unresolved.map((u) => u.description).join("، ")}</div>}
      <ErrorNote error={m.error} />
      {d.purchase_orders.map((po) => (
        <div key={po.id} className="flex flex-col gap-4" data-po-card={po.id}>
          <PoCard po={po} caseId={caseData.id} receipts={d.receipts.filter((r) => r.purchase_order_id === po.id)} />
          {po.status !== "superseded" && <MilestonesCard title={t("execution.milestones.out")} rows={po.milestones} owner={{ purchase_order_id: po.id }} currency={po.currency}
            caseId={caseData.id} offerTerms={po.offer_payment_terms} testId={`milestones-out-${po.currency}`} />}
        </div>))}
    </div>
  );
}
