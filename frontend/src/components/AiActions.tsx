/** AI entry points (v0.9.0 section 3), all opening the same review screen:
 * - ExtractButton: «استخراج با هوش مصنوعی» from attached files or pasted text into a case, an inquiry, an offer
 *   (with its supplier) or a Setad listing conversion;
 * - PartyParseButton: a party and its contact from a signature or a business card;
 * - DraftMessageButton: the RFQ message or the PO cover message in the chosen language.
 * With no provider connected each one says how to connect one; manual entry always works. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import type { Draft, Usage } from "../lib/ai";
import type { LookupItem } from "../lib/smart";
import { DraftReview } from "./DraftReview";
import { LookupField } from "./smart";
import { Button, Checkbox, ErrorNote, Field, Modal, Select, Textarea } from "./ui";

export function useAiConfigured(): boolean {
  const usage = useQuery({ queryKey: ["ai", "usage"], queryFn: () => api<Usage>("/api/ai/usage", { background: true }), staleTime: 30_000 });
  return Boolean(usage.data?.configured);
}

type Doc = { document_id: string; title: string; original_filename: string };

export function ExtractButton({ target, targetId, documents = [], label, onCommitted, needSupplier = false, testId }: {
  target: "case" | "inquiry" | "offer" | "listing";
  targetId: string;
  documents?: Doc[];
  label?: string;
  onCommitted?: (result: Record<string, unknown>) => void;
  needSupplier?: boolean;
  testId?: string;
}) {
  const { t } = useTranslation();
  const configured = useAiConfigured();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [supplier, setSupplier] = useState<LookupItem | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api<Draft>("/api/ai/extract", { method: "POST", body: { target_type: target, target_id: targetId, document_ids: picked,
      text: text || null, party_id: supplier?.id ?? null } }),
    onSuccess: (d) => { setOpen(false); setDraftId(d.id); },
  });
  return (
    <>
      <Button disabled={!configured} title={configured ? undefined : t("ai.extract.notConfigured")} onClick={() => setOpen(true)} data-testid={testId ?? "ai-extract"}>
        {label ?? t("ai.extract.title")}
      </Button>
      <Modal open={open} title={label ?? t("ai.extract.title")} onClose={() => setOpen(false)} footer={
        <Button variant="primary" busy={start.isPending} disabled={(!picked.length && !text.trim()) || (needSupplier && !supplier)} onClick={() => start.mutate()}
          data-testid="ai-extract-start">{t("ai.extract.start")}</Button>}>
        <div className="flex flex-col gap-3">
          {needSupplier && (
            <Field label={t("ai.extract.supplier")}><LookupField kind="party" value={supplier} onChange={setSupplier} testId="ai-extract-supplier" /></Field>
          )}
          {documents.length > 0 && (
            <Field label={t("ai.extract.files")}>
              <div className="flex flex-col gap-1">{documents.map((d) => (
                <Checkbox key={d.document_id} label={d.title || d.original_filename} checked={picked.includes(d.document_id)}
                  onChange={(v) => setPicked(v ? [...picked, d.document_id] : picked.filter((x) => x !== d.document_id))} />))}</div>
            </Field>
          )}
          <Field label={t("ai.extract.paste")} htmlFor="ai-paste">
            <Textarea id="ai-paste" dir="auto" rows={6} value={text} onChange={(e) => setText(e.target.value)} data-testid="ai-extract-text" />
          </Field>
          <ErrorNote error={start.error} />
        </div>
      </Modal>
      <DraftReview draftId={draftId} open={Boolean(draftId)} onClose={() => setDraftId(null)}
        onCommitted={(r) => { onCommitted?.(r); setDraftId(null); }} />
    </>
  );
}

export function PartyParseButton({ roles = [], onCommitted }: { roles?: string[]; onCommitted?: (result: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const configured = useAiConfigured();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [draftId, setDraftId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api<Draft>("/api/ai/parse-party", { method: "POST", body: { text, roles } }),
    onSuccess: (d) => { setOpen(false); setDraftId(d.id); },
  });
  return (
    <>
      <Button disabled={!configured} title={configured ? undefined : t("ai.extract.notConfigured")} onClick={() => setOpen(true)} data-testid="ai-party-parse">
        {t("ai.extract.partyButton")}
      </Button>
      <Modal open={open} title={t("ai.extract.partyButton")} onClose={() => setOpen(false)} footer={
        <Button variant="primary" busy={start.isPending} disabled={!text.trim()} onClick={() => start.mutate()}>{t("ai.extract.start")}</Button>}>
        <Field label={t("ai.extract.partyPaste")} htmlFor="ai-party-text">
          <Textarea id="ai-party-text" dir="auto" rows={6} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <ErrorNote error={start.error} />
      </Modal>
      <DraftReview draftId={draftId} open={Boolean(draftId)} onClose={() => setDraftId(null)}
        onCommitted={(r) => { onCommitted?.(r); setDraftId(null); }} />
    </>
  );
}

export function DraftMessageButton({ target, targetId, onCommitted }: { target: "rfq_recipient" | "purchase_order"; targetId: string;
  onCommitted?: (result: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const configured = useAiConfigured();
  const [lang, setLang] = useState<"en" | "fa">("en");
  const [open, setOpen] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api<Draft>("/api/ai/draft-message", { method: "POST", body: { target_type: target, target_id: targetId, language: lang } }),
    onSuccess: (d) => { setOpen(false); setDraftId(d.id); },
  });
  return (
    <>
      <Button variant="ghost" disabled={!configured} title={configured ? undefined : t("ai.extract.notConfigured")} onClick={() => setOpen(true)} data-testid="ai-draft-message">
        {t("ai.extract.draftButton")}
      </Button>
      <Modal open={open} title={t("ai.extract.draftButton")} onClose={() => setOpen(false)} footer={
        <Button variant="primary" busy={start.isPending} onClick={() => start.mutate()}>{t("ai.extract.start")}</Button>}>
        <Field label={t("ai.extract.draftLanguage")} htmlFor="ai-draft-lang">
          <Select id="ai-draft-lang" value={lang} onChange={(e) => setLang(e.target.value as "en" | "fa")}>
            <option value="en">English</option><option value="fa">فارسی</option>
          </Select>
        </Field>
        <ErrorNote error={start.error} />
      </Modal>
      <DraftReview draftId={draftId} open={Boolean(draftId)} onClose={() => setDraftId(null)}
        onCommitted={(r) => { onCommitted?.(r); setDraftId(null); }} />
    </>
  );
}
