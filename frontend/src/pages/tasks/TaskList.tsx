/** A list of tasks with done / move / cancel inline (v0.8.0), used by «کارهای من», the case tab and the command
 * center. A task never shows on a party's follow-up list; the party is context only. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Bdi, Button, EmptyState, ErrorNote, Field, Modal, Textarea, useToast } from "../../design/components";
import { TimeLeftBadge } from "../../components/TimeLeft";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import { remindsOf, taskLink, type TaskRow } from "../../lib/tasks";
import { DueDatePicker } from "../parties/shared";

export function useTasksInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["tasks"] });
    void qc.invalidateQueries({ queryKey: ["case-tasks"] });
    void qc.invalidateQueries({ queryKey: ["command-center"] });
  };
}

function TaskDialog({ mode, task, onClose }: { mode: "done" | "move" | "cancel"; task: TaskRow; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const invalidate = useTasksInvalidate();
  const [note, setNote] = useState("");
  const [due, setDue] = useState<string | null>(task.due_on);
  const save = useMutation({
    mutationFn: () => api(`/api/tasks/${task.id}/${mode}`, { method: "POST",
      body: mode === "move" ? { due_on: due, note: note || null } : mode === "cancel" ? { note } : { note: note || null } }),
    onSuccess: () => { toast(t("common.saved"), "success"); invalidate(); onClose(); },
  });
  const valid = mode === "move" ? !!due : mode === "cancel" ? note.trim().length > 0 : true;
  return (
    <Modal open title={t(`tasks.${mode}Title`)} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>{t(`tasks.${mode}`)}</Button></>}>
      <div className="flex flex-col gap-3">
        <p className="text-sm" dir="auto">{task.title}</p>
        {mode === "move" && <Field label={t("tasks.newDue")} htmlFor="task-due"><DueDatePicker id="task-due" value={due} onChange={setDue} /></Field>}
        <Field label={mode === "cancel" ? t("tasks.cancelNote") : t("tasks.note")} htmlFor="task-note">
          <Textarea id="task-note" dir="auto" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

function TaskActions({ task }: { task: TaskRow }) {
  const { t } = useTranslation();
  const invalidate = useTasksInvalidate();
  const [mode, setMode] = useState<"done" | "move" | "cancel" | null>(null);
  const reopen = useMutation({ mutationFn: () => api(`/api/tasks/${task.id}/reopen`, { method: "POST" }), onSuccess: invalidate });
  if (task.status !== "open") {
    return <Button variant="ghost" busy={reopen.isPending} onClick={() => reopen.mutate()}>{t("tasks.reopen")}</Button>;
  }
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button variant="ghost" icon="check" onClick={() => setMode("done")}>{t("tasks.done")}</Button>
      <Button variant="ghost" onClick={() => setMode("move")}>{t("tasks.move")}</Button>
      <Button variant="ghost" onClick={() => setMode("cancel")}>{t("tasks.cancel")}</Button>
      {mode && <TaskDialog mode={mode} task={task} onClose={() => setMode(null)} />}
    </div>
  );
}

export function TaskList({ rows, tone, showCase = true }: { rows: TaskRow[]; tone?: "danger"; showCase?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  if (rows.length === 0) return <EmptyState>{t("tasks.none")}</EmptyState>;
  return (
    <ul className="divide-y divide-line" data-testid="task-list">
      {rows.map((task) => {
        const link = taskLink(task);
        const of = task.status === "open" ? remindsOf(task) : null;
        return (
          <li key={task.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm" data-testid="task-row">
            <span className={`w-24 shrink-0 tabular-nums ${tone === "danger" ? "font-medium text-danger" : "text-muted"}`}>{f.day(task.due_on)}</span>
            {task.priority === "high" && <Badge tone="danger">{t("tasks.high")}</Badge>}
            <span className={`min-w-0 flex-1 truncate ${task.status !== "open" ? "text-muted line-through" : ""}`} dir="auto">{task.title}</span>
            <Badge>{t(`tasks.kinds.${task.source_kind}`)}</Badge>
            {of && <TimeLeftBadge at={of} />}
            {showCase && task.case_id && link && (
              <Link to={link} className="max-w-48 truncate text-xs text-accent hover:underline"><Bdi>{task.case_title ?? t("tasks.openCase")}</Bdi></Link>
            )}
            {task.status !== "open" && task.done_note && <span className="text-xs text-muted" dir="auto">{task.done_note}</span>}
            <TaskActions task={task} />
          </li>
        );
      })}
    </ul>
  );
}
