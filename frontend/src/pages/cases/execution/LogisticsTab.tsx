/** Case tab «لجستیک» (v0.7.0): the process checklist(s) with references, dates, documents and reminders; shipments with
 * their events and documents and the delay warnings; inspections. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../../components/Bdi";
import { DateInput } from "../../../components/DateInput";
import { TimeLeftBadge } from "../../../components/TimeLeft";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Loading, Modal, Select } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { parseContainers, STEP_TONE, stepGroups, stepState } from "../../../lib/execution";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseDetail, CaseExecution, InspectionRow, ProcessRow, ProcessStepRow, ShipmentRow } from "../../../lib/types";
import { OpenClaimButton } from "./PurchaseTab";
import { dateOrNull, FilePick, useExecution, useRun, type Body, type Method } from "./shared";

type Run = (path: string, body?: Body, method?: Method) => Promise<unknown>;
const todayIso = () => toDateString(new Date());

export function ProcessStepper({ process }: { process: ProcessRow }) {
  const { t } = useTranslation();
  const f = useFormat();
  const today = todayIso();
  return (
    <ol className="flex flex-wrap gap-1" data-testid="process-stepper">
      {stepGroups(process.steps).map((g) => (
        <li key={g.group} className="flex flex-wrap items-center gap-1 rounded-md border border-line px-1.5 py-1" data-group={g.group}>
          <span className="text-xs text-muted">{t(`execution.process.groups.${g.group}`, { defaultValue: g.group || "—" })} {f.num(g.done)}/{f.num(g.steps.length)}</span>
          {g.steps.map((s) => {
            const state = stepState(s, today);
            const tone = STEP_TONE[state];
            return <span key={s.id} data-state={state} title={f.lang === "fa" ? s.label_fa : s.label_en}
              className={`inline-block size-2.5 rounded-full ${tone === "success" ? "bg-success" : tone === "danger" ? "bg-danger" : tone === "accent" ? "bg-accent" : state === "na" ? "bg-line" : "border border-line-strong"}`} />;
          })}
        </li>
      ))}
    </ol>
  );
}

function StepRow({ step, run }: { step: ProcessStepRow; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [ref, setRef] = useState(step.reference ?? "");
  const [reason, setReason] = useState(step.no_document_reason ?? "");
  const [needReason, setNeedReason] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const state = stepState(step, todayIso());
  const patch = (body: Body) => run(`/api/process-steps/${step.id}`, body, "PATCH").then(() => setError(null), (err) => {
    if (err instanceof ApiError && err.code === "document_required") setNeedReason(true);
    setError(err);
  });
  const label = f.lang === "fa" ? step.label_fa : step.label_en;
  return (
    <li className="flex flex-col gap-1.5 px-4 py-2 text-sm" data-testid="process-step" data-code={step.code}>
      <span className="flex flex-wrap items-center gap-2">
        <Badge tone={STEP_TONE[state]}>{t(`execution.process.states.${state}`)}</Badge>
        <span className="min-w-48 flex-1 font-medium" dir="auto">{label}{step.requires_document && <span className="ms-1 text-xs text-muted">📎</span>}</span>
        <Select aria-label={`${t("execution.process.status")} ${label}`} className="w-auto" value={step.status} onChange={(e) => void patch({ status: e.target.value })}>
          {(["pending", "in_progress", "done", "not_applicable"] as const).map((s) => <option key={s} value={s}>{t(`execution.process.statuses.${s}`)}</option>)}</Select>
        {step.due_on && step.status !== "done" && step.status !== "not_applicable" && <TimeLeftBadge at={`${step.due_on}T23:59:00`} />}
      </span>
      <span className="flex flex-wrap items-center gap-2">
        {step.reference_label && <Field label={step.reference_label} htmlFor={`ref-${step.id}`}>
          <Input id={`ref-${step.id}`} dir="ltr" className="w-48" value={ref} onChange={(e) => setRef(e.target.value)} onBlur={() => ref !== (step.reference ?? "") && void patch({ reference: ref || null })} /></Field>}
        <Field label={t("execution.process.dueOn")} htmlFor={`due-${step.id}`}><DateInput id={`due-${step.id}`} value={dateOrNull(step.due_on)} onChange={(d) => void patch({ due_on: d ? toDateString(d) : null })} /></Field>
        <Field label={t("execution.process.document")} htmlFor={`doc-${step.id}`}><FilePick id={`doc-${step.id}`} value={step.document_id} onChange={(d) => void patch({ document_id: d })} /></Field>
        {(needReason || step.no_document_reason) && <Field label={t("execution.process.noDocumentReason")} htmlFor={`nodoc-${step.id}`}>
          <Input id={`nodoc-${step.id}`} dir="auto" className="w-56" value={reason} onChange={(e) => setReason(e.target.value)}
            onBlur={() => reason.trim() && void patch({ no_document_reason: reason.trim(), status: "done" })} /></Field>}
      </span>
      {step.reminders.length > 0 && <span className="text-xs text-muted">{t("execution.process.reminders", { list: step.reminders.map((r) => f.day(r.due_on)).join("، ") })}</span>}
      {step.done_on && <span className="text-xs text-muted">{t("execution.process.doneOn")}: {f.day(step.done_on)}</span>}
      {error !== null && !(error instanceof ApiError && error.code === "document_required") && <ErrorNote error={error} />}
      {needReason && step.status !== "done" && <span className="text-xs text-warning" role="alert">{t("execution.process.needDocument")}</span>}
    </li>
  );
}

function ProcessCard({ process, caseId }: { process: ProcessRow; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const run: Run = (path, body, method = "POST") => m.mutateAsync({ path, body, method });
  const groups = stepGroups(process.steps);
  return (
    <Card padded={false} title={<span className="flex flex-wrap items-center gap-2">{t("execution.process.title")} · {t(`execution.dealTypes.${process.deal_type}`)}
      <Badge tone="accent">{t("execution.process.progress", { done: f.num(process.progress.done), total: f.num(process.progress.total) })}</Badge>
      {process.progress.next && <span className="text-xs font-normal text-muted">{t("execution.process.next")}: <span dir="auto">{f.lang === "fa" ? process.progress.next.label_fa : process.progress.next.label_en}</span>
        {process.progress.next.due_on && <> · {f.day(process.progress.next.due_on)}</>}</span>}</span>}>
      <div className="border-b border-line px-4 py-2"><ProcessStepper process={process} /></div>
      {groups.map((g) => (
        <section key={g.group}>
          <h3 className="bg-surface-2 px-4 py-1 text-xs font-medium text-muted">{t(`execution.process.groups.${g.group}`, { defaultValue: g.group || "—" })}</h3>
          <ul className="divide-y divide-line">{g.steps.map((s) => <StepRow key={`${s.id}-${s.updated_at ?? ""}`} step={s} run={run} />)}</ul>
        </section>
      ))}
      <div className="px-4 pb-2"><ErrorNote error={m.error} /></div>
    </Card>
  );
}

function ShipmentDialog({ data, onClose, run }: { data: CaseExecution; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const pos = data.purchase_orders.filter((p) => !["draft", "approved", "cancelled", "superseded"].includes(p.status));
  const [form, setForm] = useState({ purchase_order_id: pos[0]?.id ?? "", mode: "sea", transport_doc_kind: "bl", transport_doc_no: "", containers: "", vessel_or_flight: "",
    origin: "", destination: "", etd: null as Date | null, eta: null as Date | null });
  const po = pos.find((p) => p.id === form.purchase_order_id);
  const [qty, setQty] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const items = po ? po.items.map((i) => ({ purchase_order_item_id: i.id, quantity: qty[i.id] ?? "" })).filter((x) => Number(x.quantity) > 0) : [];
  return (
    <Modal open wide title={t("execution.shipments.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="shipment-save"
        onClick={() => run("/api/shipments", { ...(form.purchase_order_id ? { purchase_order_id: form.purchase_order_id } : { case_id: data.sales_orders[0]?.case_id, sales_order_id: data.sales_orders[0]?.id }),
          mode: form.mode, transport_doc_kind: form.transport_doc_kind || null, transport_doc_no: form.transport_doc_no || null, containers: parseContainers(form.containers),
          vessel_or_flight: form.vessel_or_flight || null, origin: form.origin || null, destination: form.destination || null,
          etd: form.etd ? toDateString(form.etd) : null, eta: form.eta ? toDateString(form.eta) : null, items }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="shipment-dialog">
        <Field label={t("execution.shipments.po")} htmlFor="sh-po"><Select id="sh-po" value={form.purchase_order_id} onChange={(e) => setForm({ ...form, purchase_order_id: e.target.value })}>
          <option value="">{t("execution.shipments.outbound")}</option>{pos.map((p) => <option key={p.id} value={p.id}>{p.number}</option>)}</Select></Field>
        <Field label={t("execution.shipments.mode")} htmlFor="sh-mode"><Select id="sh-mode" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
          {["sea", "air", "road", "rail", "courier", "domestic_truck", "other"].map((m) => <option key={m} value={m}>{t(`execution.shipments.modes.${m}`)}</option>)}</Select></Field>
        <Field label={t("execution.shipments.docKind")} htmlFor="sh-dk"><Select id="sh-dk" value={form.transport_doc_kind} onChange={(e) => setForm({ ...form, transport_doc_kind: e.target.value })}>
          {["bl", "awb", "cmr", "waybill", "other"].map((k) => <option key={k} value={k}>{t(`execution.shipments.docKinds.${k}`)}</option>)}</Select></Field>
        <Field label={t("execution.shipments.docNo")} htmlFor="sh-dn"><Input id="sh-dn" dir="ltr" value={form.transport_doc_no} onChange={(e) => setForm({ ...form, transport_doc_no: e.target.value })} /></Field>
        <Field label={t("execution.shipments.containers")} htmlFor="sh-cont" hint={t("execution.shipments.containersHint")}><Input id="sh-cont" dir="ltr" value={form.containers} onChange={(e) => setForm({ ...form, containers: e.target.value })} /></Field>
        <Field label={t("execution.shipments.vessel")} htmlFor="sh-vessel"><Input id="sh-vessel" dir="auto" value={form.vessel_or_flight} onChange={(e) => setForm({ ...form, vessel_or_flight: e.target.value })} /></Field>
        <Field label={t("execution.shipments.origin")} htmlFor="sh-origin"><Input id="sh-origin" dir="auto" value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} /></Field>
        <Field label={t("execution.shipments.destination")} htmlFor="sh-dest"><Input id="sh-dest" dir="auto" value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })} /></Field>
        <Field label="ETD" htmlFor="sh-etd"><DateInput id="sh-etd" value={form.etd} onChange={(d) => setForm({ ...form, etd: d })} /></Field>
        <Field label="ETA" htmlFor="sh-eta"><DateInput id="sh-eta" value={form.eta} onChange={(d) => setForm({ ...form, eta: d })} /></Field>
        {po && <ul className="flex flex-col gap-1.5 sm:col-span-2 xl:col-span-3">{po.items.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="min-w-48 flex-1" dir="auto">{i.description}</span>
            <Input dir="ltr" className="w-24" aria-label={`${t("execution.shipments.quantity")} ${i.description}`} value={qty[i.id] ?? ""} onChange={(e) => setQty({ ...qty, [i.id]: e.target.value })} /></li>))}</ul>}
        <div className="sm:col-span-2 xl:col-span-3"><ErrorNote error={error} /></div>
      </div>
    </Modal>
  );
}

const DOC_KINDS = ["commercial_invoice", "packing_list", "bl", "awb", "cmr", "certificate_of_origin", "inspection_certificate", "insurance_policy", "customs_declaration", "other"] as const;

function ShipmentCard({ s, caseId, warnings }: { s: ShipmentRow; caseId: string; warnings: CaseExecution["warnings"] }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const run: Run = (path, body, method = "POST") => m.mutateAsync({ path, body, method });
  const patch = (body: Body) => void run(`/api/shipments/${s.id}`, body, "PATCH");
  const [event, setEvent] = useState({ kind: "loaded", note: "" });
  const [doc, setDoc] = useState({ kind: "commercial_invoice", number: "", document_id: null as string | null });
  const mine = warnings.filter((w) => w.shipment_id === s.id);
  return (
    <Card padded={false} title={<span className="flex flex-wrap items-center gap-2">{t("execution.shipments.title")} · {t(`execution.shipments.modes.${s.mode}`)}
      {s.transport_doc_no && <Bdi ltr className="font-mono text-sm">{(s.transport_doc_kind ?? "").toUpperCase()} {s.transport_doc_no}</Bdi>}
      <Badge tone={mine.length ? "danger" : "neutral"}>{t(`execution.shipments.statuses.${s.status}`)}</Badge>
      {s.containers.length > 0 && <span className="text-xs font-normal text-muted" dir="ltr">{s.containers.join(" · ")}</span>}</span>}>
      <div className="flex flex-col gap-3 px-4 py-3" data-testid="shipment" data-shipment={s.id}>
        {mine.map((w) => <p key={w.kind} className="rounded-md bg-danger-soft px-3 py-1.5 text-sm text-danger" role="alert" data-testid="delay-warning">
          {t(`execution.warnings.${w.kind}`, { days: f.num(w.days) })}</p>)}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <Field label={t("execution.shipments.status")} htmlFor={`sh-st-${s.id}`}><Select id={`sh-st-${s.id}`} value={s.status} onChange={(e) => patch({ status: e.target.value })}>
            {["planned", "booked", "in_transit", "arrived", "at_customs", "cleared", "delivered", "cancelled"].map((x) => <option key={x} value={x}>{t(`execution.shipments.statuses.${x}`)}</option>)}</Select></Field>
          {(["etd", "eta", "atd", "ata"] as const).map((k) => (
            <Field key={k} label={k.toUpperCase()} htmlFor={`sh-${k}-${s.id}`}><DateInput id={`sh-${k}-${s.id}`} value={dateOrNull(s[k])} onChange={(d) => patch({ [k]: d ? toDateString(d) : null })} /></Field>))}
        </div>
        {s.first_eta && s.eta && s.first_eta !== s.eta && <p className="text-xs text-muted">{t("execution.shipments.firstEta")}: {f.day(s.first_eta)}</p>}
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-2">
          <Field label={t("execution.shipments.eventKind")} htmlFor={`ev-${s.id}`}><Select id={`ev-${s.id}`} value={event.kind} onChange={(e) => setEvent({ ...event, kind: e.target.value })}>
            {["booked", "loaded", "departed", "transshipment", "arrived", "customs_entry", "released", "delivered", "delay", "other"].map((k) => <option key={k} value={k}>{t(`execution.shipments.events.${k}`)}</option>)}</Select></Field>
          <Field label={t("execution.shipments.eventNote")} htmlFor={`evn-${s.id}`}><Input id={`evn-${s.id}`} dir="auto" value={event.note} onChange={(e) => setEvent({ ...event, note: e.target.value })} /></Field>
          <Button onClick={() => void run(`/api/shipments/${s.id}/events`, { kind: event.kind, note: event.note || null }).then(() => setEvent({ ...event, note: "" }))} data-testid="add-event">{t("common.add")}</Button>
        </div>
        {s.events.length > 0 && <ul className="text-xs" data-testid="shipment-events">{s.events.map((e) => (
          <li key={e.id}><span className="tabular-nums text-muted">{f.date(e.at)}</span> · {t(`execution.shipments.events.${e.kind}`, { defaultValue: e.kind })}{e.note && <> · <bdi dir="auto">{e.note}</bdi></>}</li>))}</ul>}
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-2">
          <Field label={t("execution.shipments.docKindFull")} htmlFor={`sd-k-${s.id}`}><Select id={`sd-k-${s.id}`} value={doc.kind} onChange={(e) => setDoc({ ...doc, kind: e.target.value })}>
            {DOC_KINDS.map((k) => <option key={k} value={k}>{t(`execution.shipments.documents.${k}`)}</option>)}</Select></Field>
          <Field label={t("execution.shipments.docNumber")} htmlFor={`sd-n-${s.id}`}><Input id={`sd-n-${s.id}`} dir="ltr" className="w-40" value={doc.number} onChange={(e) => setDoc({ ...doc, number: e.target.value })} /></Field>
          <Field label={t("execution.shipments.file")} htmlFor={`sd-f-${s.id}`}><FilePick id={`sd-f-${s.id}`} value={doc.document_id} onChange={(d) => setDoc({ ...doc, document_id: d })} /></Field>
          <Button disabled={!doc.document_id} data-testid="add-shipment-doc"
            onClick={() => void run(`/api/shipments/${s.id}/documents`, { kind: doc.kind, document_id: doc.document_id, number: doc.number || null }).then(() => setDoc({ kind: doc.kind, number: "", document_id: null }))}>{t("common.add")}</Button>
        </div>
        {s.documents.length > 0 && <ul className="flex flex-wrap gap-2 text-xs" data-testid="shipment-documents">{s.documents.map((d) => (
          <li key={d.id}><Badge>{t(`execution.shipments.documents.${d.kind}`)}</Badge>{d.number && <bdi dir="ltr" className="ms-1">{d.number}</bdi>}</li>))}</ul>}
        <ErrorNote error={m.error} />
      </div>
    </Card>
  );
}

function InspectionCard({ data, caseId }: { data: CaseExecution; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const [form, setForm] = useState({ target: data.shipments[0] ? `s:${data.shipments[0].id}` : data.purchase_orders[0] ? `p:${data.purchase_orders[0].id}` : "", kind: "pre_shipment", result: "pending" });
  const create = () => {
    const [kind, id] = form.target.split(":");
    void m.mutateAsync({ path: "/api/inspections", body: { ...(kind === "s" ? { shipment_id: id } : { purchase_order_id: id }), kind: form.kind, result: form.result,
      ...(form.result !== "pending" ? { done_on: todayIso() } : {}) } });
  };
  return (
    <Card padded={false} title={t("execution.inspections.title")}>
      <div className="flex flex-wrap items-end gap-2 border-b border-line px-4 py-2">
        <Field label={t("execution.inspections.target")} htmlFor="in-target"><Select id="in-target" value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}>
          {data.shipments.map((s) => <option key={s.id} value={`s:${s.id}`}>{t("execution.shipments.title")} {s.transport_doc_no ?? ""}</option>)}
          {data.purchase_orders.filter((p) => p.status !== "superseded").map((p) => <option key={p.id} value={`p:${p.id}`}>{p.number}</option>)}</Select></Field>
        <Field label={t("execution.inspections.kind")} htmlFor="in-kind"><Select id="in-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {["pre_shipment", "on_arrival", "third_party", "internal"].map((k) => <option key={k} value={k}>{t(`execution.inspections.kinds.${k}`)}</option>)}</Select></Field>
        <Field label={t("execution.inspections.result")} htmlFor="in-result"><Select id="in-result" value={form.result} onChange={(e) => setForm({ ...form, result: e.target.value })}>
          {["pending", "pass", "conditional", "fail"].map((k) => <option key={k} value={k}>{t(`execution.inspections.results.${k}`)}</option>)}</Select></Field>
        <Button disabled={!form.target} onClick={create} data-testid="add-inspection">{t("common.add")}</Button>
      </div>
      {data.inspections.length === 0 ? <EmptyState>{t("execution.inspections.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid="inspections">{data.inspections.map((i: InspectionRow) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
            <span>{t(`execution.inspections.kinds.${i.kind}`)}</span>
            <Select aria-label={t("execution.inspections.result")} className="w-auto" value={i.result}
              onChange={(e) => m.mutate({ path: `/api/inspections/${i.id}`, body: { result: e.target.value }, method: "PATCH" })}>
              {["pending", "pass", "conditional", "fail"].map((k) => <option key={k} value={k}>{t(`execution.inspections.results.${k}`)}</option>)}</Select>
            {i.done_on && <span className="text-xs tabular-nums text-muted">{f.day(i.done_on)}</span>}
            {i.claim_suggestion && <OpenClaimButton suggestion={i.claim_suggestion} caseId={caseId} />}
          </li>))}</ul>
      )}
      <div className="px-4 pb-2"><ErrorNote error={m.error} /></div>
    </Card>
  );
}

export function LogisticsTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const ex = useExecution(caseData.id);
  const m = useRun(caseData.id);
  const [adding, setAdding] = useState(false);
  const [dealType, setDealType] = useState("import");
  if (ex.isLoading) return <Loading />;
  if (ex.error || !ex.data) return <ErrorNote error={ex.error} />;
  const d = ex.data;
  const run: Run = (path, body, method = "POST") => m.mutateAsync({ path, body, method });
  const poWarnings = d.warnings.filter((w) => w.kind === "ready_passed");
  return (
    <div className="flex flex-col gap-4" data-testid="logistics-tab">
      {poWarnings.map((w) => <p key={w.purchase_order_id} className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert" data-testid="delay-warning">
        {t("execution.warnings.ready_passed", { days: w.days, number: w.number })}</p>)}
      {d.processes.map((p) => <ProcessCard key={p.id} process={p} caseId={caseData.id} />)}
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("execution.process.addByHand")} htmlFor="pr-type"><Select id="pr-type" value={dealType} onChange={(e) => setDealType(e.target.value)}>
          {["import", "export", "domestic"].map((x) => <option key={x} value={x}>{t(`execution.dealTypes.${x}`)}</option>)}</Select></Field>
        <Button onClick={() => void run(`/api/cases/${caseData.id}/processes`, { deal_type: dealType })} data-testid="add-process">{t("common.add")}</Button>
        <Button icon="plus" className="ms-auto" onClick={() => setAdding(true)} data-testid="add-shipment">{t("execution.shipments.add")}</Button>
      </div>
      <ErrorNote error={m.error} />
      {d.shipments.length === 0 ? <EmptyState>{t("execution.shipments.none")}</EmptyState>
        : d.shipments.map((s) => <ShipmentCard key={s.id} s={s} caseId={caseData.id} warnings={d.warnings} />)}
      <InspectionCard data={d} caseId={caseData.id} />
      {adding && <ShipmentDialog data={d} onClose={() => setAdding(false)} run={run} />}
    </div>
  );
}
