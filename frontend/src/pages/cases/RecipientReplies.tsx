/** v0.10.1 (0.4.6) the actions of an RFQ recipient that is waiting for a priced reply:
 * - «پاسخ بدون قیمت»: an incoming reply (pasted, or dropped as .eml) recorded on the case; the recipient becomes replied,
 *   declined or «سؤال پرسید» (with the date to follow up), and the open «پیگیری پاسخ RFQ» closes with a note;
 * - «پیگیری»: an AI chase draft that knows what was sent and when (with «دستور به هوش»), editable, opened in the mail
 *   client; «ارسال شد» records the chase on the case and reschedules the follow-up. BOMS sends nothing. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DraftMessageButton } from "../../components/AiActions";
import { EmlDrop, type EmlPreview } from "../../components/EmlIntake";
import { Badge, Button, buttonClass, ErrorNote, Field, Input, Modal, Segmented, Textarea } from "../../design/components";
import { api } from "../../lib/api";
import type { RfqRecipient } from "../../lib/types";
import { DueDatePicker } from "../parties/shared";

function useRefresh() {
  const qc = useQueryClient();
  return () => { for (const key of [["rfqs"], ["case-thread"], ["party"], ["command-center"], ["events"]]) void qc.invalidateQueries({ queryKey: key }); };
}

export function ReplyDialog({ recipient, onClose }: { recipient: RfqRecipient; onClose: () => void }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [kind, setKind] = useState<"replied" | "declined" | "question">("replied");
  const [body, setBody] = useState("");
  const [eml, setEml] = useState<EmlPreview | null>(null);
  const [due, setDue] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api(`/api/rfqs/recipients/${recipient.id}/reply`, { method: "POST", body: {
      kind, body: body.trim() || null, subject: eml?.subject ?? null, raw_document_id: eml?.document_id ?? null,
      occurred_at: eml?.date ?? null, contact_id: eml?.match.party_id === recipient.party_id ? eml?.match.contact_id ?? null : null,
      next_due_on: kind === "question" ? due : null } }),
    onSuccess: () => { refresh(); onClose(); },
  });
  return (
    <Modal open title={t("rfqReply.title")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" disabled={kind === "question" && !due} busy={save.isPending} onClick={() => save.mutate()} data-testid="reply-save">{t("common.save")}</Button>
    </>}>
      <div className="flex flex-col gap-3" data-testid="reply-dialog">
        <Segmented label={t("rfqReply.kind")} value={kind} onChange={(v) => setKind(v as typeof kind)}
          options={(["replied", "declined", "question"] as const).map((k) => ({ value: k, label: t(`rfqReply.kinds.${k}`) }))} />
        <EmlDrop compact onRead={(p) => { setEml(p); setBody(p.body); }} testId="reply-eml" />
        {eml && <p className="text-xs"><Badge icon="inbox">.eml</Badge> <bdi dir="auto">{eml.subject}</bdi></p>}
        <Field label={t("rfqReply.text")} htmlFor="reply-text"><Textarea id="reply-text" dir="auto" rows={5} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
        {kind === "question" && <Field label={t("rfqReply.nextDue")} htmlFor="reply-due"><DueDatePicker id="reply-due" value={due} onChange={setDue} /></Field>}
        <p className="text-xs text-muted">{t(kind === "question" ? "rfqReply.hintQuestion" : "rfqReply.hintClose")}</p>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

export function ChaseDialog({ recipient, onClose }: { recipient: RfqRecipient; onClose: () => void }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [subject, setSubject] = useState(recipient.subject ?? "");
  const [body, setBody] = useState("");
  const [mailto, setMailto] = useState<string | null>(null);
  const [due, setDue] = useState<string | null>(null);
  const sent = useMutation({
    mutationFn: () => api(`/api/rfqs/recipients/${recipient.id}/chase`, { method: "POST", body: { subject: subject || null, body: body || null, next_due_on: due } }),
    onSuccess: () => { refresh(); onClose(); },
  });
  const link = mailto ?? (recipient.email ? `mailto:${recipient.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}` : null);
  return (
    <Modal open size="lg" title={t("rfqChase.title")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" disabled={!due || !body.trim()} busy={sent.isPending} onClick={() => sent.mutate()} data-testid="chase-sent">{t("rfqChase.sent")}</Button>
    </>}>
      <div className="flex flex-col gap-3" data-testid="chase-dialog">
        <p className="text-sm text-muted">{t("rfqChase.hint", { count: recipient.chase_count ?? 0 })}</p>
        <div><DraftMessageButton target="rfq_chase" targetId={recipient.id} language={recipient.language}
          onCommitted={(r) => { if (r.subject) setSubject(String(r.subject)); if (r.body) setBody(String(r.body)); setMailto(r.mailto ? String(r.mailto) : null); }} /></div>
        <Field label={t("sourcing.rfq.subject")} htmlFor="chase-subject"><Input id="chase-subject" dir={recipient.language === "fa" ? "rtl" : "ltr"} value={subject} onChange={(e) => { setSubject(e.target.value); setMailto(null); }} /></Field>
        <Field label={t("sourcing.rfq.message")} htmlFor="chase-body"><Textarea id="chase-body" dir={recipient.language === "fa" ? "rtl" : "ltr"} rows={6} value={body}
          onChange={(e) => { setBody(e.target.value); setMailto(null); }} data-testid="chase-body" /></Field>
        {link && <div><a href={link} className={buttonClass("secondary")} data-testid="chase-mailto">{t("sourcing.rfq.openMail")}</a></div>}
        <Field label={t("rfqChase.nextDue")} htmlFor="chase-due"><DueDatePicker id="chase-due" value={due} onChange={setDue} /></Field>
        <ErrorNote error={sent.error} />
      </div>
    </Modal>
  );
}

/** v0.10.1 (0.4.6) «پیگیری» of a sent quote: the AI chase draft, the mail client, then «ارسال شد». */
export function QuoteChaseDialog({ quoteId, language, email, onClose }: { quoteId: string; language: string; email?: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [due, setDue] = useState<string | null>(null);
  const sent = useMutation({
    mutationFn: () => api(`/api/quotes/${quoteId}/chase`, { method: "POST", body: { subject: subject || null, body: body || null, next_due_on: due } }),
    onSuccess: () => { for (const key of [["case-quotes"], ["case-thread"], ["command-center"]]) void qc.invalidateQueries({ queryKey: key }); onClose(); },
  });
  const link = `mailto:${email ?? ""}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  return (
    <Modal open size="lg" title={t("rfqChase.quoteTitle")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" disabled={!due || !body.trim()} busy={sent.isPending} onClick={() => sent.mutate()} data-testid="quote-chase-sent">{t("rfqChase.sent")}</Button>
    </>}>
      <div className="flex flex-col gap-3">
        <div><DraftMessageButton target="quote_chase" targetId={quoteId} language={language}
          onCommitted={(r) => { if (r.subject) setSubject(String(r.subject)); if (r.body) setBody(String(r.body)); }} /></div>
        <Field label={t("sourcing.rfq.subject")} htmlFor="qchase-subject"><Input id="qchase-subject" dir="auto" value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
        <Field label={t("sourcing.rfq.message")} htmlFor="qchase-body"><Textarea id="qchase-body" dir="auto" rows={6} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
        <div><a href={link} className={buttonClass("secondary")}>{t("sourcing.rfq.openMail")}</a></div>
        <Field label={t("rfqChase.nextDue")} htmlFor="qchase-due"><DueDatePicker id="qchase-due" value={due} onChange={setDue} /></Field>
        <ErrorNote error={sent.error} />
      </div>
    </Modal>
  );
}
