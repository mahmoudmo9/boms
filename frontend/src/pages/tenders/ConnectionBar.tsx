/** Setad connection bar: connect / disconnect, role chip, full / quick fetch, stop, progress, last run and its report,
 * and the captcha banner. The agent runs on the owner's PC; this bar only queues commands and polls its status. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, ErrorNote, Modal } from "../../components/ui";
import { api } from "../../lib/api";
import type { ListingSource } from "../../lib/listings";
import { useFormat } from "../../lib/prefs";
import type { AgentState, HarvestRunInfo } from "../../lib/types";

const RUN_TONE: Record<HarvestRunInfo["status"], "success" | "warning" | "danger" | "neutral" | "accent"> = {
  done: "success", needs_review: "warning", cancelled: "neutral", error: "danger", running: "accent",
};

export function useAgent() {
  return useQuery({
    queryKey: ["setad-agent"],
    queryFn: () => api<AgentState>("/api/setad/agent", { background: true }),
    refetchInterval: 2000,
  });
}

/** Shown while Setad asks for a captcha: the owner types it in the Setad window (BOMS never solves captchas). */
export function CaptchaBanner({ waiting, message }: { waiting: boolean; message?: string | null }) {
  const { t } = useTranslation();
  if (!waiting) return null;
  return (
    <div role="alert" data-testid="captcha-banner"
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning">
      <b>{t("setad.captcha.title")}</b><span>{t("setad.captcha.text")}</span>
      {message && <span className="text-xs opacity-80" dir="auto">{message}</span>}
    </div>
  );
}

export function ConnectionBar({ source }: { source: ListingSource }) {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const agent = useAgent();
  const [report, setReport] = useState<string | null>(null);
  const a = agent.data;
  const wanted = source === "setad_purchase" ? "EPROC" : "ETEND";
  const send = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      if (!a?.alive) await api("/api/setad/agent/start", { method: "POST" });
      return api("/api/setad/commands", { method: "POST", body });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["setad-agent"] }),
  });
  const cancel = useMutation({ mutationFn: () => api("/api/setad/cancel", { method: "POST" }) });
  const busy = Boolean(a?.command) || (a?.queued ?? 0) > 0;
  const run = a?.runs?.[source] ?? null;
  const fetching = a?.command === "full_fetch" || a?.command === "quick_fetch";
  return (
    <div className="flex flex-col gap-2" data-testid="connection-bar">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface px-3 py-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${a?.connected ? "bg-success" : a?.alive ? "bg-warning" : "bg-line-strong"}`} aria-hidden />
        <span className="text-sm" data-testid="agent-state">
          {a?.connected ? t("setad.connected") : a?.alive ? t("setad.agentRunning") : t("setad.notConnected")}
        </span>
        {a?.connected && a.role && (
          <button type="button" data-testid="role-chip" title={t("setad.switchRole")}
            className={`rounded-full border px-2 py-0.5 text-xs ${a.role === wanted ? "border-line" : "border-warning text-warning"}`}
            disabled={busy} onClick={() => send.mutate({ command: "set_role", role: a.role === "EPROC" ? "ETEND" : "EPROC" })}>
            {t(`setad.roles.${a.role}`)}
          </button>
        )}
        {!a?.connected
          ? <Button variant="primary" busy={send.isPending} onClick={() => send.mutate({ command: "connect", role: wanted })}>{t("setad.connect")}</Button>
          : <Button variant="ghost" disabled={busy} onClick={() => send.mutate({ command: "disconnect" })}>{t("setad.disconnect")}</Button>}
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        <Button disabled={!a?.connected || busy} onClick={() => send.mutate({ command: "full_fetch", source })}>{t("setad.fullFetch")}</Button>
        <Button disabled={!a?.connected || busy || !run} onClick={() => send.mutate({ command: "quick_fetch", source })}>{t("setad.quickFetch")}</Button>
        {(busy || fetching) && <Button variant="danger" busy={cancel.isPending} onClick={() => cancel.mutate()}>{t("setad.stop")}</Button>}
        {a?.command && (
          <span className="text-xs text-muted" data-testid="agent-progress">
            {t(`setad.commands.${a.command}`, { defaultValue: a.command })}
            {a.pages_total ? ` · ${t("setad.pages", { done: f.num(a.pages_done ?? 0), total: f.num(a.pages_total) })}` : ""}
            {a.rows_seen ? ` · ${t("setad.rows", { n: f.num(a.rows_seen) })}` : ""}
          </span>
        )}
        <span className="ms-auto flex flex-wrap items-center gap-2 text-xs text-muted">
          {run ? <>
            <span>{t(`setad.runKinds.${run.kind}`)}:</span>
            <Badge tone={RUN_TONE[run.status]}>{t(`setad.runStatus.${run.status}`)}</Badge>
            <span className="tabular-nums">{f.date(run.finished_at ?? run.started_at, true)}</span>
            <span>{t("setad.runSummary", { n: f.num(run.rows_seen), added: f.num(run.new_count), changed: f.num(run.changed_count) })}</span>
            <button type="button" className="text-accent hover:underline" onClick={() => setReport(run.id)}>{t("setad.report")}</button>
          </> : <span>{t("setad.noRun")}</span>}
        </span>
      </div>
      {a?.message && a.command && <p className="text-xs text-muted" dir="auto">{a.message}</p>}
      <CaptchaBanner waiting={Boolean(a?.captcha_waiting)} message={a?.captcha_message} />
      {a?.last_error && !a.command && <p className="rounded-md bg-danger-soft px-3 py-1.5 text-sm text-danger" role="alert" dir="auto">{a.last_error}</p>}
      <ErrorNote error={send.error || cancel.error} />
      {report && <RunReport id={report} onClose={() => setReport(null)} />}
    </div>
  );
}

function RunReport({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const run = useQuery({ queryKey: ["setad-run", id], queryFn: () => api<HarvestRunInfo & { issues: Record<string, string[][]> }>(`/api/setad/runs/${id}`) });
  const r = run.data;
  return (
    <Modal open title={t("setad.report")} onClose={onClose} footer={<Button onClick={onClose}>{t("common.close")}</Button>}>
      {r && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="run-report">
          <dt className="text-muted">{t("setad.reportFields.status")}</dt><dd>{t(`setad.runStatus.${r.status}`)}</dd>
          <dt className="text-muted">{t("setad.reportFields.started")}</dt><dd className="tabular-nums">{f.date(r.started_at, true)}</dd>
          <dt className="text-muted">{t("setad.reportFields.finished")}</dt><dd className="tabular-nums">{r.finished_at ? f.date(r.finished_at, true) : "—"}</dd>
          <dt className="text-muted">{t("setad.reportFields.pages")}</dt><dd className="tabular-nums">{f.num(r.pages_done)} / {f.num(r.pages_total ?? 0)}</dd>
          <dt className="text-muted">{t("setad.reportFields.reported")}</dt><dd className="tabular-nums">{r.reported_count === null ? "—" : f.num(r.reported_count)}</dd>
          <dt className="text-muted">{t("setad.reportFields.seen")}</dt><dd className="tabular-nums">{f.num(r.rows_seen)}</dd>
          <dt className="text-muted">{t("setad.reportFields.new")}</dt><dd className="tabular-nums">{f.num(r.new_count)}</dd>
          <dt className="text-muted">{t("setad.reportFields.changed")}</dt><dd className="tabular-nums">{f.num(r.changed_count)}</dd>
          <dt className="text-muted">{t("setad.reportFields.duplicates")}</dt><dd className="tabular-nums">{f.num(r.duplicates)}</dd>
          {r.errors && <><dt className="text-muted">{t("setad.reportFields.errors")}</dt><dd className="whitespace-pre-wrap text-danger" dir="auto">{r.errors}</dd></>}
        </dl>
      )}
    </Modal>
  );
}
