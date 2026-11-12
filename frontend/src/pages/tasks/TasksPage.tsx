/** «کارهای من» (v0.8.0): the owner's internal tasks grouped overdue / today / this week / later / done, filtered by
 * case and kind, with a quick add of a manual task and done / move / cancel inline. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { Badge, Button, Card, Checkbox, ErrorNote, ErrorState, Field, Input, Loading, PageHeader, Select } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import { TASK_GROUPS, TASK_KINDS, type TasksResponse } from "../../lib/tasks";
import type { Page } from "../../lib/api";
import type { Case } from "../../lib/types";
import { DueDatePicker } from "../parties/shared";
import { TaskList, useTasksInvalidate } from "./TaskList";

function useCaseOptions() {
  return useQuery({ queryKey: ["cases", "options"], queryFn: () => api<Page<Case>>("/api/cases", { query: { page_size: 200 } }) });
}

export function QuickAddTask({ caseId, focus }: { caseId?: string; focus?: boolean }) {
  const { t } = useTranslation();
  const invalidate = useTasksInvalidate();
  const cases = useCaseOptions();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState<string | null>(null);
  const [high, setHigh] = useState(false);
  const [forCase, setForCase] = useState(caseId ?? "");
  const add = useMutation({
    mutationFn: () => api("/api/tasks", { method: "POST", body: { title: title.trim(), due_on: due, priority: high ? "high" : "normal",
      case_id: forCase || null } }),
    onSuccess: () => { setTitle(""); setDue(null); setHigh(false); invalidate(); },
  });
  return (
    <div className="flex flex-col gap-2" data-testid="task-quick-add">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("tasks.title")} htmlFor="task-title">
          <Input id="task-title" className="w-72" dir="auto" autoFocus={focus} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        {!caseId && (
          <Field label={t("tasks.case")} htmlFor="task-case">
            <Select id="task-case" className="w-56" value={forCase} onChange={(e) => setForCase(e.target.value)}>
              <option value="">—</option>
              {(cases.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </Select>
          </Field>
        )}
        <Checkbox label={t("tasks.high")} checked={high} onChange={setHigh} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <DueDatePicker id="task-new-due" value={due} onChange={setDue} />
        <Button variant="primary" icon="plus" disabled={!title.trim() || !due} busy={add.isPending} onClick={() => add.mutate()}>{t("tasks.add")}</Button>
      </div>
      <ErrorNote error={add.error} />
    </div>
  );
}

export function TasksPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case") ?? "";
  const kind = params.get("kind") ?? "";
  const cases = useCaseOptions();
  const list = useQuery({
    queryKey: ["tasks", caseId, kind],
    queryFn: () => api<TasksResponse>("/api/tasks", { query: { case_id: caseId, kind } }),
  });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("nav.sub.myTasks")} subtitle={t("tasks.subtitle")} />
      <Card title={t("tasks.quickAdd")}><QuickAddTask focus={params.get("new") === "1"} /></Card>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("tasks.case")} htmlFor="tasks-filter-case">
          <Select id="tasks-filter-case" className="w-56" value={caseId} onChange={(e) => set("case", e.target.value)}>
            <option value="">{t("tasks.allCases")}</option>
            {(cases.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </Select>
        </Field>
        <Field label={t("tasks.kind")} htmlFor="tasks-filter-kind">
          <Select id="tasks-filter-kind" className="w-56" value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">{t("tasks.allKinds")}</option>
            {TASK_KINDS.map((k) => <option key={k} value={k}>{t(`tasks.kinds.${k}`)}</option>)}
          </Select>
        </Field>
      </div>
      {list.isLoading ? <Loading /> : list.error || !list.data ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : (
        <div className="flex flex-col gap-4">
          {TASK_GROUPS.map((g) => {
            const rows = list.data.groups[g] ?? [];
            const tone = g === "overdue" && rows.length ? "danger" : g === "today" ? "accent" : "neutral";
            return (
              <Card key={g} padded={false} className={g === "overdue" && rows.length ? "border-danger" : ""}
                title={<span className="flex items-center gap-2" data-testid={`tasks-group-${g}`}>{t(`tasks.groups.${g}`)} <Badge tone={tone}>{f.num(rows.length)}</Badge></span>}>
                <div className="max-h-96 overflow-y-auto"><TaskList rows={rows} tone={g === "overdue" ? "danger" : undefined} /></div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
