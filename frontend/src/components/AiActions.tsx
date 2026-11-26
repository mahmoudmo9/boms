/** AI entry points (v0.9.0 section 3), all opening the same review screen:
 * - ExtractButton: «استخراج با هوش مصنوعی» from attached files or pasted text into a case, an inquiry, an offer
 *   (with its supplier) or a Setad listing conversion;
 * - PartyParseButton: a party and its contact from a signature or a business card;
 * - DraftMessageButton: the RFQ message, the PO or quotation cover message or the inquiry reply, with the owner's
 *   instruction (v0.10.1).
 * With no provider connected each one says how to connect one; manual entry always works. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { type Draft, INSTRUCTION_PRESETS, togglePreset, type Usage } from "../lib/ai";
import { useFormat } from "../lib/prefs";
import type { LookupItem } from "../lib/smart";
import { Badge, Button, buttonClass, Checkbox, Chip, Drawer, ErrorNote, Field, LookupField, Modal, Select, Spinner, Textarea, useToast } from "../design/components";

// The review screen (and its PDF page viewer) loads only when a draft is opened.
const DraftReview = lazy(() => import("./DraftReview").then((m) => ({ default: m.DraftReview })));

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
      {draftId && <Suspense fallback={null}><DraftReview draftId={draftId} open onClose={() => setDraftId(null)}
        onCommitted={(r) => { onCommitted?.(r); setDraftId(null); }} /></Suspense>}
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
      {draftId && <Suspense fallback={null}><DraftReview draftId={draftId} open onClose={() => setDraftId(null)}
        onCommitted={(r) => { onCommitted?.(r); setDraftId(null); }} /></Suspense>}
    </>
  );
}

export type DraftTarget = "rfq_recipient" | "purchase_order" | "quote" | "inquiry_reply";
type Chosen = { subject?: string; body?: string; mailto?: string; recipient?: Record<string, unknown> } & Record<string, unknown>;

/** v0.10.1 (0.4.1): «پیش‌نویس با هوش» on every drafting action (RFQ recipient, PO cover, quotation cover, inquiry reply).
 * The owner can instruct the AI («دستور به هوش», with preset chips); «ساخت دوباره» keeps the earlier drafts selectable;
 * «انتخاب این متن» puts the subject and body where they belong (the RFQ recipient's editor and its mailto) — asking
 * replace or append when the recipient's text was already edited — or shows them to copy / open in the mail client.
 * Drafts only: BOMS never sends anything. */
export function DraftMessageButton({ target, targetId, language: initialLanguage = null, hasEditedText = false, prepare, onCommitted }: {
  /** the recipient's language; null: BOMS picks it from the party (its country) */
  target: DraftTarget; targetId: string; language?: string | null; hasEditedText?: boolean;
  /** saves what the owner typed but did not save yet, so a draft appended to it keeps it */
  prepare?: () => Promise<unknown>; onCommitted?: (result: Chosen) => void }) {
  const { t } = useTranslation();
  const configured = useAiConfigured();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="ghost" icon="sparkle" disabled={!configured} title={configured ? undefined : t("ai.extract.notConfigured")} onClick={() => setOpen(true)} data-testid="ai-draft-message">
        {t("ai.extract.draftButton")}
      </Button>
      {open && <DraftComposer target={target} targetId={targetId} initialLanguage={initialLanguage} hasEditedText={hasEditedText} prepare={prepare}
        onClose={() => setOpen(false)} onChosen={(r) => { onCommitted?.(r); if (target === "rfq_recipient") setOpen(false); }} />}
    </>
  );
}

function DraftComposer({ target, targetId, initialLanguage, hasEditedText, prepare, onClose, onChosen }: {
  target: DraftTarget; targetId: string; initialLanguage: string | null; hasEditedText: boolean; prepare?: () => Promise<unknown>; onClose: () => void;
  onChosen: (result: Chosen) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [lang, setLang] = useState<"auto" | "en" | "fa">(initialLanguage === "fa" || initialLanguage === "en" ? initialLanguage : "auto");
  const [instruction, setInstruction] = useState("");
  const [asking, setAsking] = useState<string | null>(null);          // the draft waiting for «جایگزین / افزودن»
  const [chosen, setChosen] = useState<Chosen | null>(null);
  const key = ["ai", "drafts", target, targetId];
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<Draft[]>(`/api/ai/drafts?target_type=${target}&target_id=${targetId}`, { background: true }),
    refetchInterval: (q) => (q.state.data ?? []).some((d) => d.status === "pending") ? 1500 : false,
  });
  const drafts = (list.data ?? []).filter((d) => d.task === "draft_message" && d.status !== "superseded");
  const start = useMutation({
    mutationFn: () => api<Draft>("/api/ai/draft-message", { method: "POST", body: { target_type: target, target_id: targetId, language: lang === "auto" ? null : lang,
      instruction: instruction.trim() || null } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  });
  const choose = useMutation({
    mutationFn: async ({ id, mode }: { id: string; mode: "replace" | "append" }) => {
      await prepare?.();
      return api<Draft & { result: Chosen }>(`/api/ai/drafts/${id}/choose`, { method: "POST", body: { mode } });
    },
    onSuccess: (d) => { setAsking(null); void qc.invalidateQueries({ queryKey: key }); setChosen(d.result); onChosen(d.result); },
  });
  const pick = (id: string) => (target === "rfq_recipient" && hasEditedText ? setAsking(id) : choose.mutate({ id, mode: "replace" }));
  // a preset reads like the owner's own instruction (in the language of the UI, as he types it)
  const presetText = (group: string, p: string) => t(`ai.compose.presets.${group}.${p}`);
  return (
    <Drawer open title={t("ai.compose.title")} onClose={onClose} width="w-[min(40rem,100vw)]" testId="draft-composer">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">{t("ai.compose.hint")}</p>
        <Field label={t("ai.extract.draftLanguage")} htmlFor="ai-draft-lang">
          <Select id="ai-draft-lang" value={lang} onChange={(e) => setLang(e.target.value as "auto" | "en" | "fa")}>
            {lang === "auto" && <option value="auto">{t("ai.compose.partyLanguage")}</option>}
            <option value="en">English</option><option value="fa">فارسی</option>
          </Select>
        </Field>
        <Field label={t("ai.compose.instruction")} htmlFor="ai-instruction" hint={t("ai.compose.instructionHint")}>
          <Textarea id="ai-instruction" dir={instruction ? "auto" : undefined} rows={3} maxLength={1000} value={instruction} onChange={(e) => setInstruction(e.target.value)}
            placeholder={t("ai.compose.instructionPlaceholder")} data-testid="ai-instruction" />
        </Field>
        <div className="flex flex-col gap-2" data-testid="ai-presets">
          {Object.entries(INSTRUCTION_PRESETS).map(([group, presets]) => (
            <div key={group} className="flex flex-wrap items-center gap-1.5">
              <span className="w-20 shrink-0 text-xs text-muted">{t(`ai.compose.presetGroups.${group}`)}</span>
              {presets.map((p) => {
                const phrase = presetText(group, p);
                return <Chip key={p} selected={instruction.split(/[،,]\s*/).map((x) => x.trim()).includes(phrase)}
                  onClick={() => setInstruction((v) => togglePreset(v, phrase))}>{t(`ai.compose.presets.${group}.${p}`)}</Chip>;
              })}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" icon="sparkle" busy={start.isPending} onClick={() => start.mutate()} data-testid="ai-draft-start">
            {drafts.length ? t("ai.compose.regenerate") : t("ai.compose.generate")}
          </Button>
          <span className="text-xs text-muted">{t("ai.compose.neverSent")}</span>
        </div>
        <ErrorNote error={start.error || choose.error} />
        {chosen && target !== "rfq_recipient" && <ChosenText chosen={chosen} lang={lang} />}
        <ol className="flex flex-col gap-3" data-testid="ai-drafts">
          {drafts.map((d, i) => <DraftCard key={d.id} draft={d} n={drafts.length - i} busy={choose.isPending} onPick={() => pick(d.id)} />)}
        </ol>
      </div>
      {asking && (
        <Modal open title={t("ai.compose.replaceTitle")} onClose={() => setAsking(null)} footer={<>
          <Button onClick={() => setAsking(null)}>{t("common.cancel")}</Button>
          <Button busy={choose.isPending} onClick={() => choose.mutate({ id: asking, mode: "append" })} data-testid="ai-append">{t("ai.compose.append")}</Button>
          <Button variant="primary" busy={choose.isPending} onClick={() => choose.mutate({ id: asking, mode: "replace" })} data-testid="ai-replace">{t("ai.compose.replace")}</Button>
        </>}>
          <p className="text-sm">{t("ai.compose.replaceText")}</p>
        </Modal>
      )}
    </Drawer>
  );
}

function DraftCard({ draft, n, busy, onPick }: { draft: Draft; n: number; busy: boolean; onPick: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const value = (path: string) => { const x = draft.fields.find((k) => k.path === path); return x ? String(x.final ?? x.proposed ?? "") : ""; };
  const lang = draft.payload?.language === "fa" ? "fa" : "en";
  const dir = lang === "fa" ? "rtl" : "ltr";
  const chosenAlready = draft.status === "accepted" || draft.status === "partly_accepted";
  return (
    <li className={`rounded-xl border p-3 ${chosenAlready ? "border-accent-line bg-accent-soft" : "border-line"}`} data-testid="ai-draft" data-status={draft.status}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="font-medium text-fg">{t("ai.compose.draftN", { n })}</span>
        {draft.created_at && <span className="tabular-nums">{f.time(new Date(draft.created_at))}</span>}
        {draft.payload?.instruction && <Badge tone="accent" icon="sparkle"><bdi>{draft.payload.instruction}</bdi></Badge>}
        {chosenAlready && <Badge tone="success" icon>{t("ai.compose.chosen")}</Badge>}
      </div>
      {draft.status === "pending" ? <p className="flex items-center gap-2 text-sm text-muted"><Spinner /> {t("ai.review.working")}</p>
        : draft.status === "failed" ? <p className="text-sm text-danger">{t("ai.review.failed")} <bdi className="text-xs">{draft.error}</bdi></p> : <>
          {value("subject") && <p className="mb-1 text-sm font-medium [unicode-bidi:plaintext]" dir={dir} lang={lang}>{value("subject")}</p>}
          <p className="max-h-56 overflow-y-auto text-sm whitespace-pre-wrap [unicode-bidi:plaintext]" dir={dir} lang={lang} data-testid="ai-draft-body">{value("body")}</p>
          {value("back_translation_fa") && lang !== "fa" && (
            <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer">{t("ai.compose.backTranslation")}</summary>
              <p className="mt-1 whitespace-pre-wrap" dir="rtl" lang="fa">{value("back_translation_fa")}</p></details>
          )}
          {draft.status === "ready" && <div className="mt-2"><Button variant="primary" busy={busy} onClick={onPick} data-testid="ai-draft-choose">{t("ai.compose.choose")}</Button></div>}
        </>}
    </li>
  );
}

/** The chosen text of a draft BOMS does not store (PO / quotation cover, inquiry reply): copy it or open the mail client. */
function ChosenText({ chosen, lang }: { chosen: Chosen; lang: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const copy = async (v: string) => { try { await navigator.clipboard.writeText(v); toast(t("sourcing.rfq.copied"), "success"); } catch { toast(t("errors.generic"), "error"); } };
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-accent-line bg-accent-soft p-3" data-testid="ai-chosen" lang={lang}>
      <span className="text-sm font-medium">{t("ai.compose.chosenReady")}</span>
      {chosen.body && <Button icon="list" onClick={() => void copy(String(chosen.body))}>{t("sourcing.rfq.copyText")}</Button>}
      {chosen.subject && <Button onClick={() => void copy(String(chosen.subject))}>{t("sourcing.rfq.copySubject")}</Button>}
      {chosen.mailto && <a href={String(chosen.mailto)} className={buttonClass("secondary")}>{t("sourcing.rfq.openMail")}</a>}
    </div>
  );
}
