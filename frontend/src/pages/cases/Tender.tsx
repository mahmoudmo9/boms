/** Tender tab of a case (v0.6.0): stepper, Setad banners and refresh, dates with reminders, addenda, envelopes A/B/C
 * with the company documents library, guarantees, costs, the financial proposal, submission and result. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { TimeLeftBadge } from "../../components/TimeLeft";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, Input, Loading, Modal, Select, Textarea } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import { blockerMessage, combineDateTime, nextGuaranteeSteps, parseReminderDays, progressText, stepper, timeOf } from "../../lib/tenders";
import type { Blocker, CaseDetail, CompanyDocumentRow, EnvelopeItemRow, GuaranteeRow, ProposalRow, ResultReasonRow, TenderDetail, TenderStage } from "../../lib/types";
import { PartyName } from "../parties/shared";
import { CurrencySelect, Money } from "../sourcing/shared";

type Body = Record<string, unknown>;
type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
const DATE_KINDS = ["documents_deadline", "briefing", "site_visit", "questions_deadline", "proposal_deadline", "opening",
  "quality_docs_deadline", "offer_valid_until", "other"] as const;
const ITEM_STATUSES = ["not_ready", "in_progress", "needs_signature", "ready", "submitted"] as const;
const STATUS_TONE: Record<string, "neutral" | "warning" | "accent" | "success" | "danger"> = {
  not_ready: "neutral", in_progress: "accent", needs_signature: "warning", ready: "success", submitted: "success",
  to_request: "neutral", requested: "accent", issued: "success", ready_to_upload: "success", extended: "warning",
  released: "neutral", claimed: "danger", cancelled: "neutral",
};

export function useTender(caseId: string) {
  return useQuery({ queryKey: ["tender", caseId], queryFn: () => api<TenderDetail | null>(`/api/cases/${caseId}/tender`) });
}

function useTenderMutation(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ method = "POST", path, body }: { method?: Method; path: string; body?: Body }) => api<TenderDetail>(path, { method, body }),
    onSuccess: (data) => {
      if (data && typeof data === "object" && "envelope_items" in data) queryClient.setQueryData(["tender", caseId], data);
      else void queryClient.invalidateQueries({ queryKey: ["tender", caseId] });
      void queryClient.invalidateQueries({ queryKey: ["case", caseId] });
    },
  });
}

/** Header facts for the case page: next date, envelope progress, bid bond status. */
export function TenderHeaderFacts({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const tender = useTender(caseId);
  const d = tender.data;
  if (!d) return null;
  const p = progressText(d.envelope_progress.all);
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="tender-header">
      {d.next_date && <span className="inline-flex items-center gap-1">{t(`tenders.dateKinds.${d.next_date.kind}`)}: <span className="tabular-nums">{f.date(d.next_date.at, true)}</span>
        <TimeLeftBadge at={d.next_date.at} /></span>}
      <Badge tone={p.complete ? "success" : "neutral"}>{t("tenders.envelopes.progress", { done: f.num(p.done), total: f.num(p.total) })}</Badge>
      {d.bid_bond && <Badge tone={STATUS_TONE[d.bid_bond.status] ?? "neutral"}>{t("tenders.guarantee.bidBond")}: {t(`tenders.guarantee.statuses.${d.bid_bond.status}`)}</Badge>}
    </span>
  );
}

export function TenderTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const tender = useTender(caseData.id);
  const m = useTenderMutation(caseData.id);
  if (tender.isLoading) return <Loading />;
  if (tender.error) return <ErrorNote error={tender.error} />;
  if (!tender.data) {
    return (
      <Card title={t("tenders.title")}>
        <p className="mb-2 text-sm text-muted">{t("tenders.notATender")}</p>
        <Button variant="primary" data-testid="make-tender" busy={m.isPending} onClick={() => m.mutate({ path: `/api/cases/${caseData.id}/tender` })}>{t("tenders.makeTender")}</Button>
        <ErrorNote error={m.error} />
      </Card>
    );
  }
  const d = tender.data;
  const run = (path: string, body?: Body, method: Method = "POST") => m.mutate({ path, body, method });
  return (
    <div className="flex flex-col gap-4" data-testid="tender-tab">
      <Overview d={d} run={run} />
      <ErrorNote error={m.error} />
      <SetadBanners d={d} run={run} />
      <div className="grid gap-4 xl:grid-cols-2">
        <DatesCard d={d} run={run} />
        <AddendaCard d={d} run={run} />
      </div>
      <EnvelopesCard d={d} run={run} />
      <GuaranteesCard d={d} caseData={caseData} />
      <div className="grid gap-4 xl:grid-cols-2">
        <CostsCard d={d} run={run} />
        <ProposalCard d={d} caseId={caseData.id} />
      </div>
      <SubmitAndResult d={d} run={run} />
    </div>
  );
}

type Run = (path: string, body?: Body, method?: Method) => void;

// ---- overview: stepper, participation, mode ---------------------------------------------------------------------------

function Overview({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [reason, setReason] = useState(d.participation_reason ?? "");
  const patch = (body: Body) => run(`/api/tenders/${d.id}`, body, "PATCH");
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{t("tenders.title")}
      {d.tender_no && <Bdi ltr className="font-mono text-sm">{d.tender_no}</Bdi>}
      {d.tender_type && <span className="text-sm font-normal text-muted" dir="auto">{d.tender_type}</span>}</span>}>
      <TenderStepper stage={d.stage} hint={d.stage_hint} onPick={(stage) => patch({ stage })} />
      {d.stage_hint !== d.stage && <p className="mb-3 text-xs text-warning" data-testid="stage-hint">{t("tenders.hintText", { stage: t(`tenders.stages.${d.stage_hint}`) })}</p>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Field label={t("tenders.participation")} htmlFor="t-part">
          <Select id="t-part" value={d.participation} onChange={(e) => e.target.value !== "no" ? patch({ participation: e.target.value }) : patch({ participation: "no", participation_reason: reason || null })}>
            {(["undecided", "yes", "no"] as const).map((v) => <option key={v} value={v}>{t(`tenders.participations.${v}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("tenders.participationReason")} htmlFor="t-reason">
          <Input id="t-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)}
            onBlur={() => reason !== (d.participation_reason ?? "") && patch({ participation_reason: reason || null })} />
        </Field>
        <Field label={t("tenders.financialMode")} htmlFor="t-mode">
          <Select id="t-mode" value={d.financial_mode} onChange={(e) => patch({ financial_mode: e.target.value })}>
            <option value="buyer_form">{t("tenders.modes.buyer_form")}</option><option value="letterhead">{t("tenders.modes.letterhead")}</option>
          </Select>
        </Field>
        <Field label={t("tenders.organizer")}>
          {d.organizer ? <PartyName fa={d.organizer.name_fa} en={d.organizer.name_en} id={d.organizer.id} /> : <span className="text-sm text-warning">{t("tenders.noOrganizer")}</span>}
        </Field>
        <Field label={t("tenders.documentPrice")}><Money amount={d.document_price} currency={d.document_price_currency} /></Field>
        <Field label={t("tenders.estimate")}><Money amount={d.estimate} currency={d.estimate_currency} /></Field>
        <Field label={t("tenders.validityDays")} htmlFor="t-vd">
          <Input id="t-vd" dir="ltr" inputMode="numeric" defaultValue={d.proposal_validity_days ?? ""} key={d.proposal_validity_days ?? "x"}
            onBlur={(e) => { const n = Number(e.target.value) || null; if (n !== d.proposal_validity_days) patch({ proposal_validity_days: n }); }} />
        </Field>
        <Field label={t("tenders.neededUntil")}><span className="text-sm tabular-nums">{d.needed_until ? f.day(d.needed_until) : "—"}</span></Field>
      </div>
    </Card>
  );
}

// ---- Setad --------------------------------------------------------------------------------------------------------

function SetadBanners({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [diff, setDiff] = useState(false);
  if (!d.listing_id) return null;
  const appendices = Object.entries(d.new_appendices);
  return (
    <div className="flex flex-col gap-2">
      {d.setad_date_changes.length > 0 && (
        <div role="alert" data-testid="setad-dates-changed" className="flex flex-col gap-1.5 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning">
          <b>{t("tenders.setad.datesChanged")}</b>
          {d.setad_date_changes.map((c) => (
            <span key={c.kind} className="flex flex-wrap items-center gap-2">
              <span>{t(`tenders.dateKinds.${c.kind}`)}:</span>
              <span className="tabular-nums">{c.old ? f.date(c.old, true) : "—"} → {f.date(c.new, true)}</span>
              <Button variant="ghost" onClick={() => run(`/api/tenders/${d.id}/setad-dates/apply`, { kind: c.kind })}>{t("tenders.setad.apply")}</Button>
            </span>
          ))}
          <span className="flex flex-wrap gap-1.5"><Button variant="primary" onClick={() => run(`/api/tenders/${d.id}/setad-dates/apply`, {})}>{t("tenders.setad.applyAll")}</Button>
            <Button variant="ghost" data-testid="keep-dates" onClick={() => run(`/api/tenders/${d.id}/setad-dates/keep`)}>{t("tenders.setad.keep")}</Button></span>
        </div>
      )}
      {appendices.length > 0 && (
        <div role="alert" data-testid="setad-new-addenda" className="flex flex-wrap items-center gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning">
          <b>{t("tenders.setad.newAddenda")}</b>
          <span>{appendices.map(([k, n]) => `${t(`tenders.setad.appendix.${k}`)}: ${f.num(n)}`).join("، ")}</span>
          <Link className="text-accent hover:underline" to={`/tenders?source=setad_tender&include_old=1&deadline=any&listing=${d.listing_id}`}>{t("tenders.setad.openListing")}</Link>
          <Button variant="ghost" onClick={() => run(`/api/tenders/${d.id}/appendices/seen`)}>{t("tenders.setad.seen")}</Button>
        </div>
      )}
      <div><Button onClick={() => setDiff(true)} data-testid="setad-refresh">{t("tenders.setad.refresh")}</Button></div>
      {diff && <RefreshDialog d={d} onClose={() => setDiff(false)} run={run} />}
    </div>
  );
}

function RefreshDialog({ d, onClose, run }: { d: TenderDetail; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const preview = useQuery({ queryKey: ["tender-refresh", d.id], queryFn: () => api<{ changes: { field: string; current: unknown; setad: unknown }[] }>(`/api/tenders/${d.id}/setad-refresh`) });
  const [chosen, setChosen] = useState<string[]>([]);
  const show = (field: string, v: unknown) => v === null || v === undefined ? "—" : field.startsWith("date:") ? f.date(String(v), true) : field.includes("price") || field.includes("estimate") || field.includes("amount") ? f.num(String(v)) : String(v);
  const label = (field: string) => field.startsWith("date:") ? t(`tenders.dateKinds.${field.slice(5)}`) : t(`tenders.fields.${field}`, { defaultValue: field });
  return (
    <Modal open wide title={t("tenders.setad.refresh")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!chosen.length} onClick={() => { run(`/api/tenders/${d.id}/setad-refresh`, { fields: chosen }); onClose(); }}>{t("tenders.setad.applyChosen")}</Button></>}>
      {preview.isLoading && <Loading />}
      <ErrorNote error={preview.error} />
      {preview.data && (preview.data.changes.length === 0 ? <EmptyState>{t("tenders.setad.noDiff")}</EmptyState> : (
        <table className="w-full text-sm" data-testid="refresh-diff"><thead><tr className="text-xs text-muted"><th></th><th className="text-start">{t("tenders.setad.field")}</th>
          <th className="text-start">{t("tenders.setad.current")}</th><th className="text-start">{t("tenders.setad.onSetad")}</th></tr></thead>
          <tbody>{preview.data.changes.map((c) => (
            <tr key={c.field} className="border-t border-line">
              <td className="p-1"><input type="checkbox" aria-label={label(c.field)} className="h-4 w-4 accent-[var(--accent)]" checked={chosen.includes(c.field)}
                onChange={(e) => setChosen(e.target.checked ? [...chosen, c.field] : chosen.filter((x) => x !== c.field))} /></td>
              <td className="p-1">{label(c.field)}</td><td className="p-1 tabular-nums" dir="auto">{show(c.field, c.current)}</td>
              <td className="p-1 tabular-nums" dir="auto">{show(c.field, c.setad)}</td></tr>))}</tbody></table>
      ))}
    </Modal>
  );
}

// ---- dates and addenda ----------------------------------------------------------------------------------------------

function DateEditor({ initial, onSave, onClose, needReason }: {
  initial?: { kind: string; label: string | null; at: string; remind_days_before: number[]; note: string | null };
  onSave: (body: Body) => void; onClose: () => void; needReason: boolean;
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState(initial?.kind ?? "proposal_deadline");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [day, setDay] = useState<Date | null>(initial ? new Date(initial.at) : null);
  const [time, setTime] = useState(initial ? timeOf(initial.at) : "12:00");
  const [days, setDays] = useState((initial?.remind_days_before ?? [3, 1]).join("، "));
  const [reason, setReason] = useState("");
  const parsed = parseReminderDays(days);
  const at = day ? combineDateTime(day, time) : null;
  const ok = at !== null && parsed !== null && (kind !== "other" || label.trim()) && (!needReason || initial?.at === at || reason.trim());
  return (
    <Modal open title={initial ? t("tenders.dates.edit") : t("tenders.dates.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!ok} data-testid="date-save" onClick={() => onSave({ ...(initial ? {} : { kind }), label: kind === "other" ? label.trim() : null, at,
          remind_days_before: parsed, ...(needReason && initial?.at !== at ? { reason: reason.trim() } : {}) })}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="date-editor">
        {!initial && <Field label={t("tenders.dates.kind")} htmlFor="td-kind">
          <Select id="td-kind" value={kind} onChange={(e) => setKind(e.target.value)}>{DATE_KINDS.map((k) => <option key={k} value={k}>{t(`tenders.dateKinds.${k}`)}</option>)}</Select></Field>}
        {kind === "other" && <Field label={t("tenders.dates.label")} htmlFor="td-label"><Input id="td-label" dir="auto" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>}
        <div className="flex flex-wrap gap-3">
          <Field label={t("tenders.dates.day")} htmlFor="td-day"><DateInput id="td-day" value={day} onChange={setDay} /></Field>
          <Field label={t("tenders.dates.time")} htmlFor="td-time"><Input id="td-time" dir="ltr" className="w-24" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
        </div>
        <Field label={t("tenders.dates.reminders")} htmlFor="td-days" hint={parsed === null ? t("tenders.dates.remindersInvalid") : t("tenders.dates.remindersHint")}>
          <Input id="td-days" dir="auto" value={days} onChange={(e) => setDays(e.target.value)} aria-invalid={parsed === null} />
        </Field>
        {needReason && initial && initial.at !== at && <Field label={t("tenders.dates.reason")} htmlFor="td-reason">
          <Input id="td-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
      </div>
    </Modal>
  );
}

function DatesCard({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const current = d.dates.find((x) => x.id === editing);
  return (
    <Card padded={false} title={t("tenders.dates.title")} actions={<Button icon="plus" onClick={() => setEditing("new")}>{t("tenders.dates.add")}</Button>}>
      {d.dates.length === 0 ? <EmptyState>{t("tenders.dates.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid="tender-dates">
          {d.dates.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
              <span className="min-w-36 font-medium">{x.kind === "other" ? <Bdi>{x.label}</Bdi> : t(`tenders.dateKinds.${x.kind}`)}</span>
              <span className="tabular-nums">{f.date(x.at, true)}</span>
              <TimeLeftBadge at={x.at} />
              <Badge>{t(`tenders.dates.sources.${x.source}`)}</Badge>
              <span className="text-xs text-muted">{x.reminders.length ? t("tenders.dates.reminderList", { list: x.reminders.map((r) => f.day(r.due_on)).join("، ") }) : t("tenders.dates.noReminders")}</span>
              <span className="ms-auto flex gap-1">
                <Button variant="ghost" onClick={() => setEditing(x.id)}>{t("common.edit")}</Button>
                <Button variant="ghost" onClick={() => run(`/api/tender-dates/${x.id}`, undefined, "DELETE")}>{t("common.remove")}</Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {d.date_changes.length > 0 && (
        <details className="border-t border-line px-4 py-2 text-xs"><summary className="cursor-pointer text-muted">{t("tenders.dates.history", { n: f.num(d.date_changes.length) })}</summary>
          <ul className="mt-1 flex flex-col gap-0.5">{d.date_changes.map((c) => (
            <li key={c.id}><span className="tabular-nums">{c.old_at ? f.date(c.old_at, true) : "—"} → {f.date(c.new_at, true)}</span> · <Bdi>{c.reason}</Bdi></li>))}</ul></details>
      )}
      {editing === "new" && <DateEditor needReason={false} onClose={() => setEditing(null)} onSave={(b) => { run(`/api/tenders/${d.id}/dates`, b); setEditing(null); }} />}
      {current && <DateEditor needReason initial={current} onClose={() => setEditing(null)} onSave={(b) => { run(`/api/tender-dates/${current.id}`, b, "PATCH"); setEditing(null); }} />}
    </Card>
  );
}

function AddendumDialog({ d, onClose, run }: { d: TenderDetail; onClose: () => void; run: Run }) {
  const { t } = useTranslation();
  const [form, setForm] = useState<Body>({ kind: "extension", number: "", summary: "", question: "", answer: "" });
  const [received, setReceived] = useState<Date | null>(new Date());
  const [changes, setChanges] = useState<Record<string, { day: Date | null; time: string }>>({});
  const [confirm, setConfirm] = useState(false);
  const dateChanges = Object.entries(changes).map(([id, v]) => v.day ? { date_id: id, at: combineDateTime(v.day, v.time) } : null).filter(Boolean);
  const ok = received && String(form.summary).trim() && (form.kind !== "cancellation" || confirm);
  return (
    <Modal open wide title={t("tenders.addenda.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!ok} data-testid="addendum-save" onClick={() => { run(`/api/tenders/${d.id}/addenda`, {
          kind: form.kind, number: String(form.number).trim() || null, summary: String(form.summary).trim(), received_on: toDateString(received!),
          question: String(form.question).trim() || null, answer: String(form.answer).trim() || null, date_changes: dateChanges,
          confirm_cancellation: confirm }); onClose(); }}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="addendum-dialog">
        <div className="flex flex-wrap gap-3">
          <Field label={t("tenders.addenda.kind")} htmlFor="ad-kind"><Select id="ad-kind" value={String(form.kind)} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {["extension", "change", "clarification", "question_answer", "cancellation", "other"].map((k) => <option key={k} value={k}>{t(`tenders.addenda.kinds.${k}`)}</option>)}</Select></Field>
          <Field label={t("tenders.addenda.number")} htmlFor="ad-no"><Input id="ad-no" dir="auto" className="w-28" value={String(form.number)} onChange={(e) => setForm({ ...form, number: e.target.value })} /></Field>
          <Field label={t("tenders.addenda.received")} htmlFor="ad-rec"><DateInput id="ad-rec" value={received} onChange={setReceived} /></Field>
        </div>
        <Field label={t("tenders.addenda.summary")} htmlFor="ad-sum"><Textarea id="ad-sum" dir="auto" rows={2} value={String(form.summary)} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></Field>
        {form.kind === "question_answer" && <>
          <Field label={t("tenders.addenda.question")} htmlFor="ad-q"><Textarea id="ad-q" dir="auto" rows={2} value={String(form.question)} onChange={(e) => setForm({ ...form, question: e.target.value })} /></Field>
          <Field label={t("tenders.addenda.answer")} htmlFor="ad-a"><Textarea id="ad-a" dir="auto" rows={2} value={String(form.answer)} onChange={(e) => setForm({ ...form, answer: e.target.value })} /></Field>
        </>}
        {(form.kind === "extension" || form.kind === "change") && d.dates.length > 0 && (
          <fieldset className="flex flex-col gap-2 rounded-md border border-line p-2"><legend className="px-1 text-xs text-muted">{t("tenders.addenda.dateChanges")}</legend>
            {d.dates.map((x) => (
              <div key={x.id} className="flex flex-wrap items-end gap-2 text-sm">
                <span className="min-w-36">{x.kind === "other" ? x.label : t(`tenders.dateKinds.${x.kind}`)}</span>
                <DateInput id={`ad-d-${x.kind}`} value={changes[x.id]?.day ?? null} onChange={(v) => setChanges({ ...changes, [x.id]: { day: v, time: changes[x.id]?.time ?? timeOf(x.at) } })} />
                <Input dir="ltr" aria-label={t("tenders.dates.time")} className="w-20" value={changes[x.id]?.time ?? timeOf(x.at)}
                  onChange={(e) => setChanges({ ...changes, [x.id]: { day: changes[x.id]?.day ?? null, time: e.target.value } })} />
              </div>
            ))}
          </fieldset>
        )}
        {form.kind === "cancellation" && <Checkbox label={t("tenders.addenda.confirmCancel")} checked={confirm} onChange={setConfirm} />}
      </div>
    </Modal>
  );
}

function AddendaCard({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [adding, setAdding] = useState(false);
  return (
    <Card padded={false} title={t("tenders.addenda.title")} actions={<Button icon="plus" onClick={() => setAdding(true)} data-testid="add-addendum">{t("tenders.addenda.add")}</Button>}>
      {d.addenda.length === 0 ? <EmptyState>{t("tenders.addenda.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid="tender-addenda">{d.addenda.map((a) => (
          <li key={a.id} className="flex flex-col gap-0.5 px-4 py-2 text-sm">
            <span className="flex flex-wrap items-center gap-2"><Badge>{t(`tenders.addenda.kinds.${a.kind}`)}</Badge>{a.number && <Bdi ltr>{a.number}</Bdi>}
              <span className="text-xs tabular-nums text-muted">{f.day(a.received_on)}</span></span>
            <span dir="auto">{a.summary}</span>
            {a.question && <span className="text-xs" dir="auto">{t("tenders.addenda.q")}: {a.question}</span>}
            {a.answer && <span className="text-xs" dir="auto">{t("tenders.addenda.a")}: {a.answer}</span>}
          </li>))}</ul>
      )}
      {adding && <AddendumDialog d={d} onClose={() => setAdding(false)} run={run} />}
    </Card>
  );
}

// ---- envelopes -------------------------------------------------------------------------------------------------------

function LibraryPicker({ onPick, onClose }: { onPick: (id: string) => void; onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const docs = useQuery({ queryKey: ["company-documents"], queryFn: () => api<CompanyDocumentRow[]>("/api/company-documents") });
  return (
    <Modal open title={t("tenders.library.pick")} onClose={onClose} footer={<Button onClick={onClose}>{t("common.close")}</Button>}>
      {docs.isLoading && <Loading />}
      {docs.data && (docs.data.length === 0 ? <EmptyState>{t("tenders.library.empty")} <Link className="text-accent hover:underline" to="/settings/company-documents">{t("tenders.library.open")}</Link></EmptyState> : (
        <ul className="divide-y divide-line" data-testid="library-picker">{docs.data.map((doc) => (
          <li key={doc.id}><button type="button" className="flex w-full flex-wrap items-center gap-2 px-2 py-1.5 text-start text-sm hover:bg-surface-2" onClick={() => onPick(doc.id)}>
            <span dir="auto" className="flex-1">{doc.title}</span>
            <Badge tone={doc.expiry === "expired" ? "danger" : doc.expiry === "soon" ? "warning" : doc.expiry === "ok" ? "success" : "neutral"}>
              {t(`tenders.library.expiry.${doc.expiry}`)}{doc.expires_on ? ` · ${f.day(doc.expires_on)}` : ""}</Badge></button></li>))}</ul>
      ))}
    </Modal>
  );
}

function EnvelopeItem({ item, run, first, last, onMove }: { item: EnvelopeItemRow; run: Run; first: boolean; last: boolean; onMove: (dir: -1 | 1) => void }) {
  const { t } = useTranslation();
  const [picking, setPicking] = useState(false);
  const patch = (body: Body) => run(`/api/envelope-items/${item.id}`, body, "PATCH");
  const doc = item.company_document;
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-1.5 text-sm" data-testid="envelope-item" data-item={item.id}>
      <span className="min-w-56 flex-1" dir="auto">{item.title}
        {doc && <span className={`ms-2 text-xs ${doc.expiry === "expired" ? "text-danger" : doc.expiry === "soon" ? "text-warning" : "text-muted"}`}>
          📎 <Bdi>{doc.title}</Bdi>{doc.expiry === "expired" ? ` · ${t("tenders.library.expiry.expired")}` : ""}</span>}
        {item.kind === "bid_bond" && <span className="ms-2 text-xs text-muted">{t("tenders.envelopes.followsBond")}</span>}</span>
      <span className="flex shrink-0 items-center gap-1">
        <Select aria-label={t("tenders.envelopes.status")} className="w-auto" value={item.status} onChange={(e) => patch({ status: e.target.value })}>
          {ITEM_STATUSES.map((s) => <option key={s} value={s}>{t(`tenders.envelopes.statuses.${s}`)}</option>)}
        </Select>
        {item.kind === "document" && <Button variant="ghost" onClick={() => setPicking(true)}>{t("tenders.library.use")}</Button>}
        <Button variant="ghost" disabled={first} aria-label={t("tenders.envelopes.up")} onClick={() => onMove(-1)}>▲</Button>
        <Button variant="ghost" disabled={last} aria-label={t("tenders.envelopes.down")} onClick={() => onMove(1)}>▼</Button>
        <Button variant="ghost" aria-label={t("common.remove")} onClick={() => run(`/api/envelope-items/${item.id}`, undefined, "DELETE")}>✕</Button>
      </span>
      {picking && <LibraryPicker onClose={() => setPicking(false)} onPick={(id) => { patch({ company_document_id: id }); setPicking(false); }} />}
    </li>
  );
}

function EnvelopesCard({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [title, setTitle] = useState<Record<string, string>>({});
  return (
    <Card padded={false} title={<span className="flex items-center gap-2">{t("tenders.envelopes.title")}
      <EnvelopeProgressBadge p={d.envelope_progress.all} num={f.num} long /></span>}
      actions={<Button variant="ghost" onClick={() => run(`/api/tenders/${d.id}/envelope-items/from-template`, {})}>{t("tenders.envelopes.fromTemplate")}</Button>}>
      <div className="flex flex-col divide-y divide-line" data-testid="envelopes">
        {(["A", "B", "C"] as const).map((env) => {
          const items = d.envelope_items.filter((i) => i.envelope === env);
          const move = (i: number, dir: -1 | 1) => {
            const ids = items.map((x) => x.id);
            [ids[i], ids[i + dir]] = [ids[i + dir], ids[i]];
            run(`/api/tenders/${d.id}/envelope-items/reorder`, { envelope: env, item_ids: ids });
          };
          return (
            <section key={env} data-testid={`envelope-${env}`} className="min-w-0">
              <h3 className="flex items-center gap-2 px-4 pt-3 pb-1 text-sm font-medium">{t(`tenders.envelopes.names.${env}`)}
                <EnvelopeProgressBadge p={d.envelope_progress[env]} num={f.num} /></h3>
              <ul className="divide-y divide-line">{items.map((it, i) => <EnvelopeItem key={it.id} item={it} run={run} first={i === 0} last={i === items.length - 1} onMove={(dir) => move(i, dir)} />)}</ul>
              <div className="flex max-w-xl gap-1.5 px-4 py-2">
                <Input dir="auto" aria-label={t("tenders.envelopes.newItem")} placeholder={t("tenders.envelopes.newItem")} value={title[env] ?? ""}
                  onChange={(e) => setTitle({ ...title, [env]: e.target.value })} />
                <Button disabled={!(title[env] ?? "").trim()} onClick={() => { run(`/api/tenders/${d.id}/envelope-items`, { envelope: env, title: title[env].trim() }); setTitle({ ...title, [env]: "" }); }}>{t("common.add")}</Button>
              </div>
            </section>
          );
        })}
      </div>
    </Card>
  );
}

// ---- guarantees -------------------------------------------------------------------------------------------------------

function GuaranteeForm({ initial, onSave, onClose, busy, error }: { initial: Partial<GuaranteeRow>; onSave: (b: Body) => void; onClose: () => void; busy: boolean; error: unknown }) {
  const { t } = useTranslation();
  const [g, setG] = useState<Body>({ purpose: "bid", form: "bank", ...initial });
  const set = (k: string) => (e: { target: { value: string } }) => setG({ ...g, [k]: e.target.value || null });
  const day = (k: string) => (v: Date | null) => setG({ ...g, [k]: v ? toDateString(v) : null });
  return (
    <Modal open wide title={initial.id ? t("tenders.guarantee.edit") : t("tenders.guarantee.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={busy} data-testid="guarantee-save" onClick={() => onSave(g)}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-3" data-testid="guarantee-form">
        <Field label={t("tenders.guarantee.purpose")} htmlFor="g-purpose"><Select id="g-purpose" value={String(g.purpose)} onChange={set("purpose")}>
          {["bid", "performance", "advance_payment", "retention", "other"].map((p) => <option key={p} value={p}>{t(`tenders.guarantee.purposes.${p}`)}</option>)}</Select></Field>
        <Field label={t("tenders.guarantee.form")} htmlFor="g-form"><Select id="g-form" value={String(g.form ?? "")} onChange={set("form")}>
          <option value="">—</option>{["bank", "electronic_bank", "cheque", "cash_deposit", "insurance", "promissory_note", "other"].map((p) => <option key={p} value={p}>{t(`tenders.guarantee.forms.${p}`)}</option>)}</Select></Field>
        <Field label={t("tenders.guarantee.amount")} htmlFor="g-amount"><div className="flex gap-1.5"><Input id="g-amount" dir="ltr" inputMode="decimal" value={String(g.amount ?? "")} onChange={set("amount")} />
          <CurrencySelect value={(g.amount_currency as string) ?? "IRR"} onChange={(v) => setG({ ...g, amount_currency: v })} /></div></Field>
        <Field label={t("tenders.guarantee.bank")} htmlFor="g-bank"><Input id="g-bank" dir="auto" value={String(g.bank_name ?? "")} onChange={set("bank_name")} /></Field>
        <Field label={t("tenders.guarantee.branch")} htmlFor="g-branch"><Input id="g-branch" dir="auto" value={String(g.branch ?? "")} onChange={set("branch")} /></Field>
        <Field label={t("tenders.guarantee.number")} htmlFor="g-number"><Input id="g-number" dir="ltr" value={String(g.number ?? "")} onChange={set("number")} /></Field>
        <Field label={t("tenders.guarantee.validUntil")} htmlFor="g-valid"><DateInput id="g-valid" value={g.valid_until ? fromDateString(String(g.valid_until)) : null} onChange={day("valid_until")} /></Field>
        <Field label={t("tenders.guarantee.fee")} htmlFor="g-fee"><Input id="g-fee" dir="ltr" inputMode="decimal" value={String(g.fee ?? "")} onChange={set("fee")} /></Field>
        <Field label={t("tenders.guarantee.blocked")} htmlFor="g-blocked"><Input id="g-blocked" dir="ltr" inputMode="decimal" value={String(g.blocked_deposit ?? "")} onChange={set("blocked_deposit")} /></Field>
        <Field label={t("tenders.guarantee.description")} htmlFor="g-desc"><Input id="g-desc" dir="auto" value={String(g.description ?? "")} onChange={set("description")} /></Field>
      </div>
      <ErrorNote error={error} />
    </Modal>
  );
}

function StatusDialog({ g, status, onClose, onDone }: { g: GuaranteeRow; status: string; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [on, setOn] = useState<Date | null>(new Date());
  const [valid, setValid] = useState<Date | null>(g.valid_until ? fromDateString(g.valid_until) : null);
  const [reason, setReason] = useState("");
  const save = useMutation({ mutationFn: () => api(`/api/guarantees/${g.id}/status`, { method: "POST", body: { status, on_date: on ? toDateString(on) : null,
    valid_until: valid && ["issued", "extended"].includes(status) ? toDateString(valid) : null, reason: reason.trim() || null } }), onSuccess: () => { onDone(); onClose(); } });
  return (
    <Modal open title={t(`tenders.guarantee.steps.${status}`)} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={save.isPending} data-testid="status-save" onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="status-dialog">
        <Field label={t("tenders.guarantee.onDate")} htmlFor="gs-on"><DateInput id="gs-on" value={on} onChange={setOn} /></Field>
        {["issued", "extended"].includes(status) && <Field label={t("tenders.guarantee.validUntil")} htmlFor="gs-valid"><DateInput id="gs-valid" value={valid} onChange={setValid} /></Field>}
        <Field label={t("tenders.guarantee.reason")} htmlFor="gs-reason"><Input id="gs-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

function GuaranteesCard({ d, caseData }: { d: TenderDetail; caseData: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["tender", caseData.id] });
  const [form, setForm] = useState<Partial<GuaranteeRow> | null>(null);
  const [step, setStep] = useState<{ g: GuaranteeRow; status: string } | null>(null);
  const save = useMutation({
    mutationFn: (b: Body) => b.id ? api(`/api/guarantees/${b.id}`, { method: "PATCH", body: Object.fromEntries(Object.entries(b).filter(([k]) =>
      ["purpose", "form", "amount", "amount_currency", "bank_name", "branch", "number", "valid_until", "fee", "blocked_deposit", "description"].includes(k))) })
      : api("/api/guarantees", { method: "POST", body: { ...b, case_id: caseData.id, tender_id: d.id } }),
    onSuccess: () => { refresh(); setForm(null); },
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/guarantees/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const tied = Object.entries(d.tied_up);
  return (
    <Card padded={false} title={t("tenders.guarantee.title")} actions={<Button icon="plus" onClick={() => setForm({})} data-testid="add-guarantee">{t("tenders.guarantee.add")}</Button>}>
      {d.guarantees.length === 0 ? <EmptyState>{t("tenders.guarantee.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid="guarantees">{d.guarantees.map((g) => (
          <li key={g.id} className="flex flex-col gap-1 px-4 py-2 text-sm" data-guarantee={g.id}>
            <span className="flex flex-wrap items-center gap-2">
              <b>{t(`tenders.guarantee.purposes.${g.purpose}`)}</b>
              <Badge tone={STATUS_TONE[g.status] ?? "neutral"}>{t(`tenders.guarantee.statuses.${g.status}`)}</Badge>
              <Money amount={g.amount} currency={g.amount_currency} />
              {g.bank_name && <span dir="auto">{g.bank_name}</span>}{g.number && <Bdi ltr className="font-mono text-xs">{g.number}</Bdi>}
              {g.valid_until && <span className="inline-flex items-center gap-1 text-xs">{t("tenders.guarantee.validUntil")}: <span className="tabular-nums">{f.day(g.valid_until)}</span></span>}
            </span>
            {g.coverage && <span className="text-xs text-danger" role="alert">{t("tenders.blockers.guarantee_validity_short", { valid: f.day(g.coverage.valid_until), needed: f.day(g.coverage.needed_until) })}</span>}
            {g.reminders.length > 0 && <span className="text-xs text-muted">{g.reminders.map((r) => `${t(`tenders.reminders.${r.purpose}`)} ${f.day(r.due_on)}`).join("، ")}</span>}
            <span className="flex flex-wrap gap-1">
              {nextGuaranteeSteps(g.status).map((s) => <Button key={s} variant="ghost" onClick={() => setStep({ g, status: s })}>{t(`tenders.guarantee.steps.${s}`)}</Button>)}
              <Button variant="ghost" onClick={() => setForm(g)}>{t("common.edit")}</Button>
              {["to_request", "requested"].includes(g.status) && <Button variant="ghost" onClick={() => remove.mutate(g.id)}>{t("common.remove")}</Button>}
            </span>
            {g.history.length > 1 && <details className="text-xs"><summary className="cursor-pointer text-muted">{t("tenders.guarantee.history")}</summary>
              <ul>{g.history.map((h) => <li key={h.id}><span className="tabular-nums">{f.day(h.on_date)}</span> · {t(`tenders.guarantee.statuses.${h.new_status ?? "to_request"}`)}{h.valid_until ? ` · ${f.day(h.valid_until)}` : ""}{h.reason ? ` · ${h.reason}` : ""}</li>)}</ul></details>}
          </li>))}</ul>
      )}
      {tied.length > 0 && <p className="border-t border-line px-4 py-2 text-xs text-muted" data-testid="tied-up">{t("tenders.guarantee.tiedUp")}: {tied.map(([cur, v]) => `${f.num(v.total)} ${cur}`).join("، ")}</p>}
      <ErrorNote error={remove.error} />
      {form && <GuaranteeForm initial={form} busy={save.isPending} error={save.error} onClose={() => setForm(null)} onSave={(b) => save.mutate(b)} />}
      {step && <StatusDialog g={step.g} status={step.status} onClose={() => setStep(null)} onDone={refresh} />}
    </Card>
  );
}

// ---- costs and the financial proposal ---------------------------------------------------------------------------------

function CostsCard({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ kind: "documents_purchase", amount: "", paid: true });
  const toSheet = useMutation({ mutationFn: () => api(`/api/tenders/${d.id}/costs/to-sheet`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["costing"] }) });
  const known = toSheet.error instanceof ApiError && ["no_draft_sheet", "nothing_to_add"].includes(toSheet.error.code) ? toSheet.error.code : null;
  return (
    <Card padded={false} title={t("tenders.costs.title")} actions={<Button variant="ghost" busy={toSheet.isPending} onClick={() => toSheet.mutate()} data-testid="costs-to-sheet">{t("tenders.costs.toSheet")}</Button>}>
      {d.costs.length === 0 ? <EmptyState>{t("tenders.costs.none")}</EmptyState> : (
        <ul className="divide-y divide-line" data-testid="tender-costs">{d.costs.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2 px-4 py-1.5 text-sm">
            <span className="flex-1">{t(`tenders.costs.kinds.${c.kind}`)}{c.note && <span className="ms-2 text-xs text-muted" dir="auto">{c.note}</span>}</span>
            <Money amount={c.amount} currency={c.amount_currency} />
            {c.refundable && <Badge tone={c.refunded_on ? "success" : "warning"}>{c.refunded_on ? t("tenders.costs.refunded") : t("tenders.costs.refundable")}</Badge>}
            {c.paid_on ? <span className="text-xs tabular-nums text-muted">{f.day(c.paid_on)}</span>
              : <Button variant="ghost" onClick={() => run(`/api/tender-costs/${c.id}`, { paid_on: toDateString(new Date()) }, "PATCH")}>{t("tenders.costs.markPaid")}</Button>}
            {c.refundable && c.paid_on && !c.refunded_on && <Button variant="ghost" onClick={() => run(`/api/tender-costs/${c.id}`, { refunded_on: toDateString(new Date()) }, "PATCH")}>{t("tenders.costs.markRefunded")}</Button>}
            <Button variant="ghost" aria-label={t("common.remove")} onClick={() => run(`/api/tender-costs/${c.id}`, undefined, "DELETE")}>✕</Button>
          </li>))}</ul>
      )}
      <div className="border-t border-line px-4 py-2 text-xs" data-testid="cost-totals">
        {Object.entries(d.cost_totals).map(([cur, v]) => <p key={cur}>{t("tenders.costs.totals", { spent: f.num(v.spent), out: f.num(v.refundable_outstanding), net: f.num(v.net), cur })}</p>)}
      </div>
      <div className="flex flex-wrap items-end gap-2 border-t border-line px-4 py-2">
        <Select aria-label={t("tenders.costs.kind")} className="w-auto" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {["documents_purchase", "guarantee_fee", "deposit", "travel", "other"].map((k) => <option key={k} value={k}>{t(`tenders.costs.kinds.${k}`)}</option>)}</Select>
        <Input dir="ltr" inputMode="decimal" aria-label={t("tenders.costs.amount")} placeholder={t("tenders.costs.amount")} className="w-36" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
        <Checkbox label={t("tenders.costs.paid")} checked={form.paid} onChange={(v) => setForm({ ...form, paid: v })} />
        <Button disabled={!Number(form.amount)} onClick={() => { run(`/api/tenders/${d.id}/costs`, { kind: form.kind, amount: form.amount, paid_on: form.paid ? toDateString(new Date()) : null }); setForm({ ...form, amount: "" }); }}>{t("common.add")}</Button>
      </div>
      {known ? <p className="px-4 pb-2 text-xs text-warning" role="status">{t(known === "no_draft_sheet" ? "tenders.costs.noDraft" : "tenders.costs.nothingToAdd")}</p> : <ErrorNote error={toSheet.error} />}
      {toSheet.isSuccess && <p className="px-4 pb-2 text-xs text-success">{t("tenders.costs.added")}</p>}
    </Card>
  );
}

function ProposalCard({ d, caseId }: { d: TenderDetail; caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["tender", caseId] });
  const create = useMutation({ mutationFn: () => api<ProposalRow>(`/api/tenders/${d.id}/proposals`, { method: "POST", body: {} }), onSuccess: refresh });
  const p = d.proposals.find((x) => x.status !== "superseded") ?? d.proposals[0];
  if (d.financial_mode === "letterhead") {
    return <Card title={t("tenders.proposal.title")}><p className="text-sm">{t("tenders.proposal.letterhead")} <Link className="text-accent hover:underline" to={`/cases/${caseId}?tab=quotes`}>{t("tenders.proposal.toQuotes")}</Link></p></Card>;
  }
  return (
    <Card title={t("tenders.proposal.title")} actions={<Button busy={create.isPending} onClick={() => create.mutate()} data-testid="new-proposal">{p ? t("tenders.proposal.newVersion") : t("tenders.proposal.create")}</Button>}>
      <ErrorNote error={create.error} />
      {p ? <ProposalView p={p} onChanged={refresh} /> : <p className="text-sm text-muted">{t("tenders.proposal.none")}</p>}
      {d.proposals.length > 1 && <p className="mt-2 text-xs text-muted">{t("tenders.proposal.versions", { n: f.num(d.proposals.length) })}</p>}
    </Card>
  );
}

function ProposalView({ p, onChanged }: { p: ProposalRow; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [reason, setReason] = useState("");
  const draft = p.status === "draft";
  const line = useMutation({ mutationFn: ({ id, price }: { id: string; price: string }) => api(`/api/tender-proposal-lines/${id}`, { method: "PATCH", body: { unit_price: price } }), onSuccess: onChanged });
  const approve = useMutation({ mutationFn: (withReason: boolean) => api(`/api/tender-proposals/${p.id}/approve`, { method: "POST", body: withReason ? { confirm_below_cost: true, reason } : {} }), onSuccess: onChanged });
  const output = useMutation({ mutationFn: (format: string) => api<{ document_id: string }>(`/api/tender-proposals/${p.id}/outputs`, { method: "POST", body: { format } }),
    onSuccess: (out) => { onChanged(); window.location.assign(`/api/documents/${out.document_id}/download`); } });
  const belowCost = approve.error instanceof ApiError && approve.error.code === "below_cost";
  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="proposal">
      <p className="flex flex-wrap items-center gap-2">{t("tenders.proposal.version", { n: f.num(p.version) })}
        <Badge tone={p.status === "approved" ? "success" : "warning"}>{t(`tenders.proposal.statuses.${p.status}`)}</Badge>
        {p.valid_until && <span className="text-xs">{t("tenders.proposal.validUntil")}: <span className="tabular-nums">{f.day(p.valid_until)}</span></span>}</p>
      <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="text-muted"><th className="p-1 text-start">{t("tenders.proposal.item")}</th>
        <th className="p-1 text-start">{t("tenders.proposal.qty")}</th><th className="p-1 text-start">{t("tenders.proposal.unitPrice")}</th><th className="p-1 text-start">{t("tenders.proposal.total")}</th></tr></thead>
        <tbody>{p.lines.map((x) => (
          <tr key={x.id} className="border-t border-line"><td className="p-1" dir="auto">{x.name}</td><td className="p-1 tabular-nums">{f.num(x.quantity)} {x.unit_text ?? x.unit_code ?? ""}</td>
            <td className="p-1">{draft ? <Input dir="ltr" className="w-36" aria-label={`${t("tenders.proposal.unitPrice")} ${x.name}`} defaultValue={Number(x.unit_price).toFixed(p.decimals)}
              onBlur={(e) => e.target.value && Number(e.target.value) !== Number(x.unit_price) && line.mutate({ id: x.id, price: e.target.value })} /> : <Money amount={x.unit_price} currency={p.currency} />}</td>
            <td className="p-1"><Money amount={x.total} currency={p.currency} /></td></tr>))}</tbody></table></div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5" data-testid="proposal-totals">
        <dt className="text-muted">{t("tenders.proposal.beforeVat")}</dt><dd><Money amount={p.subtotal} currency={p.currency} /></dd>
        <dt className="text-muted">{t("tenders.proposal.vat")}</dt><dd><Money amount={p.vat_amount} currency={p.currency} /></dd>
        <dt className="font-medium">{t("tenders.proposal.withVat")}</dt><dd className="font-semibold"><Money amount={p.total} currency={p.currency} /></dd>
        <dt className="text-muted">{t("tenders.proposal.inWords")}</dt><dd dir="rtl">{p.words}</dd>
      </dl>
      <span className="flex flex-wrap gap-1.5">
        <a className="inline-flex h-8 items-center rounded-md border border-line-strong px-3 text-sm hover:bg-surface-2" href={`/api/tender-proposals/${p.id}/print`} target="_blank" rel="noreferrer">{t("quotes.printView")}</a>
        <Button icon="download" busy={output.isPending && output.variables === "pdf"} onClick={() => output.mutate("pdf")}>PDF</Button>
        <Button icon="download" busy={output.isPending && output.variables === "docx"} onClick={() => output.mutate("docx")}>Word</Button>
        {draft && <Button variant="primary" busy={approve.isPending} onClick={() => approve.mutate(false)} data-testid="approve-proposal">{t("tenders.proposal.approve")}</Button>}
      </span>
      {belowCost && (
        <div className="flex flex-col gap-1.5 rounded-md bg-warning-soft p-2 text-warning" role="alert">
          <span>{t("tenders.proposal.belowCost")}</span>
          <Input dir="auto" aria-label={t("tenders.proposal.reason")} placeholder={t("tenders.proposal.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
          <span><Button variant="danger" disabled={!reason.trim()} onClick={() => approve.mutate(true)}>{t("tenders.proposal.approveAnyway")}</Button></span>
        </div>
      )}
      <ErrorNote error={(belowCost ? null : approve.error) || line.error || output.error} />
    </div>
  );
}

// ---- submission and result -----------------------------------------------------------------------------------------------

function SubmitAndResult({ d, run }: { d: TenderDetail; run: Run }) {
  const { t } = useTranslation();
  const f = useFormat();
  const reasons = useQuery({ queryKey: ["tender-result-reasons"], queryFn: () => api<ResultReasonRow[]>("/api/tender-result-reasons") });
  const [submit, setSubmit] = useState({ channel: "setad", note: "", override: "" });
  const [res, setRes] = useState({ result: d.result ?? "won", result_reason: d.result_reason ?? "", winner_name: d.winner_name ?? "", winner_price: d.winner_price ?? "",
    our_rank: d.our_rank ? String(d.our_rank) : "", result_note: d.result_note ?? "", case_status: "" });
  const blocked = d.blockers.length > 0;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title={<span className="flex items-center gap-2">{t("tenders.submit.title")}{d.submitted_at && <Badge tone="success">{t("tenders.submit.done", { at: f.date(d.submitted_at, true) })}</Badge>}</span>}>
        <BlockerList blockers={d.blockers} />
        {!d.submitted_at && !d.result && <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            <Select aria-label={t("tenders.submit.channel")} className="w-auto" value={submit.channel} onChange={(e) => setSubmit({ ...submit, channel: e.target.value })}>
              {["setad", "in_person", "post", "other"].map((c) => <option key={c} value={c}>{t(`tenders.submit.channels.${c}`)}</option>)}</Select>
            <Input dir="auto" aria-label={t("tenders.submit.note")} placeholder={t("tenders.submit.note")} value={submit.note} onChange={(e) => setSubmit({ ...submit, note: e.target.value })} />
          </div>
          {blocked && <Input dir="auto" aria-label={t("tenders.submit.override")} placeholder={t("tenders.submit.override")} value={submit.override} onChange={(e) => setSubmit({ ...submit, override: e.target.value })} />}
          <span><Button variant="primary" data-testid="mark-submitted" disabled={blocked && !submit.override.trim()}
            onClick={() => run(`/api/tenders/${d.id}/submit`, { channel: submit.channel, note: submit.note || null, override_reason: submit.override.trim() || null })}>{t("tenders.submit.button")}</Button></span>
        </div>}
        {d.submit_override_reason && <p className="mt-2 text-xs text-warning">{t("tenders.submit.overridden", { reason: d.submit_override_reason })}</p>}
      </Card>
      <Card title={<span className="flex items-center gap-2">{t("tenders.result.title")}{d.result && <Badge tone={d.result === "won" ? "success" : "neutral"}>{t(`tenders.result.results.${d.result}`)}</Badge>}</span>}>
        <div className="grid gap-2 sm:grid-cols-2" data-testid="result-form">
          <Field label={t("tenders.result.result")} htmlFor="tr-result"><Select id="tr-result" value={res.result} onChange={(e) => setRes({ ...res, result: e.target.value as typeof res.result })}>
            {["won", "lost", "cancelled", "no_result"].map((r) => <option key={r} value={r}>{t(`tenders.result.results.${r}`)}</option>)}</Select></Field>
          <Field label={t("tenders.result.reason")} htmlFor="tr-reason"><Select id="tr-reason" value={res.result_reason} onChange={(e) => setRes({ ...res, result_reason: e.target.value })}>
            <option value="">—</option>{(reasons.data ?? []).map((r) => <option key={r.code} value={r.code}>{f.lang === "fa" ? r.label_fa : r.label_en}</option>)}</Select></Field>
          <Field label={t("tenders.result.winner")} htmlFor="tr-winner"><Input id="tr-winner" dir="auto" value={res.winner_name} onChange={(e) => setRes({ ...res, winner_name: e.target.value })} /></Field>
          <Field label={t("tenders.result.winnerPrice")} htmlFor="tr-price"><Input id="tr-price" dir="ltr" inputMode="decimal" value={res.winner_price} onChange={(e) => setRes({ ...res, winner_price: e.target.value })} /></Field>
          <Field label={t("tenders.result.rank")} htmlFor="tr-rank"><Input id="tr-rank" dir="ltr" inputMode="numeric" value={res.our_rank} onChange={(e) => setRes({ ...res, our_rank: e.target.value })} /></Field>
          {(res.result === "cancelled" || res.result === "no_result") && <Field label={t("tenders.result.caseStatus")} htmlFor="tr-case">
            <Select id="tr-case" value={res.case_status} onChange={(e) => setRes({ ...res, case_status: e.target.value })}>
              <option value="">{t(res.result === "cancelled" ? "tenders.result.caseDefaultCancelled" : "tenders.result.caseDefaultLost")}</option>
              {["lost", "cancelled", "open"].map((s) => <option key={s} value={s}>{t(`sourcing.status.case.${s}`)}</option>)}</Select></Field>}
          <Field label={t("tenders.result.note")} htmlFor="tr-note"><Input id="tr-note" dir="auto" value={res.result_note} onChange={(e) => setRes({ ...res, result_note: e.target.value })} /></Field>
        </div>
        <Button className="mt-2" variant="primary" data-testid="save-result" disabled={res.result === "lost" && !res.result_reason}
          onClick={() => run(`/api/tenders/${d.id}/result`, { result: res.result, result_reason: res.result_reason || null, winner_name: res.winner_name || null,
            winner_price: res.winner_price || null, our_rank: res.our_rank ? Number(res.our_rank) : null, result_note: res.result_note || null,
            case_status: res.case_status || null })}>{d.result ? t("tenders.result.revise") : t("tenders.result.save")}</Button>
        {d.other_reminders.length > 0 && <p className="mt-2 text-xs text-muted" data-testid="result-followups">{d.other_reminders.map((r) => `${t(`tenders.reminders.${r.purpose}`)} ${f.day(r.due_on)}`).join("، ")}</p>}
        {d.guarantees.flatMap((g) => g.reminders.filter((r) => r.purpose === "guarantee_release").map((r) =>
          <p key={r.id} className="mt-1 text-xs text-warning" data-testid="release-followup">{r.action} · {f.day(r.due_on)}</p>))}
      </Card>
    </div>
  );
}

// ---- small presentational parts (exported for the unit tests) ---------------------------------------------------------

export function TenderStepper({ stage, hint, onPick }: { stage: TenderStage; hint: TenderStage; onPick?: (stage: TenderStage) => void }) {
  const { t } = useTranslation();
  return (
    <ol className="mb-3 flex flex-wrap gap-1" data-testid="tender-stepper">
      {stepper(stage, hint).map((s) => (
        <li key={s.stage} data-state={s.state} data-hinted={s.hinted || undefined}>
          <button type="button" aria-current={s.state === "current" ? "step" : undefined} onClick={() => onPick?.(s.stage)}
            className={`rounded-full border px-2.5 py-1 text-xs ${s.state === "current" ? "border-accent bg-accent-bright text-accent-fg" : s.state === "done" ? "border-success text-success" : "border-line text-muted hover:bg-surface-2"} ${s.hinted ? "ring-2 ring-warning" : ""}`}
            title={s.hinted ? t("tenders.stageHint") : undefined}>{t(`tenders.stages.${s.stage}`)}</button>
        </li>
      ))}
    </ol>
  );
}

export function BlockerList({ blockers }: { blockers: Blocker[] }) {
  const { t } = useTranslation();
  return (
    <ul className="mb-3 flex flex-col gap-1 text-sm" data-testid="blockers">
      {blockers.length === 0 ? <li className="text-success">✓ {t("tenders.submit.ready")}</li> : blockers.map((b) => {
        const m = blockerMessage(b);
        return <li key={b.code} data-code={b.code} className="flex items-start gap-2"><span aria-hidden className="text-danger">✗</span>{t(m.key, m.values)}</li>;
      })}
    </ul>
  );
}

export function EnvelopeProgressBadge({ p, num, long }: { p: [number, number]; num: (n: number) => string; long?: boolean }) {
  const { t } = useTranslation();
  const x = progressText(p);
  return <span data-complete={x.complete}><Badge tone={x.complete ? "success" : "neutral"}>
    {long ? t("tenders.envelopes.progress", { done: num(x.done), total: num(x.total) }) : `${num(x.done)}/${num(x.total)}`}</Badge></span>;
}

export function Section({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-4">{children}</div>;
}
