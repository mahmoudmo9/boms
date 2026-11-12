/** v0.10.0 (ProFinance): the deal's cash flow by month from its open payment milestones (sales order milestones in,
 * purchase order milestones out); overdue and undated ones are named beside the chart. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Card, CashFlow, EmptyState, Segmented, Status } from "../../../design/components";
import { calendarMonth, dealCashFlow } from "../../../lib/dealCash";
import { toDateString } from "../../../lib/followups";
import { useFormat } from "../../../lib/prefs";
import type { CaseExecution } from "../../../lib/types";

export function DealCashCard({ execution }: { execution: CaseExecution | undefined }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [currency, setCurrency] = useState<string | null>(null);
  if (!execution) return null;
  const milestones = [...execution.sales_orders.flatMap((o) => o.milestones), ...execution.milestones_out];
  if (milestones.length === 0) return null;          // no order yet: nothing is scheduled
  const flow = dealCashFlow(milestones, toDateString(new Date()), calendarMonth(f.calendar, f.lang));
  const shown = flow.currencies.find((c) => c.currency === currency) ?? flow.currencies[0] ?? null;
  return (
    <Card title={t("finance.dealCash.title")} subtitle={t("finance.dealCash.subtitle")} testId="deal-cash"
      actions={flow.currencies.length > 1 ? <Segmented size="sm" label={t("ds.money.currency")} value={shown?.currency ?? ""} onChange={setCurrency}
        options={flow.currencies.map((c) => ({ value: c.currency, label: <bdi dir="ltr">{c.currency}</bdi> }))} /> : undefined}>
      {!shown || shown.points.length === 0 ? <EmptyState compact icon="coins">{t("finance.dealCash.empty")}</EmptyState> : (
        <CashFlow label={`${t("finance.dealCash.title")} (${shown.currency})`} format={(n) => f.num(n, 0)} points={shown.points}
          legend={{ cashIn: t("cc.cash.in"), cashOut: t("cc.cash.out"), balance: t("cc.cash.net"), lowest: t("cc.cash.lowest") }} />
      )}
      {((shown && (shown.overdueIn > 0 || shown.overdueOut > 0)) || flow.undated > 0) && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          {shown && (shown.overdueIn > 0 || shown.overdueOut > 0) && <Status tone="warning">
            {t("cc.cash.overdue", { in: f.num(shown.overdueIn, 0), out: f.num(shown.overdueOut, 0), currency: shown.currency })}</Status>}
          {flow.undated > 0 && <span>{t("finance.dealCash.undated", { n: f.num(flow.undated) })}</span>}
        </p>
      )}
    </Card>
  );
}
