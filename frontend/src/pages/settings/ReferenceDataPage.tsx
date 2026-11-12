/** Settings → «داده‌های مرجع» (v0.9.0): each dataset with its rows, active rows and last import (release, report), and
 * import from a file the owner downloaded (UN/LOCODE, ISO 20275 ELF, OurAirports …). Nothing is fetched from the internet. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, ErrorNote, Field, Input, Loading, PageHeader, Select } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";

type Dataset = { dataset: string; rows: number; active: number; verified?: number;
  last_import: null | { dataset: string; release: string | null; at: string; report: Record<string, number> } };
type Report = { dataset: string; inserted: number; updated: number; deactivated: number; unchanged: number; rejected: number; rejections: { row: number; reason: string }[] };

export function ReferenceDataPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const summary = useQuery({ queryKey: ["reference", "summary"], queryFn: () => api<{ datasets: Dataset[]; importable: string[] }>("/api/reference/summary") });
  const [dataset, setDataset] = useState("unlocode");
  const [release, setRelease] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const run = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file!);
      form.append("dataset", dataset);
      if (release) form.append("release", release);
      return api<Report>("/api/reference/import", { method: "POST", form });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reference"] }),
  });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("reference.title")} subtitle={t("reference.subtitle")} />
      <Card title={t("reference.datasets")} padded={false}>
        {summary.isLoading ? <Loading /> : (
          <table className="w-full text-sm" data-testid="reference-summary"><thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
            {["dataset", "rows", "active", "release", "lastImport"].map((h) => <th key={h} className="p-2 text-start">{t(`reference.col.${h}`)}</th>)}
          </tr></thead><tbody>{(summary.data?.datasets ?? []).map((d) => (
            <tr key={d.dataset} className="border-b border-line">
              <td className="p-2">{t(`reference.ds.${d.dataset}`)}{d.verified !== undefined && <span className="text-xs text-muted"> · {t("reference.verified", { count: d.verified })}</span>}</td>
              <td className="p-2">{f.num(d.rows)}</td><td className="p-2">{f.num(d.active)}</td>
              <td className="p-2 font-mono text-xs" dir="ltr">{d.last_import?.release ?? "—"}</td>
              <td className="p-2 text-xs">{d.last_import ? `${f.date(d.last_import.at, true)} · +${d.last_import.report.inserted ?? 0} ~${d.last_import.report.updated ?? 0}` : "—"}</td>
            </tr>))}</tbody></table>
        )}
      </Card>
      <Card title={t("reference.importTitle")}>
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t("reference.dataset")} htmlFor="ref-ds">
            <Select id="ref-ds" className="w-60" value={dataset} onChange={(e) => setDataset(e.target.value)}>
              {(summary.data?.importable ?? []).map((d) => <option key={d} value={d}>{t(`reference.ds.${d}`, { defaultValue: d })}</option>)}
            </Select>
          </Field>
          <Field label={t("reference.release")} htmlFor="ref-rel"><Input id="ref-rel" dir="ltr" className="w-32" value={release} onChange={(e) => setRelease(e.target.value)} placeholder="2024-2" /></Field>
          <Field label={t("reference.file")} htmlFor="ref-file"><input id="ref-file" type="file" accept=".csv,.gz,.zip,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <Button variant="primary" disabled={!file} busy={run.isPending} onClick={() => run.mutate()}>{t("reference.import")}</Button>
        </div>
        <p className="mt-2 text-xs text-muted">{t("reference.importHint")}</p>
        {run.data && (
          <p className="mt-2 text-sm" data-testid="reference-report">{t("reference.report", { ...run.data })}</p>
        )}
        <ErrorNote error={run.error} />
      </Card>
    </div>
  );
}
