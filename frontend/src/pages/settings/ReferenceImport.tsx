/** v0.10.1 section 0.2: importing an official reference file — upload, a preview (dry run) that changes nothing, then
 * the import as a background job with live progress (stage, rows read, time left) and «لغو». BOMS recognises the file
 * (UN/LOCODE release or GLEIF ELF list) from its content. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, DescriptionList, ErrorNote, Field, FileDrop, InlineAlert, Input, ProgressBar, Status } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import { type ImportRun, percentDone, reasonKey, RUNNING, secondsLeft } from "../../lib/reference";

function useNowTick(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

export function ReferenceImport() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["reference", "imports"], queryFn: () => api<ImportRun[]>("/api/reference/imports", { query: { limit: 1 } }) });
  const latest = runs.data?.[0] ?? null;
  const [dismissed, setDismissed] = useState<string | null>(null);
  const run = latest && latest.id !== dismissed ? latest : null;
  const running = !!run && RUNNING.has(run.status);
  const now = useNowTick(running);
  const [release, setRelease] = useState<string | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["reference"] });
  const start = useMutation({
    mutationFn: (file: File) => { const form = new FormData(); form.append("file", file); return api<ImportRun>("/api/reference/imports", { method: "POST", form }); },
    onSuccess: () => { setDismissed(null); setRelease(null); refresh(); },
  });
  const confirm = useMutation({ mutationFn: () => api(`/api/reference/imports/${run!.id}/confirm`, { method: "POST", body: { release: release ?? run!.release } }), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => api(`/api/reference/imports/${run!.id}/cancel`, { method: "POST" }), onSuccess: refresh });
  const p = run?.preview;
  const left = run && running ? secondsLeft(run, now) : null;
  const pct = run && running ? percentDone(run) : null;
  const reason = (r: string) => { const k = reasonKey(r); return k.key ? t(k.key, { name: k.value }) : k.value; };
  return (
    <Card title={t("reference.importTitle")} subtitle={t("reference.importHint")} testId="reference-import">
      <div className="flex flex-col gap-4">
        {!running && run?.status !== "preview_ready" && (
          <FileDrop multiple={false} accept=".csv,.gz,.zip,.txt" busy={start.isPending} testId="reference-file" id="ref-file"
            label={t("reference.dropLabel")} hint={t("reference.dropHint")} onFiles={(files) => files[0] && start.mutate(files[0])} />
        )}
        {run && (
          <div className="flex flex-col gap-3 rounded-xl border border-line bg-surface-2 p-4" data-testid="import-run" data-status={run.status}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-title">{t(`reference.ds.${run.dataset}`)}</span>
              <bdi dir="ltr" className="font-mono text-xs text-muted">{run.file_name}</bdi>
              <Status tone={run.status === "done" ? "success" : run.status.endsWith("failed") ? "danger" : run.status === "cancelled" || run.status === "discarded" ? "neutral" : "accent"}>
                {t(`reference.status.${run.status}`)}</Status>
            </div>
            {running && (
              <div className="flex flex-col gap-2" data-testid="import-progress">
                <ProgressBar label={t("reference.progress")} value={pct} />
                <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                  <span>{t(`reference.stage.${run.stage ?? "queued"}`, { defaultValue: run.stage ?? "" })}</span>
                  <span>{t("reference.rowsRead", { n: f.num(run.rows_read), total: run.rows_total ? f.num(run.rows_total) : "…" })}</span>
                  {left !== null && <span>{t("reference.timeLeft", { s: f.num(left) })}</span>}
                </p>
                <div><Button size="sm" busy={cancel.isPending} disabled={run.cancel_requested} onClick={() => cancel.mutate()} data-testid="import-cancel">
                  {run.cancel_requested ? t("reference.cancelling") : t("common.cancel")}</Button></div>
              </div>
            )}
            {p && run.status === "preview_ready" && (
              <div className="flex flex-col gap-3" data-testid="import-preview">
                {p.chosen_other && <InlineAlert tone="info">{t("reference.detected", { dataset: t(`reference.ds.${run.dataset}`) })}</InlineAlert>}
                {p.warnings.includes("mostly_rejected") && <InlineAlert tone="danger">{t("reference.mostlyRejected", { n: f.num(p.rejected), total: f.num(p.rows_read) })}</InlineAlert>}
                {p.warnings.includes("partial_release") && <InlineAlert tone="warning">{t("reference.partial")}</InlineAlert>}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {(["insert", "update", "deactivate", "unchanged", "rejected"] as const).map((k) => (
                    <div key={k} className="flex flex-col gap-0.5 rounded-lg border border-line bg-surface p-3">
                      <span className="text-xs text-muted">{t(`reference.preview.${k}`)}</span>
                      <span className={`text-lg font-semibold tabular-nums ${k === "rejected" && p.rejected ? "text-danger" : "text-title"}`}>{f.num(p[k])}</span>
                    </div>
                  ))}
                </div>
                <DescriptionList items={[
                  { label: t("reference.encoding"), value: <bdi dir="ltr">{[...new Set(Object.values(p.encodings))].join(", ")}</bdi> },
                  { label: t("reference.parts"), value: <bdi dir="ltr">{p.parts.join(" · ")}</bdi> },
                ]} />
                {p.reasons.length > 0 && (
                  <div className="flex flex-col gap-1.5" data-testid="import-reasons">
                    <span className="text-xs font-medium text-muted">{t("reference.reasonsTitle")}</span>
                    <ul className="flex flex-col gap-1 text-sm">{p.reasons.map((r) => <li key={r.reason}>{reason(r.reason)}: <b className="tabular-nums">{f.num(r.count)}</b></li>)}</ul>
                    <details className="text-xs text-muted"><summary className="cursor-pointer">{t("reference.examples", { n: f.num(p.examples.length) })}</summary>
                      <ul className="mt-1 flex flex-col gap-0.5">{p.examples.map((e, i) => <li key={i}><bdi dir="ltr">{e.part} #{e.row}</bdi> — {reason(e.reason)}</li>)}</ul></details>
                  </div>
                )}
                <div className="flex flex-wrap items-end gap-2">
                  <Field label={t("reference.release")} htmlFor="ref-rel" hint={run.release ? t("reference.releaseFromName") : undefined}>
                    <Input id="ref-rel" dir="ltr" className="w-32" value={release ?? run.release ?? ""} onChange={(e) => setRelease(e.target.value)} placeholder="2025-1" />
                  </Field>
                  <Button variant="primary" busy={confirm.isPending} disabled={p.records === 0} onClick={() => confirm.mutate()} data-testid="import-confirm">{t("reference.confirm")}</Button>
                  <Button busy={cancel.isPending} onClick={() => cancel.mutate()}>{t("reference.discard")}</Button>
                </div>
              </div>
            )}
            {run.status === "done" && run.report && (
              <div className="flex flex-col gap-2" data-testid="reference-report">
                <p className="text-sm">{t("reference.report", { inserted: f.num(run.report.inserted), updated: f.num(run.report.updated),
                  deactivated: f.num(run.report.deactivated), rejected: f.num(run.report.rejected) })}</p>
                <p className="text-xs text-muted">{t("reference.took", { s: f.num(run.report.seconds) })}</p>
                <CuratedCheck notes={run.report.notes} />
              </div>
            )}
            {run.error && <InlineAlert tone="danger"><bdi dir="ltr">{run.error}</bdi></InlineAlert>}
            {!running && run.status !== "preview_ready" && <div><Button size="sm" variant="ghost" onClick={() => setDismissed(run.id)}>{t("reference.newImport")}</Button></div>}
          </div>
        )}
        <ErrorNote error={start.error ?? confirm.error ?? cancel.error ?? runs.error} />
      </div>
    </Card>
  );
}

/** After a UN/LOCODE import: the curated rows matched, the mismatches and those the file does not have. */
function CuratedCheck({ notes }: { notes: Record<string, unknown> | undefined }) {
  const { t } = useTranslation();
  const f = useFormat();
  if (!notes || notes.curated_matched === undefined) return null;
  const mismatches = (notes.curated_mismatches as { unlocode: string; field: string; curated: string; official: string }[]) ?? [];
  const missing = (notes.curated_not_in_file as string[]) ?? [];
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3" data-testid="curated-check">
      <p className="text-sm">{t("reference.curatedMatched", { n: f.num(notes.curated_matched as number) })}</p>
      {mismatches.length > 0 && (
        <table className="w-full text-xs"><caption className="mb-1 text-start text-sm font-medium text-warning">{t("reference.mismatches", { n: f.num(mismatches.length) })}</caption>
          <thead><tr className="text-muted">{["code", "field", "curated", "official"].map((h) => <th key={h} scope="col" className="px-2 py-1 text-start font-medium">{t(`reference.mismatch.${h}`)}</th>)}</tr></thead>
          <tbody>{mismatches.map((m, i) => <tr key={i} className="border-t border-line"><td className="px-2 py-1"><bdi dir="ltr">{m.unlocode}</bdi></td>
            <td className="px-2 py-1">{t(`reference.mismatch.fields.${m.field}`, { defaultValue: m.field })}</td><td className="px-2 py-1"><bdi>{m.curated}</bdi></td><td className="px-2 py-1"><bdi>{m.official}</bdi></td></tr>)}</tbody></table>
      )}
      {missing.length > 0 && <p className="text-xs text-muted">{t("reference.notInFile")} <bdi dir="ltr">{missing.join(", ")}</bdi></p>}
    </div>
  );
}
