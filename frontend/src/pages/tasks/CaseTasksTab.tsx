/** The case's tasks (v0.8.0): open ones with done / move / cancel, a quick add, and the closed ones below. */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Card, ErrorNote, Loading } from "../../design/components";
import { api } from "../../lib/api";
import type { TaskRow } from "../../lib/tasks";
import { TaskList } from "./TaskList";
import { QuickAddTask } from "./TasksPage";

export function CaseTasksTab({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const open = useQuery({ queryKey: ["case-tasks", caseId, "open"], queryFn: () => api<TaskRow[]>(`/api/cases/${caseId}/tasks`) });
  const closed = useQuery({ queryKey: ["case-tasks", caseId, "closed"],
    queryFn: () => api<TaskRow[]>(`/api/cases/${caseId}/tasks`, { query: { status: "closed" } }) });
  if (open.isLoading) return <Loading />;
  if (open.error || !open.data) return <ErrorNote error={open.error} />;
  return (
    <div className="flex flex-col gap-4" data-testid="case-tasks">
      <Card padded={false} title={t("tasks.caseOpen")}><div className="max-h-96 overflow-y-auto"><TaskList rows={open.data} showCase={false} /></div></Card>
      <Card title={t("tasks.quickAdd")}><QuickAddTask caseId={caseId} /></Card>
      <Card padded={false} title={t("tasks.groups.done")}><div className="max-h-64 overflow-y-auto"><TaskList rows={closed.data ?? []} showCase={false} /></div></Card>
    </div>
  );
}
