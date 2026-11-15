/** The case page's header and side column (v0.10.0, reference ProCase / light Case): the deal path stepper, progress
 * and margin rings, the money summary, and beside the tabs the key figures, the open tasks, the route of a shipment
 * and the latest history. Data: the case, its costing, quotes, execution and tasks (nothing new). */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Card, ProgressRing, Stepper } from "../../design/components";
import { RouteLine } from "../../design/components/charts";
import { api } from "../../lib/api";
import { pathPercent, pathSteps } from "../../lib/dealPath";
import { useFormat } from "../../lib/prefs";
import type { CaseCosting, CaseDetail, ShipmentRow } from "../../lib/types";
import { useExecution } from "./execution/shared";

export function DealPath({ c, rings = true }: { c: CaseDetail; rings?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ex = useExecution(c.id);
  const costing = useQuery({ queryKey: ["costing", c.id], queryFn: () => api<CaseCosting>(`/api/cases/${c.id}/costing`) });
  const statuses = c.items.map((i) => i.status);
  const shipping = (ex.data?.shipments.length ?? 0) > 0;
  const margin = costing.data?.current?.margin_percent;
  return (
    <div className="flex flex-col gap-5 rounded-3xl border border-line bg-surface p-5 lg:flex-row lg:items-center" data-testid="deal-path">
      <div className="min-w-0 flex-1"><Stepper label={t("case.path.label")} steps={pathSteps(statuses, c.status, shipping).map((s) => ({ ...s, label: t(`case.path.${s.key}`) }))} /></div>
      {rings && <div className="flex shrink-0 items-center justify-center gap-6">
        <div className="flex flex-col items-center gap-1.5">
          <ProgressRing value={pathPercent(statuses, c.status, shipping)} size={84} label={t("case.path.progress")}>
            <span className="text-md text-title tabular-nums">{f.num(pathPercent(statuses, c.status, shipping))}٪</span>
          </ProgressRing>
          <span className="text-xs text-muted">{t("case.path.progress")}</span>
        </div>
        {margin != null && (
          <div className="flex flex-col items-center gap-1.5">
            <ProgressRing value={Math.max(0, Math.min(100, Number(margin)))} size={84} tone="success" label={t("costing.pricing.margin")}>
              <span className="text-md text-title tabular-nums">{f.num(margin, 1)}٪</span>
            </ProgressRing>
            <span className="text-xs text-muted">{t("costing.pricing.margin")}</span>
          </div>
        )}
      </div>}
    </div>
  );
}

export function routeStops(s: ShipmentRow, lang: string, day: (iso: string) => string) {
  return (s.route?.stops ?? []).map((x) => ({ key: x.location_id + x.role, name: (lang === "fa" ? x.name_fa || x.name : x.name) ?? x.code, code: x.code,
    when: x.at ? day(x.at) : null, state: x.state }));
}

function RouteCard({ shipment }: { shipment: ShipmentRow }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const stops = routeStops(shipment, i18n.language, (iso) => f.date(iso));
  if (stops.length < 2) return null;
  return (
    <Card title={t("case.side.route")} subtitle={shipment.code ?? undefined} padded testId="case-route">
      <RouteLine label={t("case.side.route")} stops={stops} rtl={i18n.language === "fa"} height={170} caption={t("case.side.routeCaption")} />
    </Card>
  );
}

/** v0.10.1 (4.2): the route card of the case's shipment that has located events, when there is one. */
export function CaseRoute({ c }: { c: CaseDetail }) {
  const ex = useExecution(c.id);
  const shipment = (ex.data?.shipments ?? []).find((s) => (s.route?.stops?.length ?? 0) >= 2);
  return shipment ? <RouteCard shipment={shipment} /> : null;
}
