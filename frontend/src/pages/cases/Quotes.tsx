/** Quotes tab: proforma invoices of the case (draft editor, approval, outputs, sending, outcomes, revisions). */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, Input, Loading, Modal, Select, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, ApiError } from "../../lib/api";
import { gateChecklist } from "../../lib/costing";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import { personName } from "../../lib/sourcing";
import type { CaseDetail, CaseQuotes, Outcome, OutcomeReason, Quote, QuoteItem } from "../../lib/types";
import { DueDatePicker, PartyName } from "../parties/shared";
import { ContactName, CurrencySelect, IncotermSelect, Money, StatusBadge, useInvalidateSourcing, useUnitLabel } from "../sourcing/shared";

const OUTCOMES: Outcome[] = ["accepted", "rejected", "no_reply", "negotiating"];
const SEND_CHANNELS = ["email", "whatsapp", "phone", "in_person", "letter", "other"] as const;
type Body = Record<string, unknown>;

/** Field that saves on blur (draft quotes only). */
function BlurInput({ value, onSave, disabled, multiline, ...rest }: {
  value: string | null; onSave: (v: string | null) => void; disabled?: boolean; multiline?: boolean;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => { setText(value ?? ""); }, [value]);
  const save = () => { const v = text.trim() === "" ? null : text; if (v !== (value ?? null)) onSave(v); };
  if (multiline) {
    return <Textarea id={rest.id} dir="auto" rows={6} aria-label={rest["aria-label"]} disabled={disabled} value={text}
      onChange={(e) => setText(e.target.value)} onBlur={save} className="[unicode-bidi:plaintext]" />;
  }
  return <Input {...rest} disabled={disabled} value={text} onChange={(e) => setText(e.target.value)} onBlur={save} />;
}

function MarkSentDialog({ quote, onClose, onDone }: { quote: Quote; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const fallback = quote.default_followup ?? { action: "", due_on: quote.valid_until };
  const [channel, setChannel] = useState<string>("email");
  const [action, setAction] = useState(fallback.action);
  const [due, setDue] = useState<string | null>(fallback.due_on);
  const [skip, setSkip] = useState(false);
  const [reason, setReason] = useState("");
  const [move, setMove] = useState(true);
  const send = useMutation({
    mutationFn: () => api(`/api/quotes/${quote.id}/mark-sent`, { method: "POST", body: {
      channel, move_to_quoted: move, ...(skip ? { no_followup_reason: reason.trim() } : { followup: { action, due_on: due } }) } }),
    onSuccess: () => { onDone(); onClose(); },
  });
  const ready = skip ? !!reason.trim() : !!action.trim() && !!due;
  return (
    <Modal open title={t("quotes.markSent")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!ready} busy={send.isPending} onClick={() => send.mutate()}>{t("quotes.markSent")}</Button></>}>
      <div className="flex flex-col gap-3">
        <p className="text-sm">{t("quotes.markSentHint")}</p>
        <Field label={t("sourcing.rfq.channel")} htmlFor="qs-ch">
          <Select id="qs-ch" className="w-auto min-w-36" value={channel} onChange={(e) => setChannel(e.target.value)}>
            {SEND_CHANNELS.map((c) => <option key={c} value={c}>{t(`quotes.channels.${c}`)}</option>)}
          </Select>
        </Field>
        {!skip && <>
          <p className="rounded-md bg-surface-2 px-2.5 py-1.5 text-sm" data-testid="qs-preview">
            {due ? t("sourcing.rfq.followupPreview", { action: action.trim() || "—", date: f.day(due) }) : t("sourcing.rfq.followupNeedsDate")}</p>
          <Field label={t("followups.action")} htmlFor="qs-action"><Input id="qs-action" dir="auto" value={action} onChange={(e) => setAction(e.target.value)} /></Field>
          <Field label={t("followups.newDue")} htmlFor="qs-due" hint={t("quotes.dueBeforeValidity")}><DueDatePicker id="qs-due" value={due} onChange={setDue} /></Field>
        </>}
        <Checkbox label={t("sourcing.rfq.noFollowup")} checked={skip} onChange={setSkip} />
        {skip && <Field label={t("sourcing.reason")} htmlFor="qs-reason"><Input id="qs-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <Checkbox label={t("quotes.moveToQuoted")} checked={move} onChange={setMove} />
        <ErrorNote error={send.error} />
      </div>
    </Modal>
  );
}

function OutcomeRow({ item, value, reasons, currency, onChange }: {
  item: QuoteItem; value: Body; reasons: OutcomeReason[]; currency: string; onChange: (v: Body) => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const outcome = (value.outcome as string | null) ?? "";
  return (
    <tr className="border-b border-line align-top">
      <td className="p-1.5"><Bdi>{item.description_override || item.name}</Bdi></td>
      <td className="p-1.5">
        <Select className="w-auto min-w-32" aria-label={t("quotes.outcome")} value={outcome} onChange={(e) => onChange({ ...value, outcome: e.target.value || null })}>
          <option value="">—</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{t(`quotes.outcomes.${o}`)}</option>)}
        </Select>
      </td>
      <td className="p-1.5">
        <Select className="w-auto min-w-36" aria-label={t("quotes.reason")} value={(value.outcome_reason as string | null) ?? ""} onChange={(e) => onChange({ ...value, outcome_reason: e.target.value || null })}>
          <option value="">{outcome === "rejected" ? t("quotes.reasonRequired") : "—"}</option>
          {reasons.map((r) => <option key={r.code} value={r.code}>{f.lang === "fa" ? r.label_fa : r.label_en}</option>)}
        </Select>
        <Input dir="auto" className="mt-1" aria-label={t("quotes.outcomeNote")} placeholder={t("quotes.outcomeNote")} value={(value.outcome_note as string | null) ?? ""}
          onChange={(e) => onChange({ ...value, outcome_note: e.target.value || null })} />
      </td>
      <td className="p-1.5">
        <div className="flex gap-1">
          <Input dir="ltr" inputMode="decimal" className="w-28" aria-label={t("quotes.competitorPrice")} value={(value.competitor_price as string | null) ?? ""}
            onChange={(e) => onChange({ ...value, competitor_price: e.target.value || null, competitor_currency: (value.competitor_currency as string | null) ?? currency })} />
          <CurrencySelect className="w-24" value={(value.competitor_currency as string | null) ?? null} onChange={(v) => onChange({ ...value, competitor_currency: v })} />
        </div>
      </td>
    </tr>
  );
}

function OutcomesDialog({ quote, onClose, onDone }: { quote: Quote; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const reasons = useQuery({ queryKey: ["quotes", "reasons"], queryFn: () => api<OutcomeReason[]>("/api/quotes/outcome-reasons") });
  const [values, setValues] = useState<Record<string, Body>>(() => Object.fromEntries(quote.items.map((i) => [i.id, {
    outcome: i.outcome, outcome_reason: i.outcome_reason, outcome_note: i.outcome_note, competitor_price: i.competitor_price,
    competitor_currency: i.competitor_currency }])));
  const save = useMutation({
    mutationFn: () => api(`/api/quotes/${quote.id}/outcomes`, { method: "PUT", body: { items: quote.items.map((i) => ({ quote_item_id: i.id, ...values[i.id] })) } }),
    onSuccess: () => { onDone(); onClose(); },
  });
  const missingReason = quote.items.some((i) => values[i.id].outcome === "rejected" && !values[i.id].outcome_reason);
  return (
    <Modal open wide title={t("quotes.recordOutcome")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={missingReason} busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="max-h-[60vh] overflow-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-xs text-muted">
            {["item", "outcome", "reason", "competitor"].map((h) => <th key={h} className="p-1.5 text-start">{t(`quotes.outcomeColumns.${h}`)}</th>)}
          </tr></thead>
          <tbody>{quote.items.map((i) => <OutcomeRow key={i.id} item={i} value={values[i.id]} reasons={reasons.data ?? []} currency={quote.currency} onChange={(v) => setValues({ ...values, [i.id]: v })} />)}</tbody>
        </table>
      </div>
      {missingReason && <p className="mt-2 text-sm text-danger">{t("quotes.reasonRequiredHint")}</p>}
      <ErrorNote error={save.error} />
    </Modal>
  );
}

function ReasonDialog({ title, onClose, onConfirm, busy, error }: { title: string; onClose: () => void; onConfirm: (reason: string) => void; busy: boolean; error: unknown }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  return (
    <Modal open title={title} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="danger" disabled={!reason.trim()} busy={busy} onClick={() => onConfirm(reason.trim())}>{title}</Button></>}>
      <Field label={t("sourcing.reason")} htmlFor="qw-reason"><Input id="qw-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <ErrorNote error={error} />
    </Modal>
  );
}

function QuoteEditor({ quoteId, onChanged, onSelect }: { quoteId: string; onChanged: () => void; onSelect: (id: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const unitLabel = useUnitLabel();
  const quote = useQuery({ queryKey: ["quote", quoteId], queryFn: () => api<Quote>(`/api/quotes/${quoteId}`) });
  const refresh = () => { void quote.refetch(); onChanged(); };
  const [dialog, setDialog] = useState<null | "sent" | "outcome" | "withdraw">(null);
  const patch = useMutation({ mutationFn: (body: Body) => api(`/api/quotes/${quoteId}`, { method: "PATCH", body }), onSuccess: refresh });
  const patchItem = useMutation({ mutationFn: ({ id, body }: { id: string; body: Body }) => api(`/api/quotes/items/${id}`, { method: "PATCH", body }), onSuccess: refresh });
  const action = useMutation({ mutationFn: (path: string) => api<Quote>(`/api/quotes/${quoteId}/${path}`, { method: "POST", body: path === "revise" ? {} : undefined }),
    onSuccess: (q, path) => { if (path === "revise") { onChanged(); onSelect(q.id); } else refresh(); } });
  const withdraw = useMutation({ mutationFn: (reason: string) => api(`/api/quotes/${quoteId}/withdraw`, { method: "POST", body: { reason } }), onSuccess: () => { setDialog(null); refresh(); } });
  const remove = useMutation({ mutationFn: () => api(`/api/quotes/${quoteId}`, { method: "DELETE" }), onSuccess: () => { onChanged(); onSelect(""); } });
  const output = useMutation({
    mutationFn: (format: "pdf" | "docx") => api<{ document_id: string; filename: string }>(`/api/quotes/${quoteId}/outputs`, { method: "POST", body: { format } }),
    onSuccess: (out) => { refresh(); toast(t("quotes.outputReady", { name: out.filename }), "success"); window.location.assign(`/api/documents/${out.document_id}/download`); },
  });
  if (quote.isLoading) return <Loading />;
  if (quote.error || !quote.data) return <ErrorNote error={quote.error} />;
  const q = quote.data;
  const draft = q.status === "draft";
  const save = (key: string) => (v: string | null) => patch.mutate({ [key]: v });
  const pdfUnavailable = output.error instanceof ApiError && output.error.code === "pdf_unavailable";
  return (
    <div className="flex flex-col gap-4" data-quote={q.id}>
      <Card title={<span className="flex flex-wrap items-center gap-2"><Bdi ltr className="font-mono">{q.number}</Bdi>
        <span className="text-xs text-muted">{t("quotes.version", { version: f.num(q.version) })}</span><StatusBadge group="quote" status={q.status} />
        <Badge>{t(`quotes.basis.${q.price_basis}`)}</Badge></span>}
        actions={<>
          {draft && <Button variant="primary" busy={action.isPending} disabled={!q.approval?.ok} onClick={() => action.mutate("approve")}>{t("quotes.approve")}</Button>}
          {q.status === "approved" && <Button variant="primary" onClick={() => setDialog("sent")}>{t("quotes.markSent")}</Button>}
          {["sent", "expired", "accepted", "partially_accepted", "rejected"].includes(q.status) && <Button variant="primary" onClick={() => setDialog("outcome")}>{t("quotes.recordOutcome")}</Button>}
          {["approved", "sent", "expired", "partially_accepted", "rejected"].includes(q.status) && <Button onClick={() => action.mutate("revise")}>{t("quotes.revise")}</Button>}
          {["approved", "sent", "expired"].includes(q.status) && <Button variant="ghost" onClick={() => setDialog("withdraw")}>{t("quotes.withdraw")}</Button>}
          {draft && <Button variant="ghost" onClick={() => remove.mutate()}>{t("delete.button")}</Button>}
        </>}>
        <div className="mb-3 flex flex-wrap gap-2">
          <a className="inline-flex h-8 items-center rounded-md border border-line-strong px-3 text-sm hover:bg-surface-2" href={`/api/quotes/${q.id}/print`} target="_blank" rel="noreferrer">{t("quotes.printView")}</a>
          <Button icon="download" busy={output.isPending && output.variables === "pdf"} onClick={() => output.mutate("pdf")}>PDF</Button>
          <Button icon="download" busy={output.isPending && output.variables === "docx"} onClick={() => output.mutate("docx")}>Word</Button>
          {draft && <span className="self-center text-xs text-warning">{t("quotes.draftWatermark")}</span>}
        </div>
        {pdfUnavailable && <p className="mb-2 rounded-md bg-warning-soft px-2.5 py-1.5 text-sm text-warning" role="alert">{t("quotes.pdfUnavailable")}</p>}
        <ErrorNote error={pdfUnavailable ? null : output.error || action.error || patch.error || remove.error} />
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("quotes.buyer")}><span className="flex flex-wrap items-center gap-1.5">{q.buyer_party_id ? <PartyName fa={q.buyer_name_fa} en={q.buyer_name_en} id={q.buyer_party_id} /> : <span className="text-danger">{t("quotes.noBuyer")}</span>}
            <ContactName fa={q.contact_name_fa} en={q.contact_name_en} className="text-xs" /></span></Field>
          <Field label={t("quotes.language")} htmlFor="q-lang">
            <Select id="q-lang" className="w-auto min-w-28" value={q.language} disabled={!draft} onChange={(e) => patch.mutate({ language: e.target.value })}>
              <option value="fa">{t("common.languageNames.fa")}</option><option value="en">{t("common.languageNames.en")}</option>
            </Select>
          </Field>
          <Field label={t("quotes.priceBasis")} htmlFor="q-basis">
            <Select id="q-basis" className="w-auto min-w-36" value={q.price_basis} disabled={!draft} onChange={(e) => patch.mutate({ price_basis: e.target.value })}>
              <option value="before_vat">{t("quotes.basis.before_vat")}</option><option value="with_vat">{t("quotes.basis.with_vat")}</option>
            </Select>
          </Field>
          <Field label={t("quotes.validUntil")} htmlFor="q-valid" hint={q.approval?.max_valid_until ? t("quotes.maxValid", { date: f.day(q.approval.max_valid_until) }) : undefined}>
            <DateInput id="q-valid" value={fromDateString(q.valid_until)} onChange={(d) => draft && d && patch.mutate({ valid_until: toDateString(d) })} />
          </Field>
          <Field label={t("sourcing.incoterm")} htmlFor="q-inco">
            <div className="flex gap-1.5"><IncotermSelect id="q-inco" value={q.incoterm} onChange={(v) => draft && patch.mutate({ incoterm: v })} />
              <BlurInput dir="auto" aria-label={t("sourcing.incotermPlace")} placeholder={t("sourcing.incotermPlace")} value={q.incoterm_place} disabled={!draft} onSave={save("incoterm_place")} /></div>
          </Field>
          <Field label={t("quotes.leadTime")} htmlFor="q-lead"><BlurInput id="q-lead" dir="ltr" inputMode="numeric" value={q.lead_time_days === null ? null : String(q.lead_time_days)} disabled={!draft}
            onSave={(v) => patch.mutate({ lead_time_days: v === null ? null : Number(v) })} /></Field>
          <Field label={t("quotes.paymentTerms")} htmlFor="q-pay"><BlurInput id="q-pay" dir="auto" value={q.payment_terms} disabled={!draft} onSave={save("payment_terms")} /></Field>
          <Field label={t("quotes.deliveryTerms")} htmlFor="q-del"><BlurInput id="q-del" dir="auto" value={q.delivery_terms} disabled={!draft} onSave={save("delivery_terms")} /></Field>
          <Field label={t("quotes.costSheet")}><span className="text-sm">{t("costing.version", { version: f.num(q.cost_sheet.version) })} · <StatusBadge group="costSheet" status={q.cost_sheet.status} /></span></Field>
        </div>
      </Card>
      <Card padded={false} title={t("quotes.items")}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
              {["description", "quantity", "unitPrice", "total", "leadTime", "note", "outcome"].map((h) => <th key={h} className="p-1.5 text-start whitespace-nowrap">{t(`quotes.columns.${h}`)}</th>)}
            </tr></thead>
            <tbody>
              {q.items.map((i) => (
                <tr key={i.id} className="border-b border-line align-top">
                  <td className="p-1.5"><BlurInput dir="auto" className="min-w-48" aria-label={t("quotes.columns.description")} value={i.description_override} placeholder={i.name} disabled={!draft}
                    onSave={(v) => patchItem.mutate({ id: i.id, body: { description_override: v } })} /></td>
                  <td className="p-1.5 whitespace-nowrap"><Bdi ltr className="tabular-nums">{f.num(i.quantity)} {unitLabel(i.unit_code, i.unit_text)}</Bdi></td>
                  <td className="p-1.5">
                    {draft ? <BlurInput dir="ltr" inputMode="decimal" className="w-32" aria-label={t("quotes.columns.unitPrice")} value={i.unit_price}
                      onSave={(v) => patchItem.mutate({ id: i.id, body: { unit_price: v } })} /> : <Money amount={i.unit_price} currency={q.currency} />}
                    {i.price_manual && <Badge tone="warning">{t("costing.pricing.manual")}</Badge>}
                  </td>
                  <td className="p-1.5"><Money amount={i.total} currency={q.currency} /></td>
                  <td className="p-1.5"><BlurInput dir="ltr" inputMode="numeric" className="w-20" aria-label={t("quotes.columns.leadTime")} value={i.lead_time_days === null ? null : String(i.lead_time_days)} disabled={!draft}
                    onSave={(v) => patchItem.mutate({ id: i.id, body: { lead_time_days: v === null ? null : Number(v) } })} /></td>
                  <td className="p-1.5"><BlurInput dir="auto" aria-label={t("quotes.columns.note")} value={i.note} disabled={!draft} onSave={(v) => patchItem.mutate({ id: i.id, body: { note: v } })} /></td>
                  <td className="p-1.5">{i.outcome ? <span className="flex flex-col"><StatusBadge group="outcome" status={i.outcome} />{i.outcome_reason && <span className="text-xs text-muted">{t(`quotes.reasons.${i.outcome_reason}`, { defaultValue: i.outcome_reason })}</span>}</span> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 px-4 py-3 text-sm" data-testid="quote-totals">
          <div><dt className="text-xs text-muted">{t("costing.pricing.priceBeforeVat")}</dt><dd className="font-semibold"><Money amount={q.subtotal} currency={q.currency} /></dd></div>
          <div><dt className="text-xs text-muted">{t("costing.pricing.vat")}</dt><dd><Money amount={q.vat_amount} currency={q.currency} /></dd></div>
          <div><dt className="text-xs text-muted">{t("quotes.total")}</dt><dd className="font-semibold"><Money amount={q.total} currency={q.currency} /></dd></div>
          <div className="self-end text-xs text-muted">{t(`quotes.basisNote.${q.price_basis}`)}</div>
        </dl>
        <ErrorNote error={patchItem.error} />
      </Card>
      <Card title={t("quotes.terms")} actions={draft ? <Button variant="ghost" onClick={() => action.mutate("terms")}>{t("quotes.regenerateTerms")}</Button> : undefined}>
        <BlurInput multiline id="q-terms" aria-label={t("quotes.terms")} value={q.terms_text} disabled={!draft} onSave={save("terms_text")} />
        <p className="mt-1 text-xs text-muted">{t("quotes.termsHint")}</p>
      </Card>
      {q.approval && (
        <Card title={<span className="flex items-center gap-2">{t("quotes.approvalTitle")}{q.approval.ok ? <Badge tone="success">{t("costing.gate.ok")}</Badge> : <Badge tone="warning">{t("costing.gate.blocked")}</Badge>}</span>}>
          <ul className="flex flex-col gap-1 text-sm" data-testid="approval-checklist">
            {gateChecklist(q.approval.failures).filter((r) => !r.ok || r.code === "sheet_not_final").map((r) => (
              <li key={r.code} className="flex items-center gap-2"><span aria-hidden className={r.ok ? "text-success" : "text-danger"}>{r.ok ? "✓" : "✗"}</span>{t(`costing.gate.conditions.${r.code}`, { defaultValue: r.code })}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">{t("quotes.approveHint")}</p>
        </Card>
      )}
      {q.outputs.length > 0 && (
        <Card title={t("quotes.outputs")}>
          <ul className="flex flex-col gap-1 text-sm">{q.outputs.map((d) => (
            <li key={d.link_id} className="flex flex-wrap items-center gap-2"><a className="text-accent hover:underline" href={`/api/documents/${d.document_id}/download`}><Bdi ltr>{d.original_filename}</Bdi></a>
              <span className="text-xs text-muted tabular-nums">{f.date(d.linked_at, true)}</span></li>
          ))}</ul>
        </Card>
      )}
      {dialog === "sent" && <MarkSentDialog quote={q} onClose={() => setDialog(null)} onDone={refresh} />}
      {dialog === "outcome" && <OutcomesDialog quote={q} onClose={() => setDialog(null)} onDone={refresh} />}
      {dialog === "withdraw" && <ReasonDialog title={t("quotes.withdraw")} onClose={() => setDialog(null)} onConfirm={(r) => withdraw.mutate(r)} busy={withdraw.isPending} error={withdraw.error} />}
    </div>
  );
}

export function QuotesTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const invalidate = useInvalidateSourcing();
  const [params, setParams] = useSearchParams();
  const quotes = useQuery({ queryKey: ["case-quotes", caseData.id], queryFn: () => api<CaseQuotes>(`/api/cases/${caseData.id}/quotes`) });
  const selected = params.get("quote") || quotes.data?.items[0]?.id || null;
  const select = (id: string) => setParams(id ? { tab: "quotes", quote: id } : { tab: "quotes" }, { replace: true });
  const refresh = () => { void quotes.refetch(); invalidate(); };
  const result = useMutation({ mutationFn: (r: "won" | "lost") => api(`/api/cases/${caseData.id}/quote-result`, { method: "POST", body: { result: r } }), onSuccess: refresh });
  const s = quotes.data?.summary;
  return (
    <div className="flex flex-col gap-4">
      {s && s.count > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span>{t("quotes.summary", { count: s.count, n: f.num(s.count), won: f.num(s.won), lost: f.num(s.lost) })}</span>
          {s.all_decided && caseData.status === "open" && <>
            <Button variant="primary" busy={result.isPending} onClick={() => result.mutate("won")}>{t("quotes.markWon")}</Button>
            <Button variant="danger" busy={result.isPending} onClick={() => result.mutate("lost")}>{t("quotes.markLost")}</Button>
          </>}
          <ErrorNote error={result.error} />
        </div>
      )}
      {quotes.data && quotes.data.items.length === 0 && <Card><EmptyState>{t("quotes.empty")}</EmptyState></Card>}
      {quotes.data && quotes.data.items.length > 0 && (
        <Card padded={false}>
          <ul className="divide-y divide-line">
            {quotes.data.items.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => select(r.id)} aria-pressed={r.id === selected}
                  className={`flex w-full flex-wrap items-center gap-2 px-4 py-2 text-start text-sm ${r.id === selected ? "bg-accent-soft" : "hover:bg-surface-2"}`}>
                  <Bdi ltr className="font-mono">{r.number}</Bdi><span className="text-xs text-muted">{t("costing.version", { version: f.num(r.version) })}</span>
                  <StatusBadge group="quote" status={r.status} />
                  <Bdi>{personName(r.buyer_name_fa, r.buyer_name_en, f.lang)}</Bdi>
                  <span className="ms-auto"><Money amount={r.total} currency={r.currency} /></span>
                  <span className="text-xs text-muted tabular-nums">{t("quotes.validUntil")}: {f.day(r.valid_until)}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {selected && <QuoteEditor key={selected} quoteId={selected} onChanged={refresh} onSelect={select} />}
    </div>
  );
}
