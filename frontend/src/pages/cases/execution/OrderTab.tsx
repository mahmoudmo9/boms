/** Case tab «سفارش» (v0.7.0): the sales order with the signed document, amendments, customer milestones, the cash
 * position and the order acknowledgement output. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../../components/Bdi";
import { DateInput } from "../../../components/DateInput";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Loading, Modal, Select, Stat, Textarea } from "../../../components/ui";
import { cashRows, itemProgress, SO_TONE } from "../../../lib/execution";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseDetail, CaseExecution, CashPosition, SalesOrderRow } from "../../../lib/types";
import { Money } from "../../sourcing/shared";
import { dateOrNull, FilePick, MilestonesCard, OutputButtons, PartyLink, ReasonDialog, useExecution, useRun, type Body } from "./shared";

export function CashCard({ cash }: { cash: CashPosition }) {
  const { t } = useTranslation();
  const f = useFormat();
  const rows = cashRows(cash);
  return (
    <Card title={t("execution.cash.title")}>
      <div className="flex flex-col gap-3" data-testid="cash-position">
        {cash.plan && <p className="text-xs text-muted">{t("execution.cash.plan")}: <Money amount={cash.plan.exposure} currency={cash.plan.currency} /></p>}
        {rows.length === 0 ? <p className="text-sm text-muted">{t("execution.cash.none")}</p> : rows.map((r) => (
          <div key={r.currency} className="grid gap-2 sm:grid-cols-3" data-currency={r.currency}>
            <Stat label={t("execution.cash.received")} value={<Money amount={r.received} currency={r.currency} />} />
            <Stat label={t("execution.cash.paid")} value={<Money amount={r.paid} currency={r.currency} />} />
            <Stat label={t("execution.cash.net")} tone={r.tone} value={<Money amount={r.net} currency={r.currency} />} />
            {(Number(r.outstandingIn) > 0 || Number(r.outstandingOut) > 0) && <p className="text-xs text-muted sm:col-span-3">
              {t("execution.cash.outstanding", { in: f.num(r.outstandingIn), out: f.num(r.outstandingOut), cur: r.currency })}</p>}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Candidates({ data, caseId }: { data: CaseExecution; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  if (data.candidates.length === 0 && data.sales_orders.some((o) => o.status !== "cancelled")) return null;
  return (
    <Card title={t("execution.order.create")}>
      <div className="flex flex-col gap-2 text-sm" data-testid="so-candidates">
        {data.candidates.map((c) => (
          <div key={c.quote_id ?? c.tender_proposal_id} className="flex flex-wrap items-center gap-2 rounded-md bg-accent-soft px-3 py-2">
            <span>{c.source === "quote" ? t("execution.order.fromQuote") : t("execution.order.fromTender")}</span>
            <Bdi ltr className="font-mono">{c.number ?? "—"}</Bdi>{c.status && <Badge>{t(`sourcing.status.quote.${c.status}`)}</Badge>}
            <Money amount={c.total} currency={c.currency} />
            <Button variant="primary" className="ms-auto" busy={m.isPending} data-testid="create-so"
              onClick={() => m.mutate(c.source === "quote" ? { path: "/api/sales-orders/from-quote", body: { quote_id: c.quote_id } }
                : { path: "/api/sales-orders/from-proposal", body: { tender_proposal_id: c.tender_proposal_id } })}>{t("execution.order.createButton")}</Button>
          </div>
        ))}
        {data.candidates.length === 0 && <p className="text-muted">{t("execution.order.noCandidate")}</p>}
        <span><Button variant="ghost" onClick={() => m.mutate({ path: `/api/cases/${caseId}/sales-orders`, body: {} })} data-testid="create-so-manual">{t("execution.order.manual")}</Button></span>
        <ErrorNote error={m.error} />
        {f.lang && null}
      </div>
    </Card>
  );
}

function AmendDialog({ so, onClose, run }: { so: SalesOrderRow; onClose: () => void; run: (path: string, body?: Body) => Promise<unknown> }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const [doc, setDoc] = useState<string | null>(null);
  const [due, setDue] = useState<Date | null>(dateOrNull(so.delivery_due_on));
  const [terms, setTerms] = useState({ payment_terms: so.payment_terms ?? "", delivery_terms: so.delivery_terms ?? "" });
  const [items, setItems] = useState<Record<string, { quantity: string; unit_price: string }>>(
    Object.fromEntries(so.items.map((i) => [i.id, { quantity: String(Number(i.quantity)), unit_price: String(Number(i.unit_price)) }])));
  const [error, setError] = useState<unknown>(null);
  const save = () => {
    const changes: Body = {};
    if ((due ? toDateString(due) : null) !== so.delivery_due_on) changes.delivery_due_on = due ? toDateString(due) : null;
    if (terms.payment_terms !== (so.payment_terms ?? "")) changes.payment_terms = terms.payment_terms || null;
    if (terms.delivery_terms !== (so.delivery_terms ?? "")) changes.delivery_terms = terms.delivery_terms || null;
    const rows = so.items.flatMap((i) => {
      const x = items[i.id];
      const out: Body = { sales_order_item_id: i.id };
      if (Number(x.quantity) !== Number(i.quantity)) out.quantity = x.quantity;
      if (Number(x.unit_price) !== Number(i.unit_price)) out.unit_price = x.unit_price;
      return Object.keys(out).length > 1 ? [out] : [];
    });
    run(`/api/sales-orders/${so.id}/amend`, { reason, document_id: doc, changes, items: rows }).then(onClose, setError);
  };
  return (
    <Modal open wide title={t("execution.order.amend")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!reason.trim()} onClick={save} data-testid="amend-save">{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="amend-dialog">
        <Field label={t("execution.order.amendReason")} htmlFor="am-reason"><Input id="am-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <Field label={t("execution.order.amendDocument")} htmlFor="am-doc"><FilePick id="am-doc" value={doc} onChange={setDoc} /></Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("execution.order.deliveryDue")} htmlFor="am-due"><DateInput id="am-due" value={due} onChange={setDue} /></Field>
          <Field label={t("execution.order.paymentTerms")} htmlFor="am-pay"><Input id="am-pay" dir="auto" value={terms.payment_terms} onChange={(e) => setTerms({ ...terms, payment_terms: e.target.value })} /></Field>
          <Field label={t("execution.order.deliveryTerms")} htmlFor="am-del"><Input id="am-del" dir="auto" value={terms.delivery_terms} onChange={(e) => setTerms({ ...terms, delivery_terms: e.target.value })} /></Field>
        </div>
        <ul className="flex flex-col gap-1.5">{so.items.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="min-w-48 flex-1" dir="auto">{i.description}</span>
            <Input dir="ltr" className="w-24" aria-label={`${t("execution.order.quantity")} ${i.description}`} value={items[i.id].quantity}
              onChange={(e) => setItems({ ...items, [i.id]: { ...items[i.id], quantity: e.target.value } })} />
            <Input dir="ltr" className="w-36" aria-label={`${t("execution.order.unitPrice")} ${i.description}`} value={items[i.id].unit_price}
              onChange={(e) => setItems({ ...items, [i.id]: { ...items[i.id], unit_price: e.target.value } })} /></li>))}</ul>
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

function ConfirmDialog({ so, onClose, run }: { so: SalesOrderRow; onClose: () => void; run: (path: string, body?: Body) => Promise<unknown> }) {
  const { t } = useTranslation();
  const [doc, setDoc] = useState<string | null>(so.signed_document_id);
  const [without, setWithout] = useState(false);
  const [reason, setReason] = useState("بدون سند امضاشده — ");
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open title={t("execution.order.confirm")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="confirm-save" disabled={!doc && !(without && reason.trim())}
        onClick={() => run(`/api/sales-orders/${so.id}/confirm`, doc ? { signed_document_id: doc } : { no_document_reason: reason.trim() }).then(onClose, setError)}>{t("execution.order.confirm")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="confirm-dialog">
        <Field label={t("execution.order.signedDocument")} htmlFor="so-signed"><FilePick id="so-signed" value={doc} onChange={setDoc} /></Field>
        {!doc && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={without} onChange={(e) => setWithout(e.target.checked)} /> {t("execution.order.withoutDocument")}</label>}
        {!doc && without && <Field label={t("execution.order.withoutReason")} htmlFor="so-reason"><Input id="so-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

function OrderHead({ so, caseId }: { so: SalesOrderRow; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const draft = so.status === "draft";
  const [form, setForm] = useState({ customer_ref: so.customer_ref ?? "", delivery_place: so.delivery_place ?? "", warranty_months: so.warranty_months ? String(so.warranty_months) : "",
    payment_terms: so.payment_terms ?? "", delivery_terms: so.delivery_terms ?? "", notes: so.notes ?? "" });
  const patch = (body: Body) => m.mutate({ path: `/api/sales-orders/${so.id}`, body, method: "PATCH" });
  const blur = (key: keyof typeof form) => () => {
    const old = String((so as unknown as Record<string, unknown>)[key] ?? "");
    if (form[key] !== old) patch({ [key]: key === "warranty_months" ? (form[key] ? Number(form[key]) : null) : form[key] || null });
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="so-head">
      <Field label={t("execution.order.customerRef")} htmlFor={`so-ref-${so.id}`}><Input id={`so-ref-${so.id}`} dir="ltr" value={form.customer_ref} onChange={(e) => setForm({ ...form, customer_ref: e.target.value })} onBlur={blur("customer_ref")} /></Field>
      <Field label={t("execution.order.contractDate")} htmlFor={`so-cd-${so.id}`}><DateInput id={`so-cd-${so.id}`} value={dateOrNull(so.contract_date)} onChange={(d) => patch({ contract_date: d ? toDateString(d) : null })} /></Field>
      <Field label={t("execution.order.deliveryDue")} htmlFor={`so-due-${so.id}`}>{draft
        ? <DateInput id={`so-due-${so.id}`} value={dateOrNull(so.delivery_due_on)} onChange={(d) => patch({ delivery_due_on: d ? toDateString(d) : null })} />
        : <span id={`so-due-${so.id}`} className="text-sm tabular-nums">{so.delivery_due_on ? f.day(so.delivery_due_on) : "—"}</span>}</Field>
      <Field label={t("execution.order.deliveryPlace")} htmlFor={`so-place-${so.id}`}><Input id={`so-place-${so.id}`} dir="auto" value={form.delivery_place} onChange={(e) => setForm({ ...form, delivery_place: e.target.value })} onBlur={blur("delivery_place")} /></Field>
      <Field label={t("execution.order.warranty")} htmlFor={`so-war-${so.id}`}><Input id={`so-war-${so.id}`} dir="ltr" inputMode="numeric" value={form.warranty_months} onChange={(e) => setForm({ ...form, warranty_months: e.target.value.replace(/\D/g, "") })} onBlur={blur("warranty_months")} /></Field>
      <Field label={t("execution.order.paymentTerms")} htmlFor={`so-pay-${so.id}`}><Input id={`so-pay-${so.id}`} dir="auto" disabled={!draft} value={form.payment_terms} onChange={(e) => setForm({ ...form, payment_terms: e.target.value })} onBlur={blur("payment_terms")} /></Field>
      <Field label={t("execution.order.deliveryTerms")} htmlFor={`so-dt-${so.id}`}><Input id={`so-dt-${so.id}`} dir="auto" disabled={!draft} value={form.delivery_terms} onChange={(e) => setForm({ ...form, delivery_terms: e.target.value })} onBlur={blur("delivery_terms")} /></Field>
      <Field label={t("execution.order.signedDocument")} htmlFor={`so-doc-${so.id}`}><FilePick id={`so-doc-${so.id}`} value={so.signed_document_id} onChange={(d) => patch({ signed_document_id: d })} /></Field>
      <Field label={t("parties.notes")} htmlFor={`so-notes-${so.id}`}><Textarea id={`so-notes-${so.id}`} dir="auto" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} onBlur={blur("notes")} /></Field>
      <div className="sm:col-span-2 xl:col-span-3"><ErrorNote error={m.error} /></div>
    </div>
  );
}

function OrderCard({ so, caseId }: { so: SalesOrderRow; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const run = (path: string, body?: Body, method: "POST" | "PATCH" | "DELETE" = "POST") => m.mutateAsync({ path, body, method });
  const [dialog, setDialog] = useState<"confirm" | "amend" | "cancel" | null>(null);
  const [lang, setLang] = useState<"fa" | "en">(so.customer && so.customer.name_fa ? "fa" : "en");
  const draft = so.status === "draft";
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{t("execution.order.title")} <Bdi ltr className="font-mono">{so.number}</Bdi>
      <Badge tone={SO_TONE[so.status]}>{t(`execution.order.statuses.${so.status}`)}</Badge>
      <span className="text-sm font-normal"><PartyLink party={so.customer} /></span>
      <span className="text-xs font-normal text-muted">{t("execution.order.itemsDelivered", { done: f.num(so.progress.items_delivered), total: f.num(so.progress.items_total) })}</span></span>}
      actions={<span className="flex flex-wrap gap-1.5">
        {draft && <Button variant="primary" onClick={() => setDialog("confirm")} data-testid="so-confirm">{t("execution.order.confirm")}</Button>}
        {["confirmed", "in_progress"].includes(so.status) && <Button onClick={() => setDialog("amend")} data-testid="so-amend">{t("execution.order.amend")}</Button>}
        {["draft", "confirmed", "in_progress"].includes(so.status) && <Button variant="ghost" onClick={() => setDialog("cancel")}>{t("execution.order.cancel")}</Button>}
        {draft && <Button variant="ghost" onClick={() => run(`/api/sales-orders/${so.id}`, undefined, "DELETE")}>{t("common.remove")}</Button>}
      </span>}>
      <div className="flex flex-col gap-4" data-testid="sales-order" data-so={so.id}>
        {so.no_document_reason && <p className="rounded-md bg-warning-soft px-3 py-2 text-sm text-warning">{t("execution.order.confirmedWithout")}: <span dir="auto">{so.no_document_reason}</span></p>}
        <OrderHead key={so.updated_at ?? so.status} so={so} caseId={caseId} />
        <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="so-items">
          <thead><tr className="border-b border-line text-xs text-muted">{["description", "quantity", "unitPrice", "total", "delivered"].map((h) => <th key={h} className="p-1.5 text-start whitespace-nowrap">{t(`execution.order.${h}`)}</th>)}</tr></thead>
          <tbody>{so.items.map((i) => {
            const p = itemProgress(i.quantity, i.delivered);
            return (
              <tr key={i.id} className="border-b border-line">
                <td className="p-1.5" dir="auto">{i.description}</td>
                <td className="p-1.5 tabular-nums">{draft ? <Input dir="ltr" className="w-24" aria-label={`${t("execution.order.quantity")} ${i.description}`} defaultValue={Number(i.quantity)}
                  onBlur={(e) => Number(e.target.value) !== Number(i.quantity) && run(`/api/sales-order-items/${i.id}`, { quantity: e.target.value }, "PATCH")} /> : <>{f.num(i.quantity)} {i.unit ?? ""}</>}</td>
                <td className="p-1.5">{draft ? <Input dir="ltr" className="w-32" aria-label={`${t("execution.order.unitPrice")} ${i.description}`} defaultValue={Number(i.unit_price)}
                  onBlur={(e) => Number(e.target.value) !== Number(i.unit_price) && run(`/api/sales-order-items/${i.id}`, { unit_price: e.target.value }, "PATCH")} /> : <Money amount={i.unit_price} currency={so.currency} />}</td>
                <td className="p-1.5"><Money amount={i.total} currency={so.currency} /></td>
                <td className="p-1.5 text-xs whitespace-nowrap"><span className={p.complete ? "text-success" : ""}>{t("execution.delivery.itemProgress", { done: f.num(p.done), total: f.num(p.total) })}</span></td>
              </tr>);
          })}</tbody></table></div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
          <dt className="text-muted">{t("execution.order.subtotal")}</dt><dd><Money amount={so.subtotal} currency={so.currency} /></dd>
          {Number(so.vat_amount) > 0 && <><dt className="text-muted">{t("execution.order.vat")}</dt><dd><Money amount={so.vat_amount} currency={so.currency} /></dd></>}
          <dt className="font-medium">{t("execution.order.total")}</dt><dd className="font-semibold"><Money amount={so.total} currency={so.currency} /></dd>
        </dl>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">{t("execution.order.acknowledgement")}</span>
          <Select aria-label={t("execution.order.language")} className="w-auto" value={lang} onChange={(e) => setLang(e.target.value as "fa" | "en")}><option value="fa">فارسی</option><option value="en">English</option></Select>
          <OutputButtons base={`/api/sales-orders/${so.id}`} outputs={so.outputs} language={lang} />
        </div>
        {so.changes.length > 0 && <details className="text-xs" open><summary className="cursor-pointer text-muted">{t("execution.order.amendments", { n: f.num(so.changes.length) })}</summary>
          <ul className="mt-1 flex flex-col gap-0.5" data-testid="so-changes">{so.changes.map((c) => (
            <li key={c.id}><span className="tabular-nums">{f.date(c.created_at)}</span> · {t(`execution.fields.${c.field}`, { defaultValue: c.field })}: <bdi dir="ltr">{c.old_value ?? "—"}</bdi> → <bdi dir="ltr">{c.new_value ?? "—"}</bdi> · <span dir="auto">{c.reason}</span></li>))}</ul></details>}
        <ErrorNote error={m.error} />
      </div>
      {dialog === "confirm" && <ConfirmDialog so={so} onClose={() => setDialog(null)} run={run} />}
      {dialog === "amend" && <AmendDialog so={so} onClose={() => setDialog(null)} run={run} />}
      {dialog === "cancel" && <ReasonDialog title={t("execution.order.cancel")} label={t("execution.reason")} onClose={() => setDialog(null)}
        onSave={(reason) => run(`/api/sales-orders/${so.id}/cancel`, { reason }).then(() => setDialog(null))} error={m.error} />}
    </Card>
  );
}

export function OrderTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const ex = useExecution(caseData.id);
  if (ex.isLoading) return <Loading />;
  if (ex.error || !ex.data) return <ErrorNote error={ex.error} />;
  const d = ex.data;
  const orders = d.sales_orders.filter((o) => o.status !== "cancelled");
  return (
    <div className="flex flex-col gap-4" data-testid="order-tab">
      <Candidates data={d} caseId={caseData.id} />
      {orders.length === 0 && d.candidates.length === 0 && <EmptyState>{t("execution.order.none")}</EmptyState>}
      {orders.map((so) => (
        <div key={so.id} className="flex flex-col gap-4">
          <OrderCard so={so} caseId={caseData.id} />
          <div className="grid gap-4 xl:grid-cols-2">
            <MilestonesCard title={t("execution.milestones.in")} rows={so.milestones} owner={{ sales_order_id: so.id }} currency={so.currency} caseId={caseData.id} testId="milestones-in" />
            <CashCard cash={d.cash} />
          </div>
        </div>
      ))}
      {d.sales_orders.filter((o) => o.status === "cancelled").map((so) => (
        <p key={so.id} className="text-xs text-muted"><Bdi ltr>{so.number}</Bdi> · {t("execution.order.statuses.cancelled")} · <span dir="auto">{so.cancel_reason}</span></p>))}
    </div>
  );
}
