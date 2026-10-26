/** RFQ builder and collapsible RFQ cards: per-recipient text (editable while draft), copy, mailto, mark as sent, decline, xlsx. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, Input, Modal, Select, Spinner, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import { personName, rfqDefaultOpen, sortRfqs } from "../../lib/sourcing";
import type { CaseDetail, Rfq, RfqRecipient, SupplierChoice } from "../../lib/types";
import { DueDatePicker, PartyName, stageLabel } from "../parties/shared";
import { ContactName, RFQ_CHANNELS, StatusBadge, useInvalidateSourcing } from "../sourcing/shared";

const LANGS = ["en", "fa"];

interface RecipientDraft {
  party_id: string;
  name_fa: string | null;
  name_en: string | null;
  channel: string;
  language: string;
  stage: string | null;
}

function SupplierPicker({ itemIds, chosen, onAdd }: { itemIds: string[]; chosen: RecipientDraft[]; onAdd: (s: SupplierChoice) => void }) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const list = useQuery({
    queryKey: ["rfqs", "suppliers", q],
    queryFn: () => api<SupplierChoice[]>("/api/rfqs/suppliers", { query: { q, page_size: 30 } }),
  });
  const suggestions = useQuery({
    queryKey: ["rfqs", "suggestions", itemIds, chosen.map((c) => c.party_id)],
    queryFn: () => api<SupplierChoice[]>("/api/rfqs/supplier-suggestions", { query: { item_ids: itemIds, exclude: chosen.map((c) => c.party_id) } }),
    enabled: itemIds.length > 0,
  });
  const taken = new Set(chosen.map((c) => c.party_id));
  const row = (s: SupplierChoice, hint?: string) => (
    <li key={s.party_id} className="flex flex-wrap items-center gap-2 px-2.5 py-1.5 text-sm">
      <PartyName fa={s.name_fa} en={s.name_en} dnc={s.do_not_contact} />
      {s.country_iso2 && <Bdi ltr className="font-mono text-xs text-muted">{s.country_iso2}</Bdi>}
      {s.supplier_stage && <Badge>{stageLabel(t, "supplier", s.supplier_stage)}</Badge>}
      {hint && <Badge tone="accent">{hint}</Badge>}
      <Button className="ms-auto" icon="plus" disabled={taken.has(s.party_id) || s.do_not_contact} onClick={() => onAdd(s)}>{t("common.add")}</Button>
    </li>
  );
  return (
    <div className="flex flex-col gap-2">
      {(suggestions.data ?? []).length > 0 && (
        <div className="rounded-md border border-line">
          <p className="border-b border-line bg-surface-2 px-2.5 py-1 text-xs text-muted">{t("sourcing.rfq.suggestions")}</p>
          <ul className="divide-y divide-line">
            {suggestions.data!.map((s) => row(s, `${t(`sourcing.rfq.match.${s.match}`)} ${(s.codes ?? []).join(", ")}`))}
          </ul>
        </div>
      )}
      <Input type="search" placeholder={t("sourcing.rfq.searchSuppliers")} value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="max-h-48 divide-y divide-line overflow-y-auto rounded-md border border-line">
        {list.isFetching && <li className="p-2"><Spinner size={14} /></li>}
        {(list.data ?? []).map((s) => row(s))}
        {list.data && list.data.length === 0 && <li className="p-2 text-sm text-muted">{t("sourcing.rfq.noSuppliers")}</li>}
      </ul>
      <p className="text-xs text-muted">{t("sourcing.rfq.supplierHint")}</p>
    </div>
  );
}

export function RfqBuilder({ caseData, rfqCount, onClose, onCreated }: { caseData: CaseDetail; rfqCount: number; onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation();
  const open = caseData.items.filter((i) => i.status !== "cancelled");
  const [itemIds, setItemIds] = useState<string[]>(open.filter((i) => i.status === "uncovered").map((i) => i.id));
  const [title, setTitle] = useState("");  // empty: the server names it "RFQ <n> - <first item>"
  const [respondBy, setRespondBy] = useState<string | null>(null);
  const [recipients, setRecipients] = useState<RecipientDraft[]>([]);
  const create = useMutation({
    mutationFn: () => api<Rfq>("/api/rfqs", {
      method: "POST",
      body: {
        case_id: caseData.id, title: title.trim() || null, respond_by: respondBy, items: itemIds.map((id) => ({ line_item_id: id })),
        recipients: recipients.map((r) => ({ party_id: r.party_id, channel: r.channel, language: r.language })),
      },
    }),
    onSuccess: () => { onCreated(); onClose(); },
  });
  return (
    <Modal open wide title={t("sourcing.rfq.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" busy={create.isPending} disabled={itemIds.length === 0} onClick={() => create.mutate()}>{t("sourcing.rfq.create")}</Button></>}>
      <div className="flex max-h-[68vh] flex-col gap-3 overflow-y-auto pe-1">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("sourcing.rfq.title")} htmlFor="rfq-title"><Input id="rfq-title" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder={`RFQ ${rfqCount + 1} - ${open.find((i) => itemIds.includes(i.id))?.name ?? caseData.title}`} /></Field>
          <Field label={t("sourcing.rfq.respondBy")} htmlFor="rfq-due">
            <DateInput id="rfq-due" value={respondBy ? fromDateString(respondBy) : null} onChange={(d) => setRespondBy(d ? toDateString(d) : null)} />
          </Field>
        </div>
        <Field label={t("sourcing.rfq.items")}>
          <ul className="flex flex-col gap-1 rounded-md border border-line p-2">
            {open.map((i) => (
              <li key={i.id} className="flex items-center gap-2 text-sm">
                <Checkbox label={<Bdi>{i.name}</Bdi>} checked={itemIds.includes(i.id)} onChange={(v) => setItemIds(v ? [...itemIds, i.id] : itemIds.filter((x) => x !== i.id))} />
                <StatusBadge group="item" status={i.status} />
                {i.hs_code && <Bdi ltr className="font-mono text-xs text-muted">HS {i.hs_code}</Bdi>}
              </li>
            ))}
          </ul>
        </Field>
        <Field label={t("sourcing.rfq.recipients")}>
          {recipients.length > 0 && (
            <ul className="mb-2 flex flex-col gap-1.5">
              {recipients.map((r, i) => (
                <li key={r.party_id} className="flex flex-wrap items-center gap-2 rounded-md bg-surface-2 px-2.5 py-1.5 text-sm">
                  <PartyName fa={r.name_fa} en={r.name_en} />
                  {r.stage && <Badge>{stageLabel(t, "supplier", r.stage)}</Badge>}
                  <span className="ms-auto flex flex-wrap gap-1.5">
                    <Select className="w-auto min-w-28" aria-label={t("sourcing.rfq.channel")} value={r.channel}
                      onChange={(e) => setRecipients(recipients.map((x, j) => (i === j ? { ...x, channel: e.target.value } : x)))}>
                      {RFQ_CHANNELS.map((c) => <option key={c} value={c}>{t(`sourcing.channels.${c}`)}</option>)}
                    </Select>
                    <Select className="w-auto min-w-28" aria-label={t("sourcing.rfq.language")} value={r.language}
                      onChange={(e) => setRecipients(recipients.map((x, j) => (i === j ? { ...x, language: e.target.value } : x)))}>
                      {LANGS.map((l) => <option key={l} value={l}>{t(`common.languageNames.${l}`)}</option>)}
                    </Select>
                    <Button variant="ghost" onClick={() => setRecipients(recipients.filter((_, j) => j !== i))}>{t("common.remove")}</Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <SupplierPicker itemIds={itemIds} chosen={recipients} onAdd={(s) => setRecipients([...recipients, {
            party_id: s.party_id, name_fa: s.name_fa, name_en: s.name_en, stage: s.supplier_stage ?? null,
            channel: s.channel ?? ((s.country_iso2 ?? "") === "IR" ? "whatsapp" : "email"),
            language: s.language ?? ((s.country_iso2 ?? "") === "IR" ? "fa" : "en"),
          }])} />
        </Field>
        <ErrorNote error={create.error} />
      </div>
    </Modal>
  );
}

/** v0.3.1: shows the follow-up that will be created (editable) or takes an explicit "no follow-up" reason. */
function MarkSentDialog({ recipient, rfq, onClose, onDone }: { recipient: RfqRecipient; rfq: Rfq; onClose: () => void; onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const [action, setAction] = useState(i18n.getFixedT(recipient.language)("sourcing.rfq.chaseAction"));
  const [due, setDue] = useState<string | null>(rfq.respond_by);
  const [skip, setSkip] = useState(false);
  const [reason, setReason] = useState("");
  const send = useMutation({
    mutationFn: () => api(`/api/rfqs/recipients/${recipient.id}/mark-sent`, {
      method: "POST", body: { message_text: recipient.message_text, subject: recipient.subject,
        ...(skip ? { no_followup_reason: reason.trim() } : { followup: { action, due_on: due } }) },
    }),
    onSuccess: () => { onDone(); onClose(); },
  });
  const ready = skip ? !!reason.trim() : !!action.trim() && !!due;
  return (
    <Modal open title={t("sourcing.rfq.markSent")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!ready} busy={send.isPending} onClick={() => send.mutate()}>{t("sourcing.rfq.markSent")}</Button></>}>
      <div className="flex flex-col gap-3">
        <p className="text-sm">{t("sourcing.rfq.markSentHint")}</p>
        {!skip && <>
          <p className="rounded-md bg-surface-2 px-2.5 py-1.5 text-sm" data-testid="ms-preview">
            {due ? t("sourcing.rfq.followupPreview", { action: action.trim() || "—", date: f.day(due) }) : t("sourcing.rfq.followupNeedsDate")}
          </p>
          <Field label={t("followups.action")} htmlFor="ms-action"><Input id="ms-action" dir="auto" value={action} onChange={(e) => setAction(e.target.value)} /></Field>
          <Field label={t("followups.newDue")} htmlFor="ms-due" hint={rfq.respond_by ? t("sourcing.rfq.dueFromRespondBy") : undefined}><DueDatePicker id="ms-due" value={due} onChange={setDue} /></Field>
        </>}
        <Checkbox label={t("sourcing.rfq.noFollowup")} checked={skip} onChange={setSkip} />
        {skip && <Field label={t("sourcing.reason")} htmlFor="ms-reason"><Input id="ms-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <ErrorNote error={send.error} />
      </div>
    </Modal>
  );
}

/** One recipient: a one-line summary that expands to the text. Draft text is editable; sent text is read-only. */
function RecipientRow({ recipient, rfq, onChanged }: { recipient: RfqRecipient; rfq: Rfq; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const [, setParams] = useSearchParams();
  const draft = recipient.status === "draft";
  const [open, setOpen] = useState(draft);
  const [text, setText] = useState(recipient.message_text ?? "");
  const [subject, setSubject] = useState(recipient.subject ?? "");
  const [sending, setSending] = useState(false);
  const dirty = text !== (recipient.message_text ?? "") || subject !== (recipient.subject ?? "");
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<RfqRecipient>(`/api/rfqs/recipients/${recipient.id}`, { method: "PATCH", body }),
    onSuccess: (r) => { setText(r.message_text ?? ""); setSubject(r.subject ?? ""); onChanged(); },
  });
  const decline = useMutation({ mutationFn: () => api(`/api/rfqs/recipients/${recipient.id}/decline`, { method: "POST", body: {} }), onSuccess: onChanged });
  const remove = useMutation({ mutationFn: () => api(`/api/rfqs/recipients/${recipient.id}`, { method: "DELETE" }), onSuccess: onChanged });
  const copy = async (value: string) => {
    try { await navigator.clipboard.writeText(value); toast(t("sourcing.rfq.copied"), "success"); } catch { toast(t("errors.generic"), "error"); }
  };
  const textDir = recipient.language === "fa" ? "rtl" : "ltr";
  const bodyId = `rcp-${recipient.id}`;
  const waiting = ["sent", "no_response"].includes(recipient.status);
  return (
    <li className="rounded-md border border-line" data-recipient={recipient.id}>
      <div className="flex flex-wrap items-center gap-2 px-2.5 py-1.5">
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 rounded text-start text-sm focus-visible:outline-2 focus-visible:outline-accent">
          <Icon name="chevron" size={14} className={`shrink-0 text-muted ${open ? "rotate-90" : "rtl:-scale-x-100"}`} />
          <Bdi className="font-medium">{personName(recipient.party_name_fa, recipient.party_name_en, f.lang)}</Bdi>
          <ContactName fa={recipient.contact_name_fa} en={recipient.contact_name_en} className="text-xs" />
          <Badge>{t(`sourcing.channels.${recipient.channel}`)}</Badge>
          <Badge>{t(`common.languageNames.${recipient.language}`)}</Badge>
          <StatusBadge group="recipient" status={recipient.status} />
          {recipient.sent_at && <span className="text-xs text-muted tabular-nums">{f.date(recipient.sent_at, true)}</span>}
        </button>
        {draft && rfq.status !== "cancelled" && <Button variant="primary" icon="check" onClick={() => setSending(true)}>{t("sourcing.rfq.markSent")}</Button>}
        {waiting && rfq.status !== "cancelled" && (
          <Button onClick={() => setParams({ tab: "offers", record: recipient.party_id })}>{t("sourcing.rfq.recordOffer")}</Button>
        )}
      </div>
      {open && (
        <div id={bodyId} className="border-t border-line p-2.5">
          {draft ? <>
            <div className="mb-2 flex flex-wrap gap-1">
              <Select className="w-auto min-w-28" aria-label={t("sourcing.rfq.channel")} value={recipient.channel} onChange={(e) => save.mutate({ channel: e.target.value })}>
                {RFQ_CHANNELS.map((c) => <option key={c} value={c}>{t(`sourcing.channels.${c}`)}</option>)}
              </Select>
              <Select className="w-auto min-w-28" aria-label={t("sourcing.rfq.language")} value={recipient.language} onChange={(e) => save.mutate({ language: e.target.value })}>
                {LANGS.map((l) => <option key={l} value={l}>{t(`common.languageNames.${l}`)}</option>)}
              </Select>
            </div>
            {recipient.channel === "email" && (
              <Input className="mb-2" dir={textDir} lang={recipient.language} aria-label={t("sourcing.rfq.subject")} value={subject} onChange={(e) => setSubject(e.target.value)} />
            )}
            {/* plaintext bidi: each line takes its own direction, as in WhatsApp and most mail apps */}
            <Textarea dir={textDir} lang={recipient.language} rows={8} className="text-xs [unicode-bidi:plaintext]" aria-label={t("sourcing.rfq.message")} value={text} onChange={(e) => setText(e.target.value)} />
          </> : <>
            <p className="mb-1 text-xs text-muted">{t("sourcing.rfq.textAsSent")}</p>
            {recipient.subject && <p className="mb-1 text-sm font-medium [unicode-bidi:plaintext]" dir={textDir} lang={recipient.language} data-testid="sent-subject">{recipient.subject}</p>}
            <pre className="max-h-64 overflow-y-auto rounded-md bg-surface-2 p-2 font-sans text-xs whitespace-pre-wrap [unicode-bidi:plaintext]" dir={textDir} lang={recipient.language}
              aria-label={t("sourcing.rfq.message")} data-testid="sent-text">{recipient.message_text}</pre>
          </>}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Button icon="list" onClick={() => void copy(text)}>{t("sourcing.rfq.copyText")}</Button>
            {recipient.channel === "email" && <Button onClick={() => void copy(subject)}>{t("sourcing.rfq.copySubject")}</Button>}
            {recipient.mailto && !dirty && <a href={recipient.mailto} className="inline-flex h-8 items-center rounded-md border border-line-strong px-3 text-sm hover:bg-surface-2">{t("sourcing.rfq.openMail")} <Bdi ltr className="ms-1 text-xs text-muted">{recipient.email}</Bdi></a>}
            {recipient.channel === "email" && !recipient.mailto && <span className="text-xs text-muted">{t("sourcing.rfq.noEmail")}</span>}
            {draft && dirty && <Button busy={save.isPending} onClick={() => save.mutate({ subject, message_text: text })}>{t("common.save")}</Button>}
            {draft && <Button variant="ghost" onClick={() => save.mutate({ rerender: true })}>{t("sourcing.rfq.rerender")}</Button>}
            {waiting && <Button variant="ghost" onClick={() => decline.mutate()}>{t("sourcing.rfq.declined")}</Button>}
            {draft && <Button variant="ghost" className="ms-auto" onClick={() => remove.mutate()}>{t("common.remove")}</Button>}
          </div>
          <ErrorNote error={save.error || decline.error || remove.error} />
        </div>
      )}
      {sending && <MarkSentDialog recipient={{ ...recipient, message_text: text, subject }} rfq={rfq} onClose={() => setSending(false)} onDone={onChanged} />}
    </li>
  );
}

function AddRecipient({ rfq, onAdded }: { rfq: Rfq; onAdded: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const add = useMutation({
    mutationFn: (s: SupplierChoice) => api(`/api/rfqs/${rfq.id}/recipients`, { method: "POST", body: { party_id: s.party_id } }),
    onSuccess: () => { setOpen(false); onAdded(); },
  });
  if (!open) return <Button icon="plus" onClick={() => setOpen(true)}>{t("sourcing.rfq.addRecipient")}</Button>;
  return (
    <div className="rounded-md border border-line p-2">
      <SupplierPicker itemIds={rfq.items.map((i) => i.line_item_id)}
        chosen={rfq.recipients.map((r) => ({ party_id: r.party_id, name_fa: r.party_name_fa, name_en: r.party_name_en, channel: r.channel, language: r.language, stage: null }))}
        onAdd={(s) => add.mutate(s)} />
      <ErrorNote error={add.error} />
    </div>
  );
}

/** "..." menu for the low-use actions of an RFQ card. */
function MoreMenu({ label, children }: { label: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label={label} title={label} onClick={() => setOpen(!open)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg">⋯</button>
      {open && (
        <div role="menu" className="absolute end-0 z-20 mt-1 flex min-w-40 flex-col rounded-md border border-line bg-surface py-1 shadow-lg">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

const MENU_ITEM = "px-3 py-1.5 text-start text-sm hover:bg-surface-2";

/** Collapsible RFQ card (v0.3.2): one summary line (title, status, items, respond-by, recipient chips). */
export function RfqCard({ rfq, open, onToggle, highlight, onChanged }: { rfq: Rfq; open: boolean; onToggle: () => void; highlight: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [, setParams] = useSearchParams();
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const [showItems, setShowItems] = useState(false);
  const [sendingOnly, setSendingOnly] = useState(false);
  const cancel = useMutation({ mutationFn: () => api(`/api/rfqs/${rfq.id}/cancel`, { method: "POST", body: { reason } }), onSuccess: () => { setCancelling(false); onChanged(); } });
  const remove = useMutation({ mutationFn: () => api(`/api/rfqs/${rfq.id}`, { method: "DELETE" }), onSuccess: onChanged });
  const drafts = rfq.recipients.filter((r) => r.status === "draft");
  const waiting = rfq.recipients.filter((r) => ["sent", "no_response"].includes(r.status));
  const live = rfq.status !== "cancelled";
  const bodyId = `rfq-${rfq.id}`;
  const mainAction = !live ? null : drafts.length > 0 ? (
    <Button variant="primary" icon="check" onClick={() => {
      // one draft recipient: open its dialog; several: show the card so each text can be checked and sent
      if (drafts.length === 1) { setSendingOnly(true); return; }
      if (!open) onToggle();
      requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-recipient="${drafts[0].id}"]`)?.scrollIntoView({ block: "center" }));
    }}>{t("sourcing.rfq.markSent")}{drafts.length > 1 ? ` (${f.num(drafts.length)})` : ""}</Button>
  ) : waiting.length > 0 ? (
    <Button onClick={() => setParams(waiting.length === 1 ? { tab: "offers", record: waiting[0].party_id } : { tab: "offers" })}>{t("sourcing.rfq.recordOffer")}</Button>
  ) : null;
  return (
    <section className={`rounded-lg border bg-surface ${highlight ? "border-accent" : "border-line"}`} data-rfq={rfq.id} data-open={open}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}
          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 rounded text-start focus-visible:outline-2 focus-visible:outline-accent">
          <Icon name="chevron" size={16} className={`shrink-0 text-muted ${open ? "rotate-90" : "rtl:-scale-x-100"}`} />
          <Bdi className="font-semibold">{rfq.title}</Bdi>
          <StatusBadge group="rfq" status={rfq.status} />
          <span className="text-xs text-muted">{t("sourcing.rfq.itemsCount", { count: rfq.items.length })}</span>
          {rfq.respond_by && <span className="text-xs text-muted">{t("sourcing.rfq.respondBy")}: <span className="tabular-nums">{f.day(rfq.respond_by)}</span></span>}
          {rfq.recipients.map((r) => (
            <span key={r.id} data-chip className="inline-flex max-w-full items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs">
              <Bdi className="truncate">{personName(r.party_name_fa, r.party_name_en, f.lang)}</Bdi>
              {(r.contact_name_fa || r.contact_name_en) && <span className="text-muted">· <Bdi>{personName(r.contact_name_fa, r.contact_name_en, f.lang)}</Bdi></span>}
              <span className={r.status === "replied" ? "text-success" : r.status === "draft" ? "text-muted" : r.status === "sent" ? "text-accent" : "text-danger"}>
                {r.status === "replied" ? "✓ " : ""}{t(`sourcing.status.recipient.${r.status}`)}
              </span>
            </span>
          ))}
        </button>
        {mainAction}
        <MoreMenu label={t("sourcing.rfq.more")}>{(close) => <>
          <a role="menuitem" className={MENU_ITEM} href={`/api/rfqs/${rfq.id}/export.xlsx?language=${f.lang}`} onClick={close}>{t("sourcing.rfq.exportXlsx")}</a>
          {live && <button type="button" role="menuitem" className={MENU_ITEM} onClick={() => { close(); setCancelling(true); }}>{t("sourcing.rfq.cancel")}</button>}
          {rfq.recipients.every((r) => r.status === "draft") && <button type="button" role="menuitem" className={`${MENU_ITEM} text-danger`} onClick={() => { close(); remove.mutate(); }}>{t("delete.button")}</button>}
        </>}</MoreMenu>
      </div>
      <ErrorNote error={remove.error} />
      {open && (
        <div id={bodyId} className="border-t border-line p-3">
          <button type="button" aria-expanded={showItems} onClick={() => setShowItems(!showItems)} className="mb-2 inline-flex items-center gap-1 text-sm text-accent hover:underline">
            <Icon name="chevron" size={13} className={showItems ? "rotate-90" : "rtl:-scale-x-100"} />{t("sourcing.rfq.itemsCount", { count: rfq.items.length })}
          </button>
          {showItems && <ul className="mb-2 flex flex-col gap-0.5 ps-5 text-sm">{rfq.items.map((i) => <li key={i.id}><Bdi>{i.line_item.name}</Bdi></li>)}</ul>}
          {rfq.recipients.length === 0 ? <EmptyState>{t("sourcing.rfq.noRecipients")}</EmptyState> : (
            <ul className="flex flex-col gap-2">{rfq.recipients.map((r) => <RecipientRow key={`${r.id}-${r.status}-${r.channel}-${r.language}`} recipient={r} rfq={rfq} onChanged={onChanged} />)}</ul>
          )}
          {live && <div className="mt-3"><AddRecipient rfq={rfq} onAdded={onChanged} /></div>}
        </div>
      )}
      {sendingOnly && drafts.length === 1 && <MarkSentDialog recipient={drafts[0]} rfq={rfq} onClose={() => setSendingOnly(false)} onDone={onChanged} />}
      {cancelling && (
        <Modal open title={t("sourcing.rfq.cancel")} onClose={() => setCancelling(false)}
          footer={<><Button onClick={() => setCancelling(false)}>{t("common.cancel")}</Button>
            <Button variant="danger" disabled={!reason.trim()} busy={cancel.isPending} onClick={() => cancel.mutate()}>{t("sourcing.rfq.cancel")}</Button></>}>
          <Field label={t("sourcing.reason")} htmlFor="rfq-cancel"><Input id="rfq-cancel" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <ErrorNote error={cancel.error} />
        </Modal>
      )}
    </section>
  );
}

function storedOpen(key: string): Record<string, boolean> {
  try { return JSON.parse(sessionStorage.getItem(key) ?? "{}") as Record<string, boolean>; } catch { return {}; }
}

export function RfqsTab({ caseData, highlight }: { caseData: CaseDetail; highlight: string | null }) {
  const { t } = useTranslation();
  const invalidate = useInvalidateSourcing();
  const [building, setBuilding] = useState(false);
  const storageKey = `boms.rfqOpen.${caseData.id}`;
  const [openState, setOpenState] = useState<Record<string, boolean>>(() => storedOpen(storageKey));
  const rfqs = useQuery({ queryKey: ["rfqs", caseData.id], queryFn: () => api<Rfq[]>("/api/rfqs", { query: { case_id: caseData.id } }) });
  const refresh = () => { void rfqs.refetch(); invalidate(); };
  const list = sortRfqs(rfqs.data ?? []);
  const isOpen = (r: Rfq) => openState[r.id] ?? (r.id === highlight || rfqDefaultOpen(r.status));
  const remember = (next: Record<string, boolean>) => {
    setOpenState(next);
    try { sessionStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* storage is a convenience only */ }
  };
  const setAll = (value: boolean) => remember(Object.fromEntries(list.map((r) => [r.id, value])));
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {list.length > 0 && <>
          <Button variant="ghost" onClick={() => setAll(true)}>{t("sourcing.rfq.expandAll")}</Button>
          <Button variant="ghost" onClick={() => setAll(false)}>{t("sourcing.rfq.collapseAll")}</Button>
        </>}
        <Button variant="primary" icon="plus" disabled={caseData.status !== "open"} onClick={() => setBuilding(true)}>{t("sourcing.rfq.new")}</Button>
      </div>
      <ErrorNote error={rfqs.error} />
      {list.length === 0 && !rfqs.isLoading && <Card><EmptyState>{t("sourcing.rfq.empty")}</EmptyState></Card>}
      {list.map((r) => <RfqCard key={r.id} rfq={r} open={isOpen(r)} onToggle={() => remember({ ...openState, [r.id]: !isOpen(r) })}
        highlight={r.id === highlight} onChanged={refresh} />)}
      {building && <RfqBuilder caseData={caseData} rfqCount={list.length} onClose={() => setBuilding(false)} onCreated={refresh} />}
    </div>
  );
}
