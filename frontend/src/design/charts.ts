/** Chart geometry (v0.10.0 section 2), pure and tested without a browser. The components in components/charts.tsx
 * draw what these functions compute; every chart also has a text alternative built from the same numbers. */

export type Point = { x: number; y: number };

const round = (n: number) => Math.round(n * 100) / 100;

/** Scales values into a box, y growing downwards (SVG). A flat series sits in the middle. */
export function scalePoints(values: number[], width: number, height: number, pad = 2): Point[] {
  if (values.length === 0) return [];
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const step = values.length > 1 ? (width - 2 * pad) / (values.length - 1) : 0;
  return values.map((v, i) => ({
    x: round(values.length > 1 ? pad + i * step : width / 2),
    y: round(max === min ? height / 2 : pad + (1 - (v - min) / span) * (height - 2 * pad)),
  }));
}

export function linePath(points: Point[]): string {
  return points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
}

export function areaPath(points: Point[], height: number): string {
  if (points.length < 2) return "";
  return `${linePath(points)} L${points[points.length - 1].x} ${height} L${points[0].x} ${height} Z`;
}

export type BridgeStep = { key: string; label: string; value: number; kind: "total" | "delta" };
export type BridgeBar = BridgeStep & { from: number; to: number; y: number; height: number; x: number; width: number; positive: boolean };

/** A waterfall (plan -> effects -> actual): totals stand on zero, each delta starts where the running sum is. */
export function bridgeBars(steps: BridgeStep[], width: number, height: number, gap = 0.35): BridgeBar[] {
  let running = 0;
  const ranges = steps.map((s) => {
    const from = s.kind === "total" ? 0 : running;
    const to = s.kind === "total" ? s.value : running + s.value;
    running = to;
    return { from, to };
  });
  const lo = Math.min(0, ...ranges.flatMap((r) => [r.from, r.to])), hi = Math.max(0, ...ranges.flatMap((r) => [r.from, r.to]));
  const span = hi - lo || 1;
  const slot = steps.length ? width / steps.length : width;
  const y = (v: number) => round(((hi - v) / span) * height);
  return steps.map((s, i) => {
    const { from, to } = ranges[i];
    const top = Math.min(y(from), y(to));
    return { ...s, from, to, y: top, height: Math.max(round(Math.abs(y(from) - y(to))), 1), x: round(i * slot + (slot * gap) / 2), width: round(slot * (1 - gap)),
      positive: s.kind === "total" ? to >= 0 : s.value >= 0 };
  });
}

export type CashPoint = { key: string; label: string; cashIn: number; cashOut: number };
export type CashBar = CashPoint & { balance: number; x: number; width: number; inY: number; inHeight: number; outY: number; outHeight: number; balanceY: number; lowest: boolean };

/** In and out bars around a zero line, with the running balance from `opening`; the lowest balance is marked. */
export function cashFlowBars(points: CashPoint[], width: number, height: number, opening = 0): { bars: CashBar[]; zeroY: number; balancePath: string } {
  let balance = opening;
  const balances = points.map((p) => (balance += p.cashIn - p.cashOut));
  const hi = Math.max(0, opening, ...points.map((p) => p.cashIn), ...balances), lo = Math.min(0, opening, ...points.map((p) => -p.cashOut), ...balances);
  const span = hi - lo || 1;
  const y = (v: number) => round(((hi - v) / span) * height);
  const slot = points.length ? width / points.length : width;
  const lowestAt = balances.length ? balances.indexOf(Math.min(...balances)) : -1;
  const bars = points.map((p, i) => ({
    ...p, balance: balances[i], x: round(i * slot + slot * 0.3), width: round(slot * 0.4),
    inY: y(p.cashIn), inHeight: round(y(0) - y(p.cashIn)), outY: y(0), outHeight: round(y(-p.cashOut) - y(0)),
    balanceY: y(balances[i]), lowest: i === lowestAt,
  }));
  return { bars, zeroY: y(0), balancePath: linePath(bars.map((b) => ({ x: round(b.x + b.width / 2), y: b.balanceY }))) };
}

export type RouteStop = { key: string; name: string; code?: string | null; when?: string | null; state: "done" | "last" | "upcoming" };
export type RouteNode = RouteStop & Point;

/** Stops spread along a gentle arc from the origin (start edge) to the destination (end edge). The picture is a
 * diagram of the recorded events, not a map and not a live position. `rtl` mirrors it so the origin is at the start. */
export function routeNodes(stops: RouteStop[], width: number, height: number, rtl = false, pad = 28): RouteNode[] {
  const n = stops.length;
  return stops.map((s, i) => {
    const t = n > 1 ? i / (n - 1) : 0.5;
    const x = pad + t * (width - 2 * pad);
    const y = height - pad - Math.sin(t * Math.PI) * (height - 2 * pad) * 0.75 - (1 - t) * 6;
    return { ...s, x: round(rtl ? width - x : x), y: round(y) };
  });
}

/** A smooth path through the nodes (quadratic segments through the midpoints). */
export function smoothPath(points: Point[]): string {
  if (points.length < 2) return "";
  if (points.length === 2) return linePath(points);
  let d = `M${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const mid = { x: round((points[i].x + points[i + 1].x) / 2), y: round((points[i].y + points[i + 1].y) / 2) };
    d += ` Q${points[i].x} ${points[i].y} ${mid.x} ${mid.y}`;
  }
  const last = points[points.length - 1];
  return `${d} T${last.x} ${last.y}`;
}

/** Where the solid (travelled) part of the route ends: the index of the last recorded stop, -1 when none. */
export function lastRecorded(stops: RouteStop[]): number {
  let at = -1;
  stops.forEach((s, i) => { if (s.state !== "upcoming") at = i; });
  return at;
}
