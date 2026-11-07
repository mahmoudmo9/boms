/** Case tab «تحویل و ادعا» (v0.7.0): deliveries to the customer item by item (with reversal) and claims. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../../components/Bdi";
import { DateInput } from "../../../components/DateInput";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Loading, Modal, Select, Textarea } from "../../../components/ui";
import { CLAIM_TONE, itemProgress } from "../../../lib/execution";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseDetail, CaseExecution, ClaimRow, SalesOrderRow } from "../../../lib/types";
import { CurrencySelect, Money } from "../../sourcing/shared";
import { FilePick, partyName, ReasonDialog, useExecution, useRun, type Body, type Method } from "./shared";

type Run = (path: string, body?: Body, method?: Method) => Promise<unknown>;

export function ItemProgressBar({ ordered, delivered }: { ordered: string; delivered: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const p = itemProgress(ordered, delivered);
  return (
    <span className="inline-flex min-w-40 items-center gap-2" data-testid="item-progress" data-complete={p.complete}>
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-2"><span className={`block h-full ${p.complete ? "bg-success" : "bg-accent"}`} style={{ width: `${p.percent}%` }} /></span>
      <span className={`text-xs whitespace-nowrap ${p.complete ? "text-success" : ""}`}>{t("execution.delivery.itemProgress", { done: f.num(p.done), total: f.num(p.total) })}</span>
    </span>
  );
}

function DeliveryDialog({ so, onClose, run }: { so: SalesOrderRow; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const [on, setOn] = useState<Date | null>(new Date());
  const [form, setForm] = useState({ receiver_name: "", delivery_place: so.delivery_place ?? "", note: "" });
  const [doc, setDoc] = useState<string | null>(null);
  const [qty, setQty] = useState<Record<string, string>>(Object.fromEntries(so.items.map((i) => [i.id, String(Math.max(0, Number(i.quantity) - Number(i.delivered)))])));
  const [error, setError] = useState<unknown>(null);
  const items = so.items.map((i) => ({ sales_order_item_id: i.id, quantity: qty[i.id] })).filter((x) => Number(x.quantity) > 0);
  return (
    <Modal open wide title={t("execution.delivery.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!on || items.length === 0} data-testid="delivery-save"
        onClick={() => run("/api/deliveries", { sales_order_id: so.id, delivered_on: toDateString(on!), receiver_name: form.receiver_name || null,
          delivery_place: form.delivery_place || null, note: form.note || null, receipt_document_id: doc, items }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="delivery-dialog">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Field label={t("execution.delivery.on")} htmlFor="dl-on"><DateInput id="dl-on" value={on} onChange={setOn} /></Field>
          <Field label={t("execution.delivery.receiver")} htmlFor="dl-recv"><Input id="dl-recv" dir="auto" value={form.receiver_name} onChange={(e) => setForm({ ...form, receiver_name: e.target.value })} /></Field>
          <Field label={t("execution.delivery.place")} htmlFor="dl-place"><Input id="dl-place" dir="auto" value={form.delivery_place} onChange={(e) => setForm({ ...form, delivery_place: e.target.value })} /></Field>
          <Field label={t("execution.delivery.receipt")} htmlFor="dl-doc"><FilePick id="dl-doc" value={doc} onChange={setDoc} /></Field>
        </div>
        <ul className="flex flex-col gap-1.5">{so.items.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="min-w-48 flex-1" dir="auto">{i.description}</span>
            <ItemProgressBar ordered={i.quantity} delivered={i.delivered} />
            <Input dir="ltr" className="w-24" aria-label={`${t("execution.delivery.quantity")} ${i.description}`} value={qty[i.id]} onChange={(e) => setQty({ ...qty, [i.id]: e.target.value })} /></li>))}</ul>
        <Field label={t("execution.delivery.note")} htmlFor="dl-note"><Input id="dl-note" dir="auto" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

function DeliveriesCard({ so, data, caseId }: { so: SalesOrderRow; data: CaseExecution; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const run: Run = (path, body, method = "POST") => m.mutateAsync({ path, body, method });
  const [adding, setAdding] = useState(false);
  const [reversing, setReversing] = useState<string | null>(null);
  const rows = data.deliveries.filter((d) => d.sales_order_id === so.id);
  const desc = Object.fromEntries(so.items.map((i) => [i.id, i.description]));
  return (
    <Card padded={false} title={<span className="flex flex-wrap items-center gap-2">{t("execution.delivery.title")} <Bdi ltr className="font-mono text-sm">{so.number}</Bdi>
      <Badge tone={so.status === "delivered" ? "success" : "accent"}>{t("execution.order.itemsDelivered", { done: f.num(so.progress.items_delivered), total: f.num(so.progress.items_total) })}</Badge></span>}
      actions={["confirmed", "in_progress"].includes(so.status) && <Button variant="primary" icon="plus" onClick={() => setAdding(true)} data-testid="add-delivery">{t("execution.delivery.add")}</Button>}>
      <ul className="divide-y divide-line border-b border-line" data-testid="delivery-progress">{so.items.map((i) => (
        <li key={i.id} className="flex flex-wrap items-center gap-2 px-4 py-1.5 text-sm"><span className="min-w-48 flex-1" dir="auto">{i.description}</span><ItemProgressBar ordered={i.quantity} delivered={i.delivered} /></li>))}</ul>
      {rows.length === 0 ? <EmptyState>{t("execution.delivery.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid="deliveries">{rows.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
            <span className="tabular-nums">{f.day(d.delivered_on)}</span>
            {d.receiver_name && <span dir="auto">{d.receiver_name}</span>}
            <span className="text-xs text-muted">{d.items.map((x) => `${desc[x.sales_order_item_id] ?? ""}: ${f.num(x.quantity)}`).join("، ")}</span>
            {d.receipt_document_id && <a className="text-xs text-accent hover:underline" href={`/documents/${d.receipt_document_id}`}>{t("execution.delivery.receipt")}</a>}
            {so.status !== "closed" && <Button variant="ghost" className="ms-auto" onClick={() => setReversing(d.id)}>{t("execution.delivery.reverse")}</Button>}
          </li>))}</ul>
      )}
      <div className="px-4 pb-2"><ErrorNote error={m.error} /></div>
      {adding && <DeliveryDialog so={so} onClose={() => setAdding(false)} run={run} />}
      {reversing && <ReasonDialog title={t("execution.delivery.reverse")} label={t("execution.reason")} onClose={() => setReversing(null)}
        onSave={(reason) => void run(`/api/deliveries/${reversing}/reverse`, { reason }).then(() => setReversing(null))} />}
    </Card>
  );
}

function ClaimDialog({ data, onClose, run }: { data: CaseExecution; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const caseId = data.sales_orders[0]?.case_id;
  const parties = new Map<string, string>();
  data.purchase_orders.forEach((p) => parties.set(p.supplier_party_id, partyName(p.supplier, f.lang)));
  data.sales_orders.forEach((s) => parties.set(s.customer_party_id, partyName(s.customer, f.lang)));
  const [form, setForm] = useState({ direction: "against_supplier", kind: "defect", counterparty_id: data.purchase_orders[0]?.supplier_party_id ?? [...parties.keys()][0] ?? "",
    purchase_order_id: "", amount: "", currency: (data.purchase_orders[0]?.currency ?? null) as string | null, notes: "" });
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open wide title={t("execution.claims.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!form.counterparty_id} data-testid="claim-save"
        onClick={() => run("/api/claims", { case_id: caseId, direction: form.direction, kind: form.kind, counterparty_id: form.counterparty_id,
          purchase_order_id: form.purchase_order_id || null, claimed_amount: form.amount || null, claimed_amount_currency: form.amount ? form.currency : null,
          notes: form.notes || null }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="claim-dialog">
        <Field label={t("execution.claims.direction")} htmlFor="cl-dir"><Select id="cl-dir" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
          {["against_supplier", "against_carrier", "against_insurer", "from_customer"].map((d) => <option key={d} value={d}>{t(`execution.claims.directions.${d}`)}</option>)}</Select></Field>
        <Field label={t("execution.claims.kind")} htmlFor="cl-kind"><Select id="cl-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {["defect", "shortage", "delay", "damage", "wrong_item", "documents", "other"].map((k) => <option key={k} value={k}>{t(`execution.claims.kinds.${k}`)}</option>)}</Select></Field>
        <Field label={t("execution.claims.counterparty")} htmlFor="cl-party"><Select id="cl-party" value={form.counterparty_id} onChange={(e) => setForm({ ...form, counterparty_id: e.target.value })}>
          {[...parties].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</Select></Field>
        <Field label={t("execution.claims.po")} htmlFor="cl-po"><Select id="cl-po" value={form.purchase_order_id} onChange={(e) => {
          const po = data.purchase_orders.find((p) => p.id === e.target.value);   // v0.8.0: a PO defaults the counterparty to its supplier
          setForm({ ...form, purchase_order_id: e.target.value, counterparty_id: po?.supplier_party_id ?? form.counterparty_id });
        }}>
          <option value="">—</option>{data.purchase_orders.filter((p) => p.status !== "superseded").map((p) => <option key={p.id} value={p.id}>{p.number}</option>)}</Select></Field>
        <Field label={t("execution.claims.amount")} htmlFor="cl-amount"><span className="flex gap-1.5"><Input id="cl-amount" dir="ltr" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <CurrencySelect value={form.currency} onChange={(v) => setForm({ ...form, currency: v })} /></span></Field>
        <Field label={t("execution.claims.notes")} htmlFor="cl-notes"><Textarea id="cl-notes" dir="auto" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
        <div className="sm:col-span-2 xl:col-span-3"><ErrorNote error={error} /></div>
      </div>
    </Modal>
  );
}

function ClaimItem({ c, run }: { c: ClaimRow; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [status, setStatus] = useState(c.status);
  const [resolution, setResolution] = useState({ resolution: "credit_note", amount: "" });
  const save = () => run(`/api/claims/${c.id}/status`, { status, ...(status === "resolved" ? { resolution: resolution.resolution, resolution_amount: resolution.amount || null } : {}) });
  return (
    <li className="flex flex-col gap-1.5 px-4 py-2 text-sm" data-testid="claim" data-claim={c.id}>
      <span className="flex flex-wrap items-center gap-2">
        <Badge tone={CLAIM_TONE[c.status]}>{t(`execution.claims.statuses.${c.status}`)}</Badge>
        <b>{t(`execution.claims.kinds.${c.kind}`)}</b><span className="text-xs text-muted">{t(`execution.claims.directions.${c.direction}`)}</span>
        <span dir="auto">{partyName(c.counterparty, f.lang)}</span>
        {c.claimed_amount && <Money amount={c.claimed_amount} currency={c.claimed_amount_currency} />}
        <span className="text-xs tabular-nums text-muted">{f.day(c.opened_on)}</span>
      </span>
      {c.notes && <span className="text-xs" dir="auto">{c.notes}</span>}
      {c.resolution && <span className="text-xs text-success">{t(`execution.claims.resolutions.${c.resolution}`)}{c.resolution_amount && <> · <Money amount={c.resolution_amount} currency={c.resolution_amount_currency} /></>}</span>}
      {c.followups.length > 0 && <span className="text-xs text-muted">{c.followups.map((x) => `${x.action} · ${f.day(x.due_on)}`).join("، ")}</span>}
      <span className="flex flex-wrap items-center gap-1.5">
        <Select aria-label={t("execution.claims.status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["open", "submitted", "negotiating", "resolved", "rejected", "withdrawn"].map((s) => <option key={s} value={s}>{t(`execution.claims.statuses.${s}`)}</option>)}</Select>
        {status === "resolved" && <>
          <Select aria-label={t("execution.claims.resolution")} className="w-auto" value={resolution.resolution} onChange={(e) => setResolution({ ...resolution, resolution: e.target.value })}>
            {["replacement", "credit_note", "refund", "discount", "repair", "none"].map((r) => <option key={r} value={r}>{t(`execution.claims.resolutions.${r}`)}</option>)}</Select>
          <Input dir="ltr" className="w-28" aria-label={t("execution.claims.resolutionAmount")} placeholder={t("execution.claims.resolutionAmount")} value={resolution.amount}
            onChange={(e) => setResolution({ ...resolution, amount: e.target.value })} /></>}
        <Button disabled={status === c.status} onClick={() => void save()} data-testid="claim-status-save">{t("common.save")}</Button>
      </span>
    </li>
  );
}

export function DeliveryTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const ex = useExecution(caseData.id);
  const m = useRun(caseData.id);
  const [adding, setAdding] = useState(false);
  if (ex.isLoading) return <Loading />;
  if (ex.error || !ex.data) return <ErrorNote error={ex.error} />;
  const d = ex.data;
  const run: Run = (path, body, method = "POST") => m.mutateAsync({ path, body, method });
  const orders = d.sales_orders.filter((o) => ["confirmed", "in_progress", "delivered", "closed"].includes(o.status));
  return (
    <div className="flex flex-col gap-4" data-testid="delivery-tab">
      {orders.length === 0 && <EmptyState>{t("execution.delivery.needOrder")}</EmptyState>}
      {orders.map((so) => <DeliveriesCard key={so.id} so={so} data={d} caseId={caseData.id} />)}
      <Card padded={false} title={t("execution.claims.title")} actions={<Button icon="plus" onClick={() => setAdding(true)} data-testid="add-claim">{t("execution.claims.add")}</Button>}>
        {d.claims.length === 0 ? <EmptyState>{t("execution.claims.none")}</EmptyState>
          : <ul className="divide-y divide-line" data-testid="claims">{d.claims.map((c) => <ClaimItem key={`${c.id}-${c.status}`} c={c} run={run} />)}</ul>}
        <div className="px-4 pb-2"><ErrorNote error={m.error} /></div>
      </Card>
      {adding && <ClaimDialog data={d} onClose={() => setAdding(false)} run={run} />}
    </div>
  );
}
