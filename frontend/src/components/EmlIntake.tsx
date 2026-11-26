/** v0.10.1 (0.4.6): an e-mail saved as .eml becomes an interaction on the case.
 * - `readEml(file)`: uploads the file to the document store and reads it (from, date, subject, text, attachments, and
 *   what «[CODE]» and the sender's address match). Nothing is recorded yet.
 * - `EmlDialog`: shows that for confirmation and records it (POST /api/interactions/eml); an unknown sender can be
 *   added to the party's contacts. A .msg is refused with how to save the message as .eml.
 * No mailbox is opened and nothing is sent: the owner saves the message from his mail client and drops it here. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Bdi, Button, Checkbox, ErrorNote, Field, FileDrop, Input, Modal } from "../design/components";
import { api, ApiError } from "../lib/api";
import { useFormat } from "../lib/prefs";
import type { DocumentDetail, Party } from "../lib/types";
import { FileType } from "./FileType";
import { PartyField } from "./fields";
import { DueDatePicker } from "../pages/parties/shared";

export interface EmlMatch { case_id: string | null; ref_type: string | null; ref_id: string | null; code: string | null; code_kind: string | null;
  party_id: string | null; contact_id: string | null; contact_name_fa: string | null; contact_name_en: string | null; known_sender: boolean }
export interface EmlPreview { document_id: string; from_name: string | null; from_address: string | null; to: string[]; cc: string[]; date: string | null;
  subject: string | null; body: string; body_kind: string | null; codes: string[];
  attachments: { filename: string; content_type: string; size: number }[]; match: EmlMatch }

/** Uploads an .eml (an already stored one is reused) and reads it. Throws ApiError `msg_not_supported` for a .msg. */
export async function readEml(file: File): Promise<EmlPreview> {
  const form = new FormData();
  form.append("file", file);
  let id: string;
  try {
    id = (await api<DocumentDetail>("/api/documents", { method: "POST", form })).id;
  } catch (err) {
    if (err instanceof ApiError && err.code === "duplicate_document") id = String(err.details.id);
    else throw err;
  }
  return api<EmlPreview>("/api/interactions/eml/preview", { method: "POST", body: { document_id: id } });
}

/** The «.msg» refusal reads as steps, not as an error code. */
export function EmlError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error instanceof ApiError && error.code === "msg_not_supported") {
    return (
      <div className="rounded-xl border border-warning-line bg-warning-soft p-3 text-sm" role="alert" data-testid="msg-refused">
        <p className="font-medium">{t("eml.msgTitle")}</p>
        <ul className="mt-1 list-disc ps-5"><li>{t("eml.msgGmail")}</li><li>{t("eml.msgOutlook")}</li></ul>
      </div>
    );
  }
  return <ErrorNote error={error} />;
}

/** A drop zone for one .eml; calls `onRead` with what it says. */
export function EmlDrop({ onRead, compact, testId = "eml-drop" }: { onRead: (p: EmlPreview) => void; compact?: boolean; testId?: string }) {
  const { t } = useTranslation();
  const [error, setError] = useState<unknown>(null);
  const read = useMutation({ mutationFn: (file: File) => readEml(file), onSuccess: (p) => { setError(null); onRead(p); }, onError: setError });
  return (
    <div className="flex flex-col gap-2">
      <FileDrop compact={compact} multiple={false} accept=".eml,.msg,message/rfc822" busy={read.isPending} testId={testId}
        label={t("eml.drop")} hint={t("eml.dropHint")} onFiles={(files) => files[0] && read.mutate(files[0])} />
      <EmlError error={error} />
    </div>
  );
}

/** What the e-mail says and what it matches; the owner confirms and it is recorded on the case. */
export function EmlDialog({ preview, fixed, onClose, onRecorded }: {
  preview: EmlPreview;
  /** context the dialog was opened from (a case, an RFQ recipient): it wins over the subject's code */
  fixed?: { caseId?: string | null; refType?: string | null; refId?: string | null; partyId?: string | null };
  onClose: () => void; onRecorded?: (interactionId: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const m = preview.match;
  const [party, setParty] = useState<Party | null>(null);
  const partyId = fixed?.partyId ?? party?.id ?? m.party_id;
  const [addContact, setAddContact] = useState(!m.known_sender && Boolean(preview.from_address));
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [due, setDue] = useState<string | null>(null);
  const [reason, setReason] = useState(t("eml.defaultNoFollowup"));
  const caseId = fixed?.caseId ?? m.case_id;
  const refType = fixed?.refType ?? m.ref_type;
  const refId = fixed?.refId ?? m.ref_id;
  const save = useMutation({
    mutationFn: () => api<{ interaction: { id: string } }>("/api/interactions/eml", { method: "POST", body: {
      document_id: preview.document_id, party_id: partyId, contact_id: m.party_id === partyId ? m.contact_id : null,
      add_contact: addContact && !(m.known_sender && m.party_id === partyId), direction, case_id: caseId, ref_type: refType, ref_id: refId,
      followup: due ? { action: t("eml.defaultFollowup"), due_on: due } : null, no_followup_reason: due ? null : reason.trim() || null } }),
    onSuccess: (r) => {
      for (const key of [["case-thread"], ["interactions"], ["party"], ["command-center"]]) void qc.invalidateQueries({ queryKey: key });
      onRecorded?.(r.interaction.id);
      onClose();
    },
  });
  const contactName = (f.lang === "fa" ? m.contact_name_fa || m.contact_name_en : m.contact_name_en || m.contact_name_fa) ?? null;
  return (
    <Modal open size="lg" title={t("eml.title")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" disabled={!partyId || (!due && !reason.trim())} busy={save.isPending} onClick={() => save.mutate()} data-testid="eml-record">{t("eml.record")}</Button>
    </>}>
      <div className="flex flex-col gap-3 text-sm" data-testid="eml-dialog">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
          <dt className="text-muted">{t("eml.from")}</dt><dd><Bdi>{preview.from_name ?? ""}</Bdi> <Bdi ltr className="text-muted">{preview.from_address}</Bdi>
            {m.known_sender ? <Badge tone="success" className="ms-2">{contactName ? <Bdi>{contactName}</Bdi> : t("eml.knownSender")}</Badge>
              : <Badge tone="warning" className="ms-2">{t("eml.unknownSender")}</Badge>}</dd>
          {preview.date && <><dt className="text-muted">{t("eml.date")}</dt><dd className="tabular-nums">{f.date(preview.date, true)}</dd></>}
          <dt className="text-muted">{t("eml.subject")}</dt><dd><bdi dir="auto">{preview.subject ?? "—"}</bdi></dd>
          <dt className="text-muted">{t("eml.matched")}</dt><dd data-testid="eml-match">
            {caseId ? <Badge tone="accent">{m.code ? <Bdi ltr>{m.code}</Bdi> : t("eml.thisCase")}</Badge> : <span className="text-warning">{t("eml.noCase")}</span>}
            {refType && <Badge className="ms-1">{t(`eml.refs.${refType}`)}</Badge>}</dd>
        </dl>
        <pre className="max-h-48 overflow-y-auto rounded-md bg-surface-2 p-2 font-sans text-xs whitespace-pre-wrap [unicode-bidi:plaintext]" dir="auto">{preview.body || "—"}</pre>
        {preview.attachments.length > 0 && (
          <ul className="flex flex-wrap gap-2">{preview.attachments.map((a) => (
            <li key={a.filename} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs"><FileType mime={a.content_type} name={a.filename} /><Bdi>{a.filename}</Bdi>
              <span className="text-muted tabular-nums">{f.bytes(a.size)}</span></li>))}</ul>
        )}
        {!fixed?.partyId && !m.party_id && <Field label={t("eml.party")}><PartyField value={party} onChange={setParty} id="eml-party" /></Field>}
        {!m.known_sender && preview.from_address && partyId && (
          <Checkbox label={t("eml.addContact")} checked={addContact} onChange={setAddContact} />
        )}
        <Checkbox label={t("eml.outgoing")} checked={direction === "out"} onChange={(v) => setDirection(v ? "out" : "in")} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("eml.followupDue")} htmlFor="eml-due"><DueDatePicker id="eml-due" value={due} onChange={setDue} /></Field>
          {!due && <Field label={t("eml.noFollowupReason")} htmlFor="eml-reason"><Input id="eml-reason" dir="auto" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        </div>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}
