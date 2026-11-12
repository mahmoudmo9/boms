/** Shared parts of the execution tabs (v0.7.0): the case's execution data, a mutation runner, a file picker into the
 * document store, the outputs buttons, payment milestones with their payments, and a reason dialog. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Button, Card, DateInput, EmptyState, ErrorNote, Field, FileDrop, Input, Modal, Select } from "../../../design/components";
import { api, ApiError } from "../../../lib/api";
import { MILESTONE_TONE } from "../../../lib/execution";
import { fromDateString, toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseExecution, DocumentDetail, MilestoneRow, OutputLink, PartyRef } from "../../../lib/types";
import { Money } from "../../sourcing/shared";

export type Body = Record<string, unknown>;
export type Method = "POST" | "PATCH" | "DELETE" | "PUT";

export function useExecution(caseId: string) {
  return useQuery({ queryKey: ["execution", caseId], queryFn: () => api<CaseExecution>(`/api/cases/${caseId}/execution`) });
}

/** POST/PATCH/DELETE then refresh the case's execution data (and the case, whose items' statuses may change). */
export function useRun(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, body, method = "POST" }: { path: string; body?: Body; method?: Method }) => api<unknown>(path, { method, body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["execution", caseId] });
      void queryClient.invalidateQueries({ queryKey: ["case", caseId] });
    },
  });
}

export function partyName(p: PartyRef | null | undefined, lang: string): string {
  if (!p) return "—";
  return (lang === "fa" ? p.name_fa || p.name_en : p.name_en || p.name_fa) ?? "—";
}

export function PartyLink({ party }: { party: PartyRef | null | undefined }) {
  const f = useFormat();
  if (!party) return <span>—</span>;
  return <Link to={`/parties/${party.id}`} className="text-accent hover:underline" dir="auto">{partyName(party, f.lang)}</Link>;
}

/** Choose a file: it goes into the document store (an identical file already stored is reused). */
export function FilePick({ id, value, onChange, label }: { id: string; value: string | null; onChange: (documentId: string | null) => void; label?: string }) {
  const { t } = useTranslation();
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const data = new FormData();
      data.append("file", file);
      try { return (await api<DocumentDetail>("/api/documents", { method: "POST", form: data })).id; }
      catch (err) { if (err instanceof ApiError && err.code === "duplicate_document") return String(err.details.id); throw err; }
    },
    onSuccess: (docId) => onChange(docId),
  });
  return (
    <span className="flex flex-wrap items-center gap-2">
      <FileDrop compact id={id} multiple={false} ariaLabel={label} busy={upload.isPending} onFiles={(files) => files[0] && upload.mutate(files[0])} />
      {value && <Link className="text-xs text-accent hover:underline" to={`/documents/${value}`} data-testid={`${id}-set`}>{t("execution.fileSet")}</Link>}
      <ErrorNote error={upload.error} />
    </span>
  );
}

/** Print view, PDF and Word of an order document (generated into the store, then downloaded). */
export function OutputButtons({ base, outputs, language }: { base: string; outputs: OutputLink[]; language?: "fa" | "en" }) {
  const { t } = useTranslation();
  const make = useMutation({
    mutationFn: (format: "pdf" | "docx") => api<{ document_id: string }>(`${base}/outputs`, { method: "POST", body: { format, ...(language ? { language } : {}) } }),
    onSuccess: (out) => window.location.assign(`/api/documents/${out.document_id}/download`),
  });
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <a className="inline-flex h-8 items-center rounded-md border border-line-strong px-3 text-sm hover:bg-surface-2"
        href={`${base}/print${language ? `?language=${language}` : ""}`} target="_blank" rel="noreferrer">{t("quotes.printView")}</a>
      <Button icon="download" busy={make.isPending && make.variables === "pdf"} onClick={() => make.mutate("pdf")}>PDF</Button>
      <Button icon="download" busy={make.isPending && make.variables === "docx"} onClick={() => make.mutate("docx")}>Word</Button>
      {outputs.length > 0 && <span className="text-xs text-muted">{t("execution.outputs", { n: outputs.length })}</span>}
      <ErrorNote error={make.error} />
    </span>
  );
}

export function ReasonDialog({ title, label, onClose, onSave, busy, error }: {
  title: string; label: string; onClose: () => void; onSave: (reason: string) => void; busy?: boolean; error?: unknown;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  return (
    <Modal open title={title} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={busy} disabled={!reason.trim()}
        data-testid="reason-save" onClick={() => onSave(reason.trim())}>{t("common.save")}</Button></>}>
      <Field label={label} htmlFor="reason-text"><Input id="reason-text" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <ErrorNote error={error} />
    </Modal>
  );
}

const KINDS = ["prepayment", "on_order_confirmation", "on_shipment", "on_delivery", "balance", "retention", "other"] as const;

function PaymentForm({ m, onClose, run }: { m: MilestoneRow; onClose: () => void; run: (path: string, body?: Body) => Promise<unknown> }) {
  const { t } = useTranslation();
  const left = Math.max(0, Number(m.expected_amount) - Number(m.actual_amount ?? 0));
  const [form, setForm] = useState({ amount: left ? String(left) : "", paid_on: new Date() as Date | null, method: "", reference: "", document_id: null as string | null,
    fx_rate_to_base: "", rate_source: "", bank_fee: "" });
  const foreign = m.expected_currency !== "IRR";   // v0.8.0: a foreign payment carries its real rate to rials
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open title={t("execution.milestones.record")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="payment-save" disabled={!Number(form.amount) || !form.paid_on || (foreign && !Number(form.fx_rate_to_base))}
        onClick={() => run(`/api/payment-milestones/${m.id}/payments`, { amount: form.amount, paid_on: toDateString(form.paid_on!), method: form.method || null,
          reference: form.reference || null, document_id: form.document_id, ...(foreign ? { fx_rate_to_base: form.fx_rate_to_base, rate_source: form.rate_source || null } : {}),
          ...(Number(form.bank_fee) ? { bank_fee: form.bank_fee } : {}) }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2" data-testid="payment-form">
        <Field label={`${t("execution.milestones.amount")} (${m.expected_currency})`} htmlFor="pay-amount"><Input id="pay-amount" dir="ltr" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
        <Field label={t("execution.milestones.paidOn")} htmlFor="pay-on"><DateInput id="pay-on" value={form.paid_on} onChange={(d) => setForm({ ...form, paid_on: d })} /></Field>
        <Field label={t("execution.milestones.method")} htmlFor="pay-method"><Input id="pay-method" dir="auto" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })} /></Field>
        <Field label={t("execution.milestones.reference")} htmlFor="pay-ref"><Input id="pay-ref" dir="ltr" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></Field>
        {foreign && <Field label={t("finance.fxRate", { cur: m.expected_currency })} htmlFor="pay-rate"><Input id="pay-rate" dir="ltr" inputMode="decimal" value={form.fx_rate_to_base} onChange={(e) => setForm({ ...form, fx_rate_to_base: e.target.value })} /></Field>}
        {foreign && <Field label={t("finance.rateSource")} htmlFor="pay-rate-src"><Input id="pay-rate-src" dir="auto" value={form.rate_source} onChange={(e) => setForm({ ...form, rate_source: e.target.value })} /></Field>}
        <Field label={`${t("finance.bankFee")} (${m.expected_currency})`} htmlFor="pay-fee"><Input id="pay-fee" dir="ltr" inputMode="decimal" value={form.bank_fee} onChange={(e) => setForm({ ...form, bank_fee: e.target.value })} /></Field>
        <Field label={t("execution.milestones.receipt")} htmlFor="pay-doc"><FilePick id="pay-doc" value={form.document_id} onChange={(d) => setForm({ ...form, document_id: d })} /></Field>
      </div>
      <ErrorNote error={error} />
    </Modal>
  );
}

function MilestoneForm({ owner, onClose, run, currency, preset }: {
  owner: Body; onClose: () => void; run: (path: string, body?: Body) => Promise<unknown>; currency: string; preset?: { kind: string; label: string };
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ kind: preset?.kind ?? "prepayment", label: preset?.label ?? "", mode: "percent" as "percent" | "amount", value: "", due_on: null as Date | null, due_event: "" });
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open title={t("execution.milestones.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" data-testid="milestone-save" disabled={!Number(form.value)}
        onClick={() => run("/api/payment-milestones", { ...owner, kind: form.kind, label: form.label || null,
          ...(form.mode === "percent" ? { percent: form.value } : { amount: form.value, amount_currency: currency }),
          due_on: form.due_on ? toDateString(form.due_on) : null, due_event: form.due_event || null }).then(onClose, setError)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2" data-testid="milestone-form">
        <Field label={t("execution.milestones.kind")} htmlFor="ms-kind"><Select id="ms-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {KINDS.map((k) => <option key={k} value={k}>{t(`execution.milestones.kinds.${k}`)}</option>)}</Select></Field>
        <Field label={t("execution.milestones.label")} htmlFor="ms-label"><Input id="ms-label" dir="auto" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></Field>
        <Field label={t("execution.milestones.valueMode")} htmlFor="ms-mode"><Select id="ms-mode" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as "percent" | "amount" })}>
          <option value="percent">{t("execution.milestones.percent")}</option><option value="amount">{t("execution.milestones.amount")} ({currency})</option></Select></Field>
        <Field label={form.mode === "percent" ? "%" : currency} htmlFor="ms-value"><Input id="ms-value" dir="ltr" inputMode="decimal" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} /></Field>
        <Field label={t("execution.milestones.dueOn")} htmlFor="ms-due"><DateInput id="ms-due" value={form.due_on} onChange={(d) => setForm({ ...form, due_on: d })} /></Field>
        <Field label={t("execution.milestones.dueEvent")} htmlFor="ms-event"><Input id="ms-event" dir="auto" value={form.due_event} onChange={(e) => setForm({ ...form, due_event: e.target.value })} /></Field>
      </div>
      <ErrorNote error={error} />
    </Modal>
  );
}

/** Payment milestones of one order (in from the customer or out to a supplier), with quick-add and payments. */
export function MilestonesCard({ title, rows, owner, currency, caseId, offerTerms, testId }: {
  title: string; rows: MilestoneRow[]; owner: Body; currency: string; caseId: string; offerTerms?: string | null; testId: string;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const m = useRun(caseId);
  const run = (path: string, body?: Body, method: Method = "POST") => m.mutateAsync({ path, body, method });
  const [adding, setAdding] = useState<{ kind: string; label: string } | null | "free">(null);
  const [paying, setPaying] = useState<MilestoneRow | null>(null);
  const quick = [{ kind: "prepayment", label: t("execution.milestones.quickPrepayment") }, { kind: "on_delivery", label: t("execution.milestones.quickBalance") }];
  return (
    <Card padded={false} title={title} actions={<span className="flex flex-wrap gap-1">
      {quick.map((q) => <Button key={q.kind} variant="ghost" onClick={() => setAdding(q)}>+ {q.label}</Button>)}
      <Button icon="plus" onClick={() => setAdding("free")} data-testid={`${testId}-add`}>{t("execution.milestones.add")}</Button></span>}>
      {offerTerms && <p className="border-b border-line px-4 py-2 text-xs text-muted" dir="auto">{t("execution.milestones.offerTerms")}: {offerTerms}</p>}
      {rows.length === 0 ? <EmptyState>{t("execution.milestones.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid={testId}>{rows.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm" data-milestone={r.id}>
            <span className="min-w-36 font-medium">{r.label || t(`execution.milestones.kinds.${r.kind}`)}</span>
            {r.percent && <span className="tabular-nums text-muted">{f.num(r.percent)} %</span>}
            <Money amount={r.expected_amount} currency={r.expected_currency} />
            <Badge tone={MILESTONE_TONE[r.status]}>{t(`execution.milestones.statuses.${r.status}`)}</Badge>
            {r.actual_amount && <span className="text-xs">{t("execution.milestones.paid")}: <Money amount={r.actual_amount} currency={r.actual_amount_currency} /></span>}
            {r.due_on && <span className="text-xs tabular-nums text-muted">{t("execution.milestones.dueOn")}: {f.day(r.due_on)}</span>}
            {r.due_event && <span className="text-xs text-muted" dir="auto">{r.due_event}</span>}
            <span className="ms-auto flex gap-1">
              {r.status !== "done" && r.status !== "cancelled" && <Button variant="ghost" onClick={() => setPaying(r)} data-testid="record-payment">{t("execution.milestones.record")}</Button>}
              {r.records.length === 0 && r.status !== "cancelled" && <Button variant="ghost" onClick={() => run(`/api/payment-milestones/${r.id}`, undefined, "DELETE")}>{t("common.remove")}</Button>}
            </span>
            {r.records.length > 0 && <ul className="w-full text-xs text-muted">{r.records.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2"><span className="tabular-nums">{f.day(p.paid_on)}</span><Money amount={p.amount} currency={p.amount_currency} />
                {p.reference && <bdi dir="ltr">{p.reference}</bdi>}{p.document_id && <Link className="text-accent hover:underline" to={`/documents/${p.document_id}`}>{t("execution.fileSet")}</Link>}</li>))}</ul>}
          </li>))}</ul>
      )}
      <div className="px-4 pb-2"><ErrorNote error={m.error} /></div>
      {adding && <MilestoneForm owner={owner} currency={currency} preset={adding === "free" ? undefined : adding} onClose={() => setAdding(null)} run={run} />}
      {paying && <PaymentForm m={paying} onClose={() => setPaying(null)} run={run} />}
    </Card>
  );
}

export function dateOrNull(value: string | null | undefined): Date | null {
  return value ? fromDateString(value) : null;
}
