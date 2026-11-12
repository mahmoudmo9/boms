/** The case page's header and side column (v0.10.0, reference ProCase / light Case): the deal path stepper, progress
 * and margin rings, the money summary, and beside the tabs the key figures, the open tasks, the route of a shipment
 * and the latest history. Data: the case, its costing, quotes, execution and tasks (nothing new). */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Card, DescriptionList, EmptyState, ProgressRing, RouteLine, Stepper, Timeline } from "../../design/components";
import { api, type Page } from "../../lib/api";
import { pathPercent, pathSteps } from "../../lib/dealPath";
import { useFormat } from "../../lib/prefs";
import type { CaseCosting, CaseDetail, CaseQuotes, EventItem, ShipmentRow } from "../../lib/types";
import type { TaskRow } from "../../lib/tasks";
import { useExecution } from "./execution/shared";
import { Money } from "../sourcing/shared";

export function DealPath({ c }: { c: CaseDetail }) {
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
      <div className="flex shrink-0 items-center justify-center gap-6">
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
      </div>
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

export function CaseSide({ c }: { c: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const costing = useQuery({ queryKey: ["costing", c.id], queryFn: () => api<CaseCosting>(`/api/cases/${c.id}/costing`) });
  const quotes = useQuery({ queryKey: ["case-quotes", c.id], queryFn: () => api<CaseQuotes>(`/api/cases/${c.id}/quotes`) });
  const tasks = useQuery({ queryKey: ["case-tasks", c.id, "open"], queryFn: () => api<TaskRow[]>(`/api/cases/${c.id}/tasks`) });
  const history = useQuery({ queryKey: ["events", "case", c.id, "side"],
    queryFn: () => api<Page<EventItem>>("/api/events", { query: { entity_type: "case", entity_id: c.id, page_size: 6 } }) });
  const ex = useExecution(c.id);
  const cur = costing.data?.current;
  const latest = quotes.data?.summary.latest;
  const cash = Object.entries(ex.data?.header?.cash ?? {});
  const shipment = (ex.data?.shipments ?? []).find((s) => (s.route?.stops?.length ?? 0) >= 2);
  return (
    <>
      <Card title={t("case.side.figures")} testId="case-figures">
        <DescriptionList columns={1} items={[
          { label: t("sourcing.decision.exposure"), value: c.exposure_estimate ? <Money amount={c.exposure_estimate} currency={c.exposure_currency} /> : null },
          { label: t("costing.computedExposure"), value: cur?.exposure !== undefined ? <Money amount={cur.exposure} currency={cur.currency} /> : null },
          { label: t("case.side.marginMarkup"), value: cur?.margin_percent ? <span className="tabular-nums">{f.num(cur.margin_percent, 1)}٪ · {f.num(cur.markup_percent ?? "", 1)}٪</span> : null },
          { label: t("quotes.latest"), value: latest ? <span><bdi dir="ltr">{latest.number}</bdi> · {t(`sourcing.status.quote.${latest.status}`, { defaultValue: latest.status })}</span> : null },
          ...cash.map(([currency, v]) => ({ label: `${t("execution.cash.net")} (${currency})`, value: <Money amount={v.net_tied_up} currency={currency} /> })),
          { label: t("case.side.opened"), value: <span className="tabular-nums">{f.date(c.created_at)}</span> },
        ]} />
      </Card>
      <Card title={t("case.side.tasks")} actions={<Link to={`?tab=tasks`} className="text-sm text-accent hover:underline">{t("case.side.all")}</Link>} testId="case-open-tasks">
        {(tasks.data ?? []).length === 0 ? <EmptyState compact icon="checkCircle">{t("tasks.none")}</EmptyState> : (
          <ul className="flex flex-col gap-2.5">{(tasks.data ?? []).slice(0, 5).map((task) => (
            <li key={task.id} className="flex items-start justify-between gap-3 text-sm">
              <span className="min-w-0"><bdi>{task.title}</bdi></span>
              <span className={`shrink-0 text-xs tabular-nums ${task.due_on < new Date().toISOString().slice(0, 10) ? "text-danger" : "text-muted"}`}>{f.day(task.due_on)}</span>
            </li>))}</ul>
        )}
      </Card>
      {shipment && <RouteCard shipment={shipment} />}
      <Card title={t("case.side.story")} actions={<Link to={`?tab=history`} className="text-sm text-accent hover:underline">{t("case.side.all")}</Link>} testId="case-story">
        {(history.data?.items ?? []).length === 0 ? <EmptyState compact icon="clock">{t("case.side.noHistory")}</EmptyState> : (
          <Timeline label={t("case.side.story")} items={(history.data?.items ?? []).map((e) => ({
            key: String(e.id), when: f.date(e.occurred_at), title: t(`events.actions.${e.action}`, { defaultValue: e.action }), detail: e.actor, state: "done" as const }))} />
        )}
      </Card>
    </>
  );
}
