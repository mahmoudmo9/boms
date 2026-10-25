import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { Bdi } from "../../components/Bdi";
import { DataTable, Pagination } from "../../components/DataTable";
import { Badge, Button, Card, ErrorNote, PageHeader, Stat } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { BackupRun, Health, Job } from "../../lib/types";

const POLL_MS = 5000;

/** "1 of 2" / "۱ از ۲": a word between the numbers, each number isolated, so RTL cannot reorder them. */
export function AttemptsCell({ attempts, max }: { attempts: string; max: string }) {
  return (
    <span className="tabular-nums whitespace-nowrap">
      <Trans i18nKey="system.attemptsValue" values={{ attempts, max }} components={{ n: <bdi dir="ltr" /> }} />
    </span>
  );
}

function statusTone(status: string | null | undefined) {
  if (status === "succeeded" || status === "passed" || status === "done" || status === "ok") return "success" as const;
  if (status === "failed") return "danger" as const;
  if (status === "running" || status === "queued" || status === "skipped") return "warning" as const;
  return "neutral" as const;
}

export function SystemPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [backupPage, setBackupPage] = useState(1);
  const [jobPage, setJobPage] = useState(1);

  const health = useQuery({
    queryKey: ["system", "health"],
    queryFn: () => api<Health>("/api/system/health", { background: true }),
    refetchInterval: POLL_MS,
  });
  const backups = useQuery({
    queryKey: ["system", "backups", backupPage],
    queryFn: () => api<Page<BackupRun>>("/api/system/backups", { query: { page: backupPage, page_size: 10 }, background: true }),
    refetchInterval: POLL_MS,
  });
  const jobs = useQuery({
    queryKey: ["system", "jobs", jobPage],
    queryFn: () => api<Page<Job>>("/api/system/jobs", { query: { page: jobPage, page_size: 10 }, background: true }),
    refetchInterval: POLL_MS,
  });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["system"] });
  const backupNow = useMutation({
    mutationFn: () => api("/api/system/backups", { method: "POST" }),
    onSuccess: () => {
      toast(t("system.backupQueued"), "success");
      refresh();
    },
  });
  const restoreTest = useMutation({
    mutationFn: () => api("/api/system/restore-test", { method: "POST", body: {} }),
    onSuccess: () => {
      toast(t("system.restoreTestQueued"), "success");
      refresh();
    },
  });

  const backupColumns = useMemo<ColumnDef<BackupRun, unknown>[]>(
    () => [
      { id: "started", header: t("system.started"), cell: ({ row }) => <span className="tabular-nums">{f.date(row.original.started_at, true)}</span> },
      { id: "kind", header: t("system.kind"), cell: ({ row }) => t(`system.kinds.${row.original.kind}`) },
      {
        id: "status",
        header: t("system.status"),
        cell: ({ row }) => (
          <span title={row.original.details?.error ?? ""}>
            <Badge tone={statusTone(row.original.status)}>{t(`system.statuses.${row.original.status}`)}</Badge>
          </span>
        ),
      },
      { id: "size", header: t("system.dumpSize"), cell: ({ row }) => <span className="tabular-nums">{f.bytes(row.original.db_dump_bytes)}</span> },
      { id: "files", header: t("system.filesCopied"), cell: ({ row }) => <span className="tabular-nums">{f.num(row.original.files_copied ?? "")}</span> },
      {
        id: "secondary",
        header: t("system.secondary"),
        cell: ({ row }) =>
          row.original.secondary_status ? (
            <span title={row.original.details?.secondary_reason ?? ""}>
              <Badge tone={statusTone(row.original.secondary_status)}>{t(`system.secondaryStatuses.${row.original.secondary_status}`)}</Badge>
            </span>
          ) : null,
      },
      {
        id: "restore",
        header: t("system.restoreTest"),
        cell: ({ row }) =>
          row.original.restore_test_status ? (
            <span title={(row.original.restore_test_details?.failures ?? []).join("\n")}>
              <Badge tone={statusTone(row.original.restore_test_status)}>{t(`system.statuses.${row.original.restore_test_status}`)}</Badge>
            </span>
          ) : null,
      },
    ],
    [t, f],
  );

  const jobColumns = useMemo<ColumnDef<Job, unknown>[]>(
    () => [
      { id: "created", header: t("system.created"), cell: ({ row }) => <span className="tabular-nums">{f.date(row.original.created_at, true)}</span> },
      { id: "type", header: t("system.jobType"), cell: ({ row }) => <Bdi ltr className="font-mono text-xs">{row.original.type}</Bdi> },
      { id: "status", header: t("system.status"), cell: ({ row }) => <Badge tone={statusTone(row.original.status)}>{t(`system.statuses.${row.original.status}`)}</Badge> },
      {
        id: "attempts",
        header: t("system.attempts"),
        cell: ({ row }) => <AttemptsCell attempts={f.num(row.original.attempts)} max={f.num(row.original.max_attempts)} />,
      },
      {
        id: "error",
        header: t("system.lastError"),
        cell: ({ row }) =>
          row.original.last_error ? (
            <Bdi ltr className="line-clamp-1 max-w-md text-xs text-danger" >{row.original.last_error.trim().split("\n").pop()}</Bdi>
          ) : null,
      },
    ],
    [t, f],
  );

  const h = health.data;
  const lastBackup = h?.last_backup;
  const lastRestore = h?.last_restore_test;
  const diskLow = h?.disk.free_bytes !== null && h?.disk.free_bytes !== undefined && h.disk.free_bytes < 5 * 1024 ** 3;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={t("nav.sub.system")}
        subtitle={t("system.subtitle")}
        actions={
          <>
            <Button icon="refresh" busy={restoreTest.isPending} onClick={() => restoreTest.mutate()}>{t("system.runRestoreTest")}</Button>
            <Button variant="primary" icon="database" busy={backupNow.isPending} onClick={() => backupNow.mutate()}>{t("system.backupNow")}</Button>
          </>
        }
      />
      <ErrorNote error={health.error || backupNow.error || restoreTest.error} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card title={t("system.worker")}>
          <div className="flex flex-col gap-3">
            <Badge tone={h?.worker.alive ? "success" : "danger"}>{h?.worker.alive ? t("system.workerAlive") : t("system.workerDown")}</Badge>
            <Stat label={t("system.lastSeen")} value={h?.worker.last_seen ? f.date(h.worker.last_seen, true) : t("system.never")} />
          </div>
        </Card>
        <Card title={t("system.jobs")}>
          <div className="grid grid-cols-3 gap-3">
            <Stat label={t("system.statuses.queued")} value={f.num(h?.jobs.queued ?? 0)} />
            <Stat label={t("system.statuses.running")} value={f.num(h?.jobs.running ?? 0)} />
            <Stat label={t("system.statuses.failed")} value={f.num(h?.jobs.failed ?? 0)} tone={h?.jobs.failed ? "danger" : undefined} />
          </div>
        </Card>
        <Card title={t("system.disk")}>
          <div className="flex flex-col gap-3">
            <Stat label={t("system.diskFree")} value={`${f.bytes(h?.disk.free_bytes)} / ${f.bytes(h?.disk.total_bytes)}`} tone={diskLow ? "danger" : undefined} />
            <Bdi ltr className="truncate text-xs text-muted">{h?.disk.path}</Bdi>
          </div>
        </Card>
        <Card title={t("system.lastBackup")}>
          <div className="flex flex-col gap-2">
            {lastBackup ? (
              <>
                <div className="flex items-center gap-2">
                  <Badge tone={statusTone(lastBackup.status)}>{t(`system.statuses.${lastBackup.status}`)}</Badge>
                  <span className="text-sm tabular-nums">{f.date(lastBackup.started_at, true)}</span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-muted">{t("system.restoreTest")}:</span>
                  {lastRestore ? (
                    <>
                      <Badge tone={statusTone(lastRestore.restore_test_status)}>{t(`system.statuses.${lastRestore.restore_test_status}`)}</Badge>
                      <span className="tabular-nums text-muted">{f.date(lastRestore.restore_test_at)}</span>
                    </>
                  ) : (
                    <span className="text-muted">{t("system.never")}</span>
                  )}
                </div>
              </>
            ) : (
              <span className="text-sm text-danger">{t("system.noBackupYet")}</span>
            )}
          </div>
        </Card>
      </div>

      <Card title={t("system.backupHistory")} padded={false}>
        <DataTable columns={backupColumns} data={backups.data?.items ?? []} rowKey={(r) => r.id} empty={t("system.noBackupYet")} />
        <Pagination page={backupPage} pageSize={10} total={backups.data?.total ?? 0} onPage={setBackupPage} />
      </Card>

      <Card title={t("system.recentJobs")} padded={false}>
        <DataTable columns={jobColumns} data={jobs.data?.items ?? []} rowKey={(r) => r.id} />
        <Pagination page={jobPage} pageSize={10} total={jobs.data?.total ?? 0} onPage={setJobPage} />
      </Card>
    </div>
  );
}
