/** Costing and quote helpers for the UI. Money is never recomputed here: the server sends every number. */
import type { GateFailure } from "./types";

/** Margin and markup of the same profit, side by side (strings straight from the server). */
export function marginMarkupView(view: { profit: string | null; margin_percent: string | null; markup_percent: string | null },
  num: (v: string) => string = (v) => v): {
  margin: string;
  markup: string;
  profit: string | null;
} {
  const percent = (v: string | null) => (v === null ? "—" : `${num(v)} %`);
  return { margin: percent(view.margin_percent), markup: percent(view.markup_percent), profit: view.profit };
}

/** Keyboard navigation in a grid of inputs marked data-grid="<row>-<column>": Enter / ArrowDown go down,
 * ArrowUp goes up (columns stay), wrapping is not needed. Returns the target cell key or null. */
export function gridTarget(key: string, row: number, column: string, rows: number): string | null {
  const delta = key === "Enter" || key === "ArrowDown" ? 1 : key === "ArrowUp" ? -1 : 0;
  if (!delta) return null;
  const next = row + delta;
  if (next < 0 || next >= rows) return null;
  return `${next}-${column}`;
}

/** The gate's conditions in a fixed order, each passed or failed (with the failure's details). */
export const GATE_CONDITIONS = [
  "sheet_not_final", "fx_missing", "lines_incomplete", "item_not_priced", "below_minimum", "item_below_minimum",
  "validity_too_long", "unconfirmed_parameter", "fx_stale",
] as const;

export type GateCondition = (typeof GATE_CONDITIONS)[number];

export function gateChecklist(failures: GateFailure[], overrides?: { fx_stale: string | null; unconfirmed_parameter: string | null }) {
  const byCode = new Map(failures.map((f) => [f.code, f]));
  const known = new Set<string>(GATE_CONDITIONS);
  const rows: { code: string; ok: boolean; failure: GateFailure | null; overridden: string | null }[] = GATE_CONDITIONS.map((code) => ({
    code,
    ok: !byCode.has(code),
    failure: byCode.get(code) ?? null,
    overridden: code === "fx_stale" ? overrides?.fx_stale ?? null : code === "unconfirmed_parameter" ? overrides?.unconfirmed_parameter ?? null : null,
  }));
  // anything the server adds later still shows (as failed)
  for (const f of failures) if (!known.has(f.code)) rows.push({ code: f.code, ok: false, failure: f, overridden: null });
  return rows;
}

/** Quote statuses that are still open (the case cannot be marked won/lost yet). */
export const OPEN_QUOTE_STATUSES = ["draft", "approved", "sent"];
