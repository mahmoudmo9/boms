/** The deal's profit table (v0.8.0): planned, actual, variance and variance % by line kind, in the deal currency and
 * in rials; the FX effect, VAT summary, unrealized amounts and the cost of money as information lines. */
import { useTranslation } from "react-i18next";

import { Badge, Card, KpiTile, ProfitBridge, Stat } from "../../../design/components";
import { profitBridge, profitLines, signed, varianceTone, type Profit } from "../../../lib/finance";
import { useFormat } from "../../../lib/prefs";

export function ProfitTable({ profit }: { profit: Profit }) {
  const { t } = useTranslation();
  const f = useFormat();
  const both = profit.deal_currency !== profit.base_currency;
  const num = (v: string | null | undefined) => (v === null || v === undefined ? "—" : f.num(v));
  const lines = profitLines(profit);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="profit-table">
        <thead className="text-xs text-muted">
          <tr>
            <th className="px-2 py-1.5 text-start">{t("finance.profit.kind")}</th>
            <th className="px-2 py-1.5 text-end">{t("finance.profit.planned")} ({profit.deal_currency})</th>
            <th className="px-2 py-1.5 text-end">{t("finance.profit.actual")} ({profit.deal_currency})</th>
            <th className="px-2 py-1.5 text-end">{t("finance.profit.variance")}</th>
            <th className="px-2 py-1.5 text-end">%</th>
            {both && <th className="px-2 py-1.5 text-end">{t("finance.profit.actual")} ({profit.base_currency})</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {lines.map((l) => {
            const tone = varianceTone(l.variance?.deal, l.side === "cost" ? "cost" : "revenue");
            const strong = l.key === "cost_total" || l.key === "profit" || l.key === "revenue";
            return (
              <tr key={l.key} data-testid={`profit-row-${l.key}`} className={strong ? "font-medium" : ""}>
                <td className="px-2 py-1.5">
                  {t(`finance.profit.lines.${l.key}`)}
                  {l.estimated && <span className="ms-1"><Badge tone="warning">{t("finance.profit.estimated")}</Badge></span>}
                  {l.unrealized && <span className="ms-1"><Badge>{t("finance.profit.unrealized")}</Badge></span>}
                </td>
                <td className="px-2 py-1.5 text-end tabular-nums"><bdi dir="ltr">{num(l.planned?.deal)}</bdi></td>
                <td className="px-2 py-1.5 text-end tabular-nums"><bdi dir="ltr">{num(l.actual?.deal)}</bdi></td>
                <td className={`px-2 py-1.5 text-end tabular-nums ${tone === "danger" ? "text-danger" : tone === "success" ? "text-success" : ""}`}
                  data-tone={tone}><bdi dir="ltr">{signed(l.variance?.deal, f.num)}</bdi></td>
                <td className="px-2 py-1.5 text-end tabular-nums"><bdi dir="ltr">{l.percent === null ? "" : `${signed(l.percent, f.num)}%`}</bdi></td>
                {both && <td className="px-2 py-1.5 text-end tabular-nums"><bdi dir="ltr">{num(l.actual?.base)}</bdi></td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** v0.10.0 (ProFinance): the deal's figures as tiles and the bridge from planned to actual profit. */
export function ProfitBridgeCard({ profit }: { profit: Profit }) {
  const { t } = useTranslation();
  const f = useFormat();
  const cur = profit.deal_currency;
  const bridge = profitBridge(profit, (key) => (key === "plan" ? t("finance.bridge.plan") : key === "actual" ? t("finance.bridge.actual")
    : key === "other" ? t("finance.bridge.other") : t(`finance.profit.lines.${key}`)));
  const estimatedParts = profit.expected ? Number(profit.expected.estimated.goods) + Number(profit.expected.estimated.planned_costs) : 0;
  return (
    <section className="flex flex-col gap-4" data-testid="profit-overview">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile label={profit.frozen ? t("finance.profit.final") : t("finance.profit.soFar")} value={f.num(profit.profit.actual.deal, 0)} unit={<bdi dir="ltr">{cur}</bdi>}
          tone={Number(profit.profit.actual.deal) < 0 ? "danger" : "neutral"} emphasis testId="tile-so-far"
          note={profit.margin_percent.actual !== null ? t("finance.bridge.marginNote", { margin: f.num(profit.margin_percent.actual, 1), markup: f.num(profit.markup_percent.actual ?? "0", 1) }) : undefined} />
        {profit.expected && <KpiTile label={t("finance.profit.expected")} value={f.num(profit.expected.profit, 0)} unit={<bdi dir="ltr">{cur}</bdi>} estimated={estimatedParts !== 0} testId="tile-expected"
          note={profit.expected.margin_percent !== null ? t("finance.bridge.expectedNote", { margin: f.num(profit.expected.margin_percent, 1) }) : undefined} />}
        <KpiTile label={t("finance.bridge.planned")} value={profit.profit.planned?.deal != null ? f.num(profit.profit.planned.deal, 0) : "—"} unit={<bdi dir="ltr">{cur}</bdi>}
          note={profit.margin_percent.planned !== null ? t("finance.bridge.marginNote", { margin: f.num(profit.margin_percent.planned, 1), markup: f.num(profit.markup_percent.planned ?? "0", 1) }) : t("finance.profit.noPlan")} />
        <KpiTile label={t("finance.profit.fxEffect")} value={signed(profit.fx_effect.base, (v) => f.num(v, 0))} unit={<bdi dir="ltr">{profit.base_currency}</bdi>}
          tone={Number(profit.fx_effect.base) < 0 ? "danger" : Number(profit.fx_effect.base) > 0 ? "success" : "neutral"} note={t("finance.bridge.fxNote")} />
      </div>
      <Card title={t("finance.bridge.title")} subtitle={t("finance.bridge.subtitle", { cur })} testId="bridge-card">
        {bridge ? (
          <ProfitBridge label={t("finance.bridge.title")} steps={bridge.steps} estimated={bridge.estimated} format={(n) => f.num(Math.round(n), 0)} />
        ) : <p className="text-sm text-muted">{t("finance.profit.noPlan")}</p>}
      </Card>
    </section>
  );
}

export function ProfitCard({ profit }: { profit: Profit }) {
  const { t } = useTranslation();
  const f = useFormat();
  const pct = (v: string | null) => (v === null ? "—" : `${f.num(v)}%`);
  const base = profit.base_currency;
  return (
    <Card title={<span className="flex items-center gap-2">{t("finance.profit.title")}
      <Badge tone={profit.frozen ? "neutral" : "accent"}>{profit.frozen ? t("finance.profit.final") : t("finance.profit.soFar")}</Badge></span>}>
      <div className="flex flex-col gap-3" data-testid="profit-card">
        {profit.plan && "error" in profit.plan && <p className="text-sm text-warning">{t("finance.profit.noPlan")}</p>}
        <div className="grid gap-2 sm:grid-cols-4">
          <Stat label={t("finance.profit.margin")} value={<span>{pct(profit.margin_percent.actual)} <span className="text-xs text-muted">/ {pct(profit.margin_percent.planned)}</span></span>} />
          <Stat label={t("finance.profit.markup")} value={<span>{pct(profit.markup_percent.actual)} <span className="text-xs text-muted">/ {pct(profit.markup_percent.planned)}</span></span>} />
          <Stat label={t("finance.profit.fxEffect")} tone={Number(profit.fx_effect.base) < 0 ? "danger" : Number(profit.fx_effect.base) > 0 ? "success" : undefined}
            value={<bdi dir="ltr" data-testid="fx-effect">{signed(profit.fx_effect.base, f.num)} {base}</bdi>} />
          {profit.expected && <Stat label={t("finance.profit.expected")} value={<span data-testid="expected-profit">
            <bdi dir="ltr">{f.num(profit.expected.profit)} {profit.deal_currency}</bdi>
            {profit.expected.margin_percent !== null && <span className="text-xs text-muted"> · {f.num(profit.expected.margin_percent)}%</span>}</span>} />}
        </div>
        <ProfitTable profit={profit} />
        {profit.expected && (Number(profit.expected.estimated.goods) !== 0 || Number(profit.expected.estimated.planned_costs) !== 0) && (
          <p className="text-xs text-warning" data-testid="expected-estimated">{t("finance.profit.expectedEstimated", {
            revenue: f.num(profit.expected.revenue), cost: f.num(profit.expected.cost), goods: f.num(profit.expected.estimated.goods),
            planned: f.num(profit.expected.estimated.planned_costs), cur: profit.deal_currency })}</p>)}
        <div className="grid gap-2 text-sm sm:grid-cols-3" data-testid="vat-summary">
          <span>{t("finance.vat.output")}: <bdi dir="ltr">{f.num(profit.vat.output.base)} {base}</bdi></span>
          <span>{t("finance.vat.input")}: <bdi dir="ltr">{f.num(profit.vat.input.base)} {base}</bdi></span>
          <span>{t("finance.vat.net")}: <bdi dir="ltr">{f.num(profit.vat.net.base)} {base}</bdi></span>
        </div>
        <p className="text-xs text-muted" data-testid="cost-of-money">
          {t("finance.profit.costOfMoney", { actual: f.num(profit.cost_of_money.actual.base), planned: f.num(profit.cost_of_money.planned?.base ?? "0"),
            days: f.num(profit.cost_of_money.days), cur: base })}
        </p>
        {(Number(profit.unrealized.revenue) !== 0 || Number(profit.unrealized.cost) !== 0) && (
          <p className="text-xs text-muted">{t("finance.profit.unrealizedNote", { revenue: f.num(profit.unrealized.revenue), cost: f.num(profit.unrealized.cost), cur: base })}</p>)}
        {profit.missing_rates.length > 0 && <p className="text-xs text-danger">{t("finance.profit.missingRates", { list: profit.missing_rates.join(", ") })}</p>}
      </div>
    </Card>
  );
}
