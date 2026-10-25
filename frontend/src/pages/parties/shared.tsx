/** Building blocks shared by the command center, parties, funnels and the quick-log dialog. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Badge, Button, ErrorNote, errorMessage, Field, Input, Modal, Select, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api } from "../../lib/api";
import { fromDateString, type QuickDue, quickDueDate, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import type { PartyRoleName } from "../../lib/types";

export const ROLES: PartyRoleName[] = ["buyer", "supplier", "forwarder", "customs_broker", "agent", "other"];
export const CHANNELS = ["whatsapp", "call", "email", "tender_portal", "in_person", "other"] as const;
export const METHOD_TYPES = ["whatsapp", "phone", "email", "telegram", "other"] as const;

export interface Stage {
  role: PartyRoleName;
  code: string;
  sort_order: number;
  is_terminal: boolean;
}

export function useStages() {
  return useQuery({ queryKey: ["parties", "stages"], queryFn: () => api<Stage[]>("/api/parties/stages"), staleTime: Infinity });
}

/** Name in the user's language (falls back to the other one), with the do-not-contact badge. */
export function PartyName({ fa, en, dnc, id, className = "" }: {
  fa: string | null;
  en: string | null;
  dnc?: boolean;
  id?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const primary = (f.lang === "fa" ? fa || en : en || fa) ?? "";
  const label = <Bdi>{primary}</Bdi>;
  return (
    <span className={`inline-flex min-w-0 items-center gap-1.5 ${className}`}>
      {id ? (
        <Link to={`/parties/${id}`} className="truncate font-medium text-accent hover:underline">{label}</Link>
      ) : (
        <span className="truncate font-medium">{label}</span>
      )}
      {dnc && <Badge tone="danger">{t("parties.dnc")}</Badge>}
    </span>
  );
}

export function stageLabel(t: (k: string) => string, role: string, stage: string) {
  return t(`funnel.stages.${role}.${stage}`);
}

/** Stage dropdown for one role; calls the API and records the event server-side. */
export function StageSelect({ partyId, role, stage, onChanged }: {
  partyId: string;
  role: PartyRoleName;
  stage: string;
  onChanged?: () => void;
}) {
  const { t } = useTranslation();
  const stages = useStages();
  const queryClient = useQueryClient();
  const toast = useToast();
  const change = useMutation({
    mutationFn: (next: string) => api(`/api/parties/${partyId}/roles/${role}/stage`, { method: "POST", body: { stage: next } }),
    onSuccess: () => {
      toast(t("parties.stageChanged"), "success");
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      void queryClient.invalidateQueries({ queryKey: ["command-center"] });
      onChanged?.();
    },
    onError: (e) => toast(errorMessage(t, e), "error"),
  });
  return (
    <Select
      className="w-48"
      aria-label={t("parties.stage")}
      value={stage}
      disabled={change.isPending}
      onChange={(e) => change.mutate(e.target.value)}
    >
      {(stages.data ?? []).filter((s) => s.role === role).map((s) => (
        <option key={s.code} value={s.code}>{stageLabel(t, role, s.code)}</option>
      ))}
    </Select>
  );
}

/** Due date: quick buttons (tomorrow / 3 days / 1 week) or a typed date in the user's calendar. */
export function DueDatePicker({ value, onChange, id }: { value: string | null; onChange: (v: string | null) => void; id?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const quick: QuickDue[] = ["tomorrow", "3days", "week"];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {quick.map((q) => {
        const date = quickDueDate(new Date(), q);
        return (
          <button
            key={q}
            type="button"
            onClick={() => onChange(date)}
            className={`h-8 rounded-md border px-2.5 text-sm ${value === date ? "border-accent bg-accent-soft text-accent" : "border-line-strong hover:bg-surface-2"}`}
          >
            {t(`followups.quick.${q}`)}
          </button>
        );
      })}
      <DateInput id={id} value={value ? fromDateString(value) : null} onChange={(d) => onChange(d ? toDateString(d) : null)} />
      {value && <span className="text-xs text-muted tabular-nums">{f.day(value)}</span>}
    </div>
  );
}

function useFollowupInvalidate() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["command-center"] });
    void queryClient.invalidateQueries({ queryKey: ["parties"] });
    void queryClient.invalidateQueries({ queryKey: ["party"] });
  };
}

/** Mark done (optionally with the next follow-up) or reschedule. */
export function FollowupDialog({ mode, followup, onClose }: {
  mode: "done" | "reschedule" | "cancel";
  followup: { id: string; action: string; due_on: string };
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const invalidate = useFollowupInvalidate();
  const [note, setNote] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [nextDue, setNextDue] = useState<string | null>(null);
  const [due, setDue] = useState<string | null>(followup.due_on);

  const mutation = useMutation({
    mutationFn: () => {
      if (mode === "done") {
        return api(`/api/followups/${followup.id}/done`, {
          method: "POST",
          body: { note: note || null, next: nextAction.trim() && nextDue ? { action: nextAction.trim(), due_on: nextDue } : null },
        });
      }
      if (mode === "cancel") return api(`/api/followups/${followup.id}/cancel`, { method: "POST", body: { note } });
      return api(`/api/followups/${followup.id}/reschedule`, { method: "POST", body: { due_on: due } });
    },
    onSuccess: () => {
      toast(t("common.saved"), "success");
      invalidate();
      onClose();
    },
  });

  const valid = mode === "reschedule" ? !!due : mode === "cancel" ? note.trim().length > 0 : !(nextAction.trim() && !nextDue);
  return (
    <Modal
      open
      title={t(`followups.${mode}Title`)}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!valid} busy={mutation.isPending} onClick={() => mutation.mutate()}>
            {t(`followups.${mode}`)}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm"><span className="text-muted">{t("followups.action")}:</span> {followup.action}</p>
        {mode === "reschedule" && (
          <Field label={t("followups.newDue")} htmlFor="fu-due"><DueDatePicker id="fu-due" value={due} onChange={setDue} /></Field>
        )}
        {(mode === "done" || mode === "cancel") && (
          <Field label={mode === "cancel" ? t("followups.cancelNote") : t("followups.doneNote")} htmlFor="fu-note">
            <Textarea id="fu-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        )}
        {mode === "done" && (
          <div className="rounded-md border border-line p-3">
            <p className="mb-2 text-xs font-medium text-muted">{t("followups.nextOptional")}</p>
            <div className="flex flex-col gap-2">
              <Input dir="auto" placeholder={t("followups.actionPlaceholder")} value={nextAction} onChange={(e) => setNextAction(e.target.value)} />
              <DueDatePicker value={nextDue} onChange={setNextDue} />
            </div>
          </div>
        )}
        <ErrorNote error={mutation.error} />
      </div>
    </Modal>
  );
}

/** Row buttons used by every follow-up list. */
export function FollowupActions({ followup, extra }: { followup: { id: string; action: string; due_on: string }; extra?: ReactNode }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"done" | "reschedule" | "cancel" | null>(null);
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button variant="ghost" icon="check" onClick={() => setMode("done")}>{t("followups.done")}</Button>
      <Button variant="ghost" onClick={() => setMode("reschedule")}>{t("followups.reschedule")}</Button>
      {extra}
      {mode && <FollowupDialog mode={mode} followup={followup} onClose={() => setMode(null)} />}
    </div>
  );
}

export function CancelFollowupButton({ followup }: { followup: { id: string; action: string; due_on: string } }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="ghost" onClick={() => setOpen(true)}>{t("followups.cancel")}</Button>
      {open && <FollowupDialog mode="cancel" followup={followup} onClose={() => setOpen(false)} />}
    </>
  );
}
