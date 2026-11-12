/** Charts of the design system (v0.10.0 section 2): hand-built SVG in token colours. Each chart is one image with an
 * accessible name, and carries a text alternative (a visually hidden table of the same numbers) for screen readers
 * and for anyone who cannot tell the marks apart. Geometry: design/charts.ts. */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { areaPath, bridgeBars, type BridgeStep, cashFlowBars, type CashPoint, lastRecorded, linePath, routeNodes, type RouteStop, scalePoints, smoothPath } from "../charts";

type Fmt = (n: number) => string;

/** The text alternative: a table only assistive technology reads. */
function DataTableAlt({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => (j === 0 ? <th key={j} scope="row">{c}</th> : <td key={j}>{c}</td>))}</tr>)}</tbody>
    </table>
  );
}

/** A trend in a small space. `label` says what it shows; the values are listed for screen readers. */
export function Sparkline({ values, label, width = 280, height = 56, format = String, area = true }: {
  values: number[]; label: string; width?: number; height?: number; format?: Fmt; area?: boolean }) {
  const { t } = useTranslation();
  const points = scalePoints(values, width, height, 3);
  if (points.length === 0) return null;
  const last = points[points.length - 1];
  return (
    <figure className="m-0" data-testid="sparkline">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" role="img"
        aria-label={`${label}: ${t("ds.chart.fromTo", { from: format(values[0]), to: format(values[values.length - 1]) })}`}>
        {area && points.length > 1 && <path d={areaPath(points, height)} className="fill-chart-1 opacity-15" />}
        {points.length > 1 && <path d={linePath(points)} fill="none" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" className="stroke-chart-1" />}
        <circle cx={last.x} cy={last.y} r={3} className="fill-chart-1" />
      </svg>
      <DataTableAlt caption={label} head={["#", label]} rows={values.map((v, i) => [i + 1, format(v)])} />
    </figure>
  );
}

/** A few bars to compare (months, categories); one can be highlighted. */
export function Bars({ items, label, height = 64, format = String, highlight }: {
  items: { key: string; label: string; value: number }[]; label: string; height?: number; format?: Fmt; highlight?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <figure className="m-0" data-testid="bars">
      <div role="img" aria-label={`${label}: ${items.map((i) => `${i.label} ${format(i.value)}`).join("، ")}`} className="flex items-end gap-1.5" style={{ height }}>
        {items.map((i) => (
          <span key={i.key} title={`${i.label}: ${format(i.value)}`} style={{ height: `${Math.max((i.value / max) * 100, 4)}%` }}
            className={`min-w-2 flex-1 rounded-sm ${i.key === highlight ? "bg-chart-1" : "bg-chart-track"}`} />
        ))}
      </div>
      <DataTableAlt caption={label} head={["", label]} rows={items.map((i) => [i.label, format(i.value)])} />
    </figure>
  );
}

/** The profit bridge: plan -> FX effect -> cost groups -> actual. Totals in the accent, gains and losses with their
 * sign, a mark («+» / «−») and their own colour, so the direction is never by colour alone. */
export function ProfitBridge({ steps, label, format = String, height = 220, estimated = [] }: {
  steps: BridgeStep[]; label: string; format?: Fmt; height?: number; estimated?: string[] }) {
  const { t } = useTranslation();
  const width = Math.max(steps.length * 110, 320);
  const plot = height - 58;
  const bars = bridgeBars(steps, width, plot);
  const signed = (s: BridgeStep) => (s.kind === "delta" ? `${s.value >= 0 ? "+" : "−"}${format(Math.abs(s.value))}` : format(s.value));
  return (
    <figure className="m-0 overflow-x-auto" data-testid="profit-bridge">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={`${label}: ${steps.map((s) => `${s.label} ${signed(s)}`).join("، ")}`} style={{ minWidth: width * 0.7 }}>
        <g transform="translate(0 22)">
          {bars.map((b, i) => (
            <g key={b.key} data-kind={b.kind} data-positive={b.positive}>
              {i > 0 && <line x1={bars[i - 1].x + bars[i - 1].width} x2={b.x} y1={b.kind === "total" ? bars[i - 1].y + (bars[i - 1].positive || bars[i - 1].kind === "total" ? 0 : bars[i - 1].height) : (b.positive ? b.y + b.height : b.y)}
                y2={b.kind === "total" ? bars[i - 1].y + (bars[i - 1].positive || bars[i - 1].kind === "total" ? 0 : bars[i - 1].height) : (b.positive ? b.y + b.height : b.y)} strokeDasharray="3 3" className="stroke-chart-grid" />}
              <rect x={b.x} y={b.y} width={b.width} height={b.height} rx={5}
                className={b.kind === "total" ? "fill-chart-1" : b.positive ? "fill-chart-in" : "fill-chart-out"} opacity={estimated.includes(b.key) ? 0.55 : 1}
                strokeDasharray={estimated.includes(b.key) ? "4 3" : undefined} />
              <text x={b.x + b.width / 2} y={b.y - 7} textAnchor="middle" className="fill-title text-xs tabular-nums" direction="ltr">{signed(b)}</text>
              <text x={b.x + b.width / 2} y={plot + 18} textAnchor="middle" className="fill-muted text-xs">{b.label}</text>
              {estimated.includes(b.key) && <text x={b.x + b.width / 2} y={plot + 33} textAnchor="middle" className="fill-warning text-2xs">{t("ds.kpi.estimated")}</text>}
            </g>
          ))}
        </g>
      </svg>
      <DataTableAlt caption={label} head={[t("ds.chart.step"), t("ds.chart.amount")]} rows={steps.map((s) => [s.label + (estimated.includes(s.key) ? ` (${t("ds.kpi.estimated")})` : ""), signed(s)])} />
    </figure>
  );
}

/** Cash in and out per period with the running balance; the lowest balance is marked and named. */
export function CashFlow({ points, label, opening = 0, format = String, height = 220, legend }: {
  points: CashPoint[]; label: string; opening?: number; format?: Fmt; height?: number; legend?: { cashIn: string; cashOut: string; balance: string; lowest: string } }) {
  const { t } = useTranslation();
  const names = legend ?? { cashIn: t("ds.chart.cashIn"), cashOut: t("ds.chart.cashOut"), balance: t("ds.chart.balance"), lowest: t("ds.chart.lowest") };
  const width = Math.max(points.length * 64, 320);
  const plot = height - 34;
  const { bars, zeroY, balancePath } = cashFlowBars(points, width, plot, opening);
  const low = bars.find((b) => b.lowest);
  return (
    <figure className="m-0 flex flex-col gap-2" data-testid="cash-flow">
      <figcaption className="flex flex-wrap items-center justify-end gap-4 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-0.5 w-3 bg-chart-in" />{names.cashIn}</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-0.5 w-3 bg-chart-out" />{names.cashOut}</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-0.5 w-3 bg-chart-line" />{names.balance}</span>
      </figcaption>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" style={{ minWidth: width * 0.7 }}
          aria-label={`${label}. ${low ? `${names.lowest}: ${low.label}, ${format(low.balance)}` : ""}`}>
          <line x1={0} x2={width} y1={zeroY} y2={zeroY} className="stroke-chart-grid" />
          {bars.map((b) => (
            <g key={b.key}>
              {b.inHeight > 0 && <rect x={b.x} y={b.inY} width={b.width} height={b.inHeight} rx={3} className="fill-chart-in opacity-80" />}
              {b.outHeight > 0 && <rect x={b.x} y={b.outY} width={b.width} height={b.outHeight} rx={3} className="fill-chart-out opacity-80" />}
              <text x={b.x + b.width / 2} y={height - 8} textAnchor="middle" className="fill-muted text-2xs">{b.label}</text>
            </g>
          ))}
          {bars.length > 1 && <path d={balancePath} fill="none" strokeWidth={1.75} strokeLinejoin="round" className="stroke-chart-line" />}
          {low && (
            <g data-testid="cash-lowest">
              <circle cx={low.x + low.width / 2} cy={low.balanceY} r={5} strokeWidth={2} className="fill-surface stroke-chart-line" />
              <text x={low.x + low.width / 2} y={Math.min(low.balanceY + 20, plot - 2)} textAnchor="middle" className="fill-accent text-xs">{names.lowest} · {format(low.balance)}</text>
            </g>
          )}
        </svg>
      </div>
      <DataTableAlt caption={label} head={["", names.cashIn, names.cashOut, names.balance]} rows={bars.map((b) => [b.label + (b.lowest ? ` (${names.lowest})` : ""), format(b.cashIn), format(b.cashOut), format(b.balance)])} />
    </figure>
  );
}

/** The route of a shipment from its recorded events: the travelled part solid, the rest dashed, the last recorded
 * event marked. A diagram, not a map: the caption says it is not a live position. */
export function RouteLine({ stops, label, caption, height = 200, rtl = false, lastLabel, children }: {
  stops: RouteStop[]; label: string; caption: ReactNode; height?: number; rtl?: boolean; lastLabel?: string; children?: ReactNode }) {
  const { t } = useTranslation();
  const width = 820;
  const nodes = routeNodes(stops, width, height - 30, rtl);
  const at = lastRecorded(stops);
  const done = nodes.slice(0, at + 1), rest = nodes.slice(Math.max(at, 0));
  const state = (s: RouteStop) => (s.state === "last" ? lastLabel ?? t("ds.route.last") : s.state === "done" ? t("ds.route.done") : t("ds.route.upcoming"));
  return (
    <figure className="m-0 flex flex-col gap-2" data-testid="route-line">
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" style={{ minWidth: 520 }}
          aria-label={`${label}: ${stops.map((s) => `${s.name}${s.code ? ` (${s.code})` : ""} ${state(s)}`).join(" ← ")}`}>
          {rest.length > 1 && <path d={smoothPath(rest)} fill="none" strokeWidth={1.5} strokeDasharray="5 5" className="stroke-faint" />}
          {done.length > 1 && <path d={smoothPath(done)} fill="none" strokeWidth={2} strokeLinecap="round" className="stroke-chart-1" />}
          {nodes.map((n, i) => {
            const above = i % 2 === 0;
            return (
              <g key={n.key} data-state={n.state}>
                {n.state === "last" && <circle cx={n.x} cy={n.y} r={13} className="fill-none stroke-accent-line" />}
                <circle cx={n.x} cy={n.y} r={n.state === "last" ? 7 : 5} strokeWidth={2}
                  className={n.state === "done" ? "fill-chart-1 stroke-chart-1" : n.state === "last" ? "fill-surface stroke-chart-1" : "fill-surface stroke-faint"} />
                <text x={n.x} y={n.y + (above ? -18 : 26)} textAnchor="middle" className={`text-sm ${n.state === "upcoming" ? "fill-muted" : "fill-title"}`}>{n.name}</text>
                <text x={n.x} y={n.y + (above ? -34 : 42)} textAnchor="middle" className="fill-muted text-2xs" direction="ltr">{[n.code, n.when].filter(Boolean).join(" · ")}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">{caption}{children}</figcaption>
      <DataTableAlt caption={label} head={[t("ds.route.place"), t("ds.route.code"), t("ds.route.when"), t("ds.route.state")]}
        rows={stops.map((s) => [s.name, s.code ?? "", s.when ?? "", state(s)])} />
    </figure>
  );
}
