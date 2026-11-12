/** Quick-log interaction dialog: header button, Ctrl+Shift+L, or from a party page. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type DragEvent, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { Bdi, Button, Checkbox, DateInput, errorMessage, ErrorNote, Field, Icon, Input, Modal, Select, Spinner, Textarea, useToast } from "../../design/components";
import { api, ApiError} from "../../lib/api";
import { canSaveQuickLog } from "../../lib/followups";
import type { Contact, DocumentDetail, Party, PartyDetail} from "../../lib/types";
import { CHANNELS, DueDatePicker, stageLabel, useStages } from "./shared";
import { ContactField, PartyField } from "../../components/fields";

interface QuickLogContextValue {
  open: (partyId?: string) => void;
}

const QuickLogContext = createContext<QuickLogContextValue>({ open: () => undefined });
export const useQuickLog = () => useContext(QuickLogContext);

export function QuickLogProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ open: boolean; partyId?: string; key: number }>({ open: false, key: 0 });
  const open = useCallback((partyId?: string) => setState((s) => ({ open: true, partyId, key: s.key + 1 })), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <QuickLogContext.Provider value={{ open }}>
      {children}
      {state.open && (
        <QuickLogDialog key={state.key} initialPartyId={state.partyId} onClose={() => setState((s) => ({ ...s, open: false }))} />
      )}
    </QuickLogContext.Provider>
  );
}



interface Attachment {
  name: string;
  status: "uploading" | "ok" | "error";
  id?: string;
  error?: unknown;
}

function QuickLogDialog({ initialPartyId, onClose }: { initialPartyId?: string; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const stages = useStages();
  const fileInput = useRef<HTMLInputElement>(null);

  const [party, setParty] = useState<Party | null>(null);
  const [contactId, setContactId] = useState("");
  const [channel, setChannel] = useState<string>("whatsapp");
  const [direction, setDirection] = useState<string>("in");
  const [day, setDay] = useState<Date | null>(new Date());
  const [time, setTime] = useState(() => {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  });
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [followupAction, setFollowupAction] = useState("");
  const [followupDue, setFollowupDue] = useState<string | null>(null);
  const [noFollowup, setNoFollowup] = useState(false);
  const [noFollowupReason, setNoFollowupReason] = useState("");
  const [moveRole, setMoveRole] = useState("");
  const [moveStage, setMoveStage] = useState("");

  useEffect(() => {
    if (initialPartyId) void api<PartyDetail>(`/api/parties/${initialPartyId}`).then(setParty);
  }, [initialPartyId]);

  const contacts = useQuery({
    queryKey: ["contacts", party?.id],
    queryFn: () => api<Contact[]>("/api/contacts", { query: { party_id: party!.id } }),
    enabled: !!party,
  });

  const occurredAt = (() => {
    if (!day || !/^\d{2}:\d{2}$/.test(time)) return null;
    const [h, m] = time.split(":").map(Number);
    return new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m);
  })();
  const uploading = attachments.some((a) => a.status === "uploading");
  const canSave =
    canSaveQuickLog({ partyId: party?.id ?? null, channel, direction, occurredAt, followupAction, followupDue, noFollowup, noFollowupReason }) &&
    !uploading;

  const addFiles = async (files: File[]) => {
    for (const file of files) {
      setAttachments((list) => [...list, { name: file.name, status: "uploading" }]);
      const form = new FormData();
      form.append("file", file);
      let result: Attachment;
      try {
        const doc = await api<DocumentDetail>("/api/documents", { method: "POST", form });
        result = { name: file.name, status: "ok", id: doc.id };
      } catch (err) {
        // an already-registered file is linked, not uploaded again
        result = err instanceof ApiError && err.code === "duplicate_document"
          ? { name: file.name, status: "ok", id: String(err.details.id) }
          : { name: file.name, status: "error", error: err };
      }
      setAttachments((list) => list.map((a) => (a.name === file.name && a.status === "uploading" ? result : a)));
    }
  };

  const save = useMutation({
    mutationFn: () =>
      api<{ id: string; party_id: string }>("/api/interactions", {
        method: "POST",
        body: {
          party_id: party!.id,
          contact_id: contactId || null,
          channel,
          direction,
          occurred_at: occurredAt!.toISOString(),
          subject: subject.trim() || null,
          body: body || null,
          followup: noFollowup ? null : { action: followupAction.trim(), due_on: followupDue },
          no_followup_reason: noFollowup ? noFollowupReason.trim() : null,
          move_stage: moveRole && moveStage ? { role: moveRole, stage: moveStage } : null,
          document_ids: attachments.filter((a) => a.status === "ok" && a.id).map((a) => a.id),
        },
      }),
    onSuccess: (res) => {
      toast(t("quicklog.saved"), "success");
      for (const key of ["command-center", "parties", "party", "interactions"]) void queryClient.invalidateQueries({ queryKey: [key] });
      onClose();
      navigate(`/parties/${res.party_id}?tab=interactions`);
    },
  });

  const partyRoles = party?.roles ?? [];
  return (
    <Modal
      open
      wide
      title={t("quicklog.title")}
      onClose={onClose}
      footer={
        <>
          {!canSave && <span className="me-auto text-xs text-muted">{t("quicklog.saveHint")}</span>}
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!canSave} busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
        </>
      }
    >
      <div className="flex max-h-[65vh] flex-col gap-3 overflow-y-auto pe-1">
        <Field label={t("quicklog.party")} htmlFor="ql-party"><PartyField value={party} onChange={(p) => { setParty(p); setContactId(""); setMoveRole(""); }} /></Field>
        {party?.do_not_contact && (
          <p className="rounded-md bg-danger-soft px-2.5 py-1.5 text-sm text-danger">{t("parties.dncWarning")} {party.do_not_contact_reason}</p>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label={t("interactions.channel")} htmlFor="ql-channel">
            <Select id="ql-channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {CHANNELS.map((c) => <option key={c} value={c}>{t(`interactions.channels.${c}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("interactions.direction")} htmlFor="ql-direction">
            <Select id="ql-direction" value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="in">{t("interactions.directions.in")}</option>
              <option value="out">{t("interactions.directions.out")}</option>
            </Select>
          </Field>
          <Field label={t("interactions.contact")} htmlFor="ql-contact">
            <ContactField id="ql-contact" contacts={(contacts.data ?? []).filter((c) => c.status === "active")} value={contactId} onChange={setContactId} disabled={!party} />
          </Field>
        </div>
        <Field label={t("interactions.when")} htmlFor="ql-day">
          <div className="flex items-center gap-2">
            <DateInput id="ql-day" value={day} onChange={setDay} />
            <Input type="time" dir="ltr" className="w-28" value={time} onChange={(e) => setTime(e.target.value)} aria-label={t("interactions.time")} />
          </div>
        </Field>
        <Field label={t("interactions.subject")} htmlFor="ql-subject">
          <Input id="ql-subject" dir="auto" value={subject} maxLength={500} onChange={(e) => setSubject(e.target.value)} />
        </Field>
        <Field label={t("interactions.body")} htmlFor="ql-body" hint={t("interactions.bodyHint")}>
          <Textarea id="ql-body" dir="auto" rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e: DragEvent) => { e.preventDefault(); void addFiles(Array.from(e.dataTransfer.files)); }}
          className="rounded-md border-2 border-dashed border-line-strong p-3 text-sm"
        >
          <input ref={fileInput} type="file" multiple hidden onChange={(e) => { if (e.target.files) void addFiles(Array.from(e.target.files)); e.target.value = ""; }} />
          <button type="button" className="inline-flex items-center gap-1.5 text-accent hover:underline" onClick={() => fileInput.current?.click()}>
            <Icon name="upload" size={15} /> {t("quicklog.attach")}
          </button>
          {attachments.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {attachments.map((a, i) => (
                <li key={`${a.name}-${i}`} className="flex items-center gap-2">
                  {a.status === "uploading" ? <Spinner size={12} /> : <Icon name={a.status === "ok" ? "check" : "alert"} size={14} className={a.status === "ok" ? "text-success" : "text-danger"} />}
                  <Bdi>{a.name}</Bdi>
                  {a.status === "error" && <span className="text-xs text-danger">{errorMessage(t, a.error)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <fieldset className={`rounded-md border p-3 ${canSaveQuickLog({ partyId: "x", channel, direction, occurredAt: new Date(), followupAction, followupDue, noFollowup, noFollowupReason }) ? "border-line" : "border-warning"}`}>
          <legend className="px-1 text-sm font-semibold">{t("quicklog.nextAction")} *</legend>
          {!noFollowup && (
            <div className="flex flex-col gap-2">
              <Input dir="auto" aria-label={t("followups.action")} placeholder={t("followups.actionPlaceholder")} value={followupAction} onChange={(e) => setFollowupAction(e.target.value)} />
              <DueDatePicker id="ql-due" value={followupDue} onChange={setFollowupDue} />
            </div>
          )}
          <div className="mt-2">
            <Checkbox label={t("quicklog.noFollowup")} checked={noFollowup} onChange={setNoFollowup} />
          </div>
          {noFollowup && (
            <Input className="mt-2" aria-label={t("quicklog.noFollowupReason")} placeholder={t("quicklog.noFollowupReason")} value={noFollowupReason} maxLength={500} onChange={(e) => setNoFollowupReason(e.target.value)} />
          )}
        </fieldset>

        {partyRoles.length > 0 && (
          <Field label={t("quicklog.moveStage")} htmlFor="ql-role">
            <div className="flex gap-2">
              <Select id="ql-role" className="w-44" value={moveRole} onChange={(e) => { setMoveRole(e.target.value); setMoveStage(""); }}>
                <option value="">—</option>
                {partyRoles.map((r) => <option key={r.role} value={r.role}>{t(`parties.roles.${r.role}`)}</option>)}
              </Select>
              {moveRole && (
                <Select className="w-48" aria-label={t("parties.stage")} value={moveStage} onChange={(e) => setMoveStage(e.target.value)}>
                  <option value="">—</option>
                  {(stages.data ?? []).filter((s) => s.role === moveRole).map((s) => (
                    <option key={s.code} value={s.code}>{stageLabel(t, moveRole, s.code)}</option>
                  ))}
                </Select>
              )}
            </div>
          </Field>
        )}
        <ErrorNote error={save.error} />
        <p className="text-xs text-muted">{t("quicklog.shortcut")} <kbd dir="ltr" className="rounded border border-line px-1">Ctrl Shift L</kbd> · {t("quicklog.timesLocal")}</p>
      </div>
    </Modal>
  );
}
