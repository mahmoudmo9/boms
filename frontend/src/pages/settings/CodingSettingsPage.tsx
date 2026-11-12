/** Settings → «کدگذاری و نام‌گذاری» (v0.9.0): code patterns per kind with a live example, the output naming pattern,
 * and the readable folder view (where, hard links or copies, last sync). A pattern change applies to new codes only. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, CodeChip, ErrorNote, Input, Loading, PageHeader } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { SettingsResponse } from "../../lib/types";

type PatternRow = { kind: string; pattern: string; default: string; example: string; reserved: boolean };
type FolderStatus = { enabled: boolean; root: string; mode?: "hardlink" | "copy"; at?: string; cases?: number; linked?: number; copied?: number };

function PatternRowEditor({ row }: { row: PatternRow }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [value, setValue] = useState(row.pattern);
  const preview = useQuery({
    queryKey: ["codes", "preview", row.kind, value],
    queryFn: () => api<PatternRow>("/api/codes/preview", { method: "POST", body: { kind: row.kind, pattern: value } }),
    enabled: value !== row.pattern && value.length > 2,
    retry: false,
  });
  const save = useMutation({
    mutationFn: () => api("/api/settings", { method: "PATCH", body: { [`codes.pattern.${row.kind}`]: value } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["codes"] }),
  });
  const example = value === row.pattern ? row.example : preview.data?.example;
  return (
    <tr className="border-b border-line" data-testid="code-pattern" data-kind={row.kind}>
      <td className="p-2 text-sm">{t(`codes.kinds.${row.kind}`)} {row.reserved && <Badge>{t("codes.reserved")}</Badge>}</td>
      <td className="p-2"><Input dir="ltr" className="w-56 font-mono" value={value} aria-label={t("codes.pattern")} onChange={(e) => setValue(e.target.value)} /></td>
      <td className="p-2">{preview.isError ? <span className="text-xs text-danger">{t("codes.invalidPattern")}</span> : <CodeChip code={example} copy={false} />}</td>
      <td className="p-2">
        <Button variant="ghost" disabled={value === row.pattern || preview.isError} busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
        {value !== row.default && <Button variant="ghost" onClick={() => setValue(row.default)}>{t("codes.default")}</Button>}
        <ErrorNote error={save.error} />
      </td>
    </tr>
  );
}

export function CodingSettingsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const patterns = useQuery({ queryKey: ["codes", "patterns"], queryFn: () => api<PatternRow[]>("/api/codes/patterns") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const folders = useQuery({ queryKey: ["folders", "status"], queryFn: () => api<FolderStatus>("/api/folders/status") });
  const [naming, setNaming] = useState<string | null>(null);
  const saveNaming = useMutation({
    mutationFn: () => api("/api/settings", { method: "PATCH", body: { "naming.output": naming } }),
    onSuccess: () => { setNaming(null); void qc.invalidateQueries({ queryKey: ["settings"] }); },
  });
  const sync = useMutation({ mutationFn: () => api("/api/folders/sync", { method: "POST" }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["folders"] }) });
  const current = ((settings.data?.values as Record<string, unknown> | undefined)?.["naming.output"] as string | undefined) ?? "";
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("codes.settings.title")} subtitle={t("codes.settings.subtitle")} />
      <Card title={t("codes.settings.patterns")} padded={false}>
        {patterns.isLoading ? <Loading /> : (
          <div className="overflow-x-auto"><table className="w-full"><thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
            <th className="p-2 text-start">{t("codes.kind")}</th><th className="p-2 text-start">{t("codes.pattern")}</th>
            <th className="p-2 text-start">{t("codes.example")}</th><th />
          </tr></thead><tbody>{(patterns.data ?? []).map((r) => <PatternRowEditor key={r.kind} row={r} />)}</tbody></table></div>
        )}
        <p className="p-3 text-xs text-muted">{t("codes.settings.tokens")}</p>
      </Card>
      <Card title={t("codes.settings.naming")}>
        <div className="flex flex-wrap items-end gap-2">
          <Input dir="ltr" className="w-96 font-mono" aria-label={t("codes.settings.naming")} value={naming ?? current} onChange={(e) => setNaming(e.target.value)} />
          <Button variant="primary" disabled={naming === null} busy={saveNaming.isPending} onClick={() => saveNaming.mutate()}>{t("common.save")}</Button>
        </div>
        <p className="mt-2 text-xs text-muted" dir="ltr">PI-1405-0005_پیش‌فاکتور_نفت‌وگازپارس_14050810_v2.pdf · PO-1405-0007_PurchaseOrder_ShanghaiValve_20261101.pdf</p>
        <ErrorNote error={saveNaming.error} />
      </Card>
      <Card title={t("codes.settings.folders")} actions={<Button busy={sync.isPending} onClick={() => sync.mutate()} data-testid="folders-sync">{t("codes.settings.syncNow")}</Button>}>
        {folders.data && (
          <div className="flex flex-col gap-1 text-sm" data-testid="folder-status" data-mode={folders.data.mode ?? ""}>
            <p><span className="text-muted">{t("codes.settings.folderRoot")}:</span> <bdi dir="ltr">{folders.data.root}</bdi></p>
            <p>{folders.data.mode === "copy" ? <Badge tone="warning">{t("codes.settings.copies")}</Badge> : <Badge tone="success">{t("codes.settings.hardlinks")}</Badge>}</p>
            {folders.data.at && <p className="text-xs text-muted">{t("codes.settings.lastSync", { at: f.date(folders.data.at, true), cases: folders.data.cases ?? 0 })}</p>}
            <p className="text-xs text-muted">{t("codes.settings.folderHint")}</p>
          </div>
        )}
        <ErrorNote error={sync.error} />
      </Card>
    </div>
  );
}
