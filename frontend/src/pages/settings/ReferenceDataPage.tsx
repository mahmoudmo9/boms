/** Settings → «داده‌های مرجع» (v0.9.0): each dataset with its rows, active rows and last import (release, report), and
 * import from a file the owner downloaded (UN/LOCODE, ISO 20275 ELF, OurAirports …). Nothing is fetched from the internet. */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Card, Isolated, Loading, PageHeader } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import { ReferenceImport } from "./ReferenceImport";

type Dataset = { dataset: string; rows: number; active: number; verified?: number;
  last_import: null | { dataset: string; release: string | null; at: string; report: Record<string, number> } };

export function ReferenceDataPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const summary = useQuery({ queryKey: ["reference", "summary"], queryFn: () => api<{ datasets: Dataset[]; importable: string[] }>("/api/reference/summary") });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("reference.title")} subtitle={t("reference.subtitle")} />
      <Card title={t("reference.datasets")} padded={false}>
        {summary.isLoading ? <Loading /> : (
          <table className="w-full text-sm" data-testid="reference-summary"><thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
            {["dataset", "rows", "active", "release", "lastImport"].map((h) => <th key={h} className="p-2 text-start">{t(`reference.col.${h}`)}</th>)}
          </tr></thead><tbody>{(summary.data?.datasets ?? []).map((d) => (
            <tr key={d.dataset} className="border-b border-line">
              <td className="p-2"><Isolated text={t(`reference.ds.${d.dataset}`)} />{d.verified !== undefined && <span className="text-xs text-muted"> · {t("reference.verified", { count: d.verified })}</span>}</td>
              <td className="p-2">{f.num(d.rows)}</td><td className="p-2">{f.num(d.active)}</td>
              <td className="p-2 font-mono text-xs"><bdi dir="ltr">{d.last_import?.release ?? "—"}</bdi></td>
              <td className="p-2 text-xs">{d.last_import ? `${f.date(d.last_import.at, true)} · ${t("reference.importedCounts", { inserted: f.num(d.last_import.report.inserted ?? 0), updated: f.num(d.last_import.report.updated ?? 0) })}` : "—"}</td>
            </tr>))}</tbody></table>
        )}
      </Card>
      <ReferenceImport />
    </div>
  );
}
