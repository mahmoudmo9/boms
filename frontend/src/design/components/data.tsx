/** Data display of the design system (v0.10.0 section 2): DataTable (sticky header, a body that scrolls in its own
 * box, column sizing, sort, row selection, keyboard row navigation, empty / loading / error rows), Pagination,
 * DescriptionList, Timeline (vertical) and DatedTimeline (horizontal), Stepper (the deal path), KpiTile, Stat,
 * ProgressBar, ProgressRing. */
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { type KeyboardEvent, type ReactNode, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useFormat } from "../../lib/prefs";
import { EmptyState, ErrorState, Skeleton } from "./feedback";
import { Icon } from "./Icon";
import { IconButton, Spinner, type Tone } from "./primitives";

export interface SortState { id: string; desc: boolean }

interface TableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  sort?: SortState;
  onSortChange?: (s: SortState) => void;
  sortable?: string[];
  rowKey: (row: T) => string;
  empty?: ReactNode;
  emptyAction?: ReactNode;
  /** A Tailwind max-height class: the body then scrolls inside the table's own box under a sticky header. */
  maxHeight?: string;
  dense?: boolean;
  label?: string;
  /** The row that is open beside the table (marked, announced as selected). */
  activeKey?: string | null;
  onRowActivate?: (row: T) => void;
  /** Checkbox selection. */
  selected?: Set<string>;
  onSelectedChange?: (keys: Set<string>) => void;
  testId?: string;
}

/** Server-paginated table on TanStack Table. Sorting is reported upward; the server sorts. Rows can be walked with
 * the arrow keys (Home / End jump); Enter opens the row; Space toggles its checkbox. */
export function DataTable<T>({ columns, data, loading, error, onRetry, sort, onSortChange, sortable = [], rowKey, empty, emptyAction, maxHeight, dense, label,
  activeKey, onRowActivate, selected, onSelectedChange, testId }: TableProps<T>) {
  const { t } = useTranslation();
  const body = useRef<HTMLTableSectionElement>(null);
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel(), getRowId: rowKey, manualSorting: true });
  const rows = table.getRowModel().rows;
  const interactive = Boolean(onRowActivate || onSelectedChange);
  const toggle = (key: string) => {
    if (!selected || !onSelectedChange) return;
    const next = new Set(selected);
    if (next.has(key)) next.delete(key); else next.add(key);
    onSelectedChange(next);
  };
  const allSelected = Boolean(selected && rows.length > 0 && rows.every((r) => selected.has(r.id)));
  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, index: number, key: string, row: T) => {
    if (e.target !== e.currentTarget) return;                 // keys typed inside a cell's own control are its own
    const nodes = [...(body.current?.querySelectorAll<HTMLElement>("tr[data-row]") ?? [])];
    const to = e.key === "ArrowDown" ? nodes[index + 1] : e.key === "ArrowUp" ? nodes[index - 1] : e.key === "Home" ? nodes[0] : e.key === "End" ? nodes[nodes.length - 1] : undefined;
    if (to) { e.preventDefault(); to.focus(); return; }
    if (e.key === "Enter" && onRowActivate) { e.preventDefault(); onRowActivate(row); }
    if (e.key === " " && onSelectedChange) { e.preventDefault(); toggle(key); }
  };
  const cell = dense ? "h-9 px-3" : "h-12 px-3.5";
  const colCount = columns.length + (onSelectedChange ? 1 : 0);
  return (
    <div className={`relative overflow-auto ${maxHeight ?? ""}`} data-testid={testId} data-dense={dense || undefined} tabIndex={maxHeight ? 0 : undefined}
      role={maxHeight ? "region" : undefined} aria-label={maxHeight ? label : undefined}>
      <table className="w-full border-collapse text-sm" aria-label={label} aria-busy={loading || undefined} aria-rowcount={data.length}>
        <thead className="sticky top-0 z-(--z-sticky)">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="bg-surface-2">
              {onSelectedChange && (
                <th scope="col" className="w-10 border-b border-line px-3">
                  <input type="checkbox" aria-label={t("ds.table.selectAll")} checked={allSelected} className="size-4 cursor-pointer accent-accent-bright"
                    onChange={() => onSelectedChange(allSelected ? new Set() : new Set(rows.map((r) => r.id)))} />
                </th>
              )}
              {group.headers.map((header) => {
                const canSort = sortable.includes(header.column.id) && onSortChange;
                const active = sort?.id === header.column.id;
                const size = header.column.columnDef.size;
                return (
                  <th key={header.id} scope="col" style={size && size !== 150 ? { width: size } : undefined}
                    aria-sort={active ? (sort!.desc ? "descending" : "ascending") : canSort ? "none" : undefined}
                    className="h-10 border-b border-line px-3.5 text-start text-xs font-medium whitespace-nowrap text-muted">
                    {canSort ? (
                      <button type="button" className="relative inline-flex cursor-pointer items-center gap-1 rounded-sm after:absolute after:-inset-2 hover:text-fg"
                        onClick={() => onSortChange!({ id: header.column.id, desc: active ? !sort!.desc : false })}>
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <Icon name={active ? (sort!.desc ? "chevronDown" : "chevronUp") : "chevronDown"} size={12} className={active ? "text-accent" : "opacity-40"} />
                      </button>
                    ) : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody ref={body}>
          {rows.map((row, index) => {
            const isActive = activeKey === row.id, isSelected = Boolean(selected?.has(row.id));
            return (
              <tr key={row.id} data-row={row.id} data-active={isActive || undefined} aria-selected={interactive ? isActive || isSelected : undefined}
                tabIndex={interactive ? (isActive || (activeKey == null && index === 0) ? 0 : -1) : undefined}
                onClick={onRowActivate ? (e) => { if (!(e.target as HTMLElement).closest("a, button, input, select, label")) onRowActivate(row.original); } : undefined}
                onKeyDown={interactive ? (e) => onKey(e, index, row.id, row.original) : undefined}
                className={`border-b border-line transition-colors duration-150 last:border-b-0 ${onRowActivate ? "cursor-pointer" : ""} ${isActive ? "bg-accent-soft" : isSelected ? "bg-surface-2" : "hover:bg-hover"}`}>
                {onSelectedChange && (
                  <td className="px-3"><input type="checkbox" aria-label={t("ds.table.selectRow")} checked={isSelected} onChange={() => toggle(row.id)} className="size-4 cursor-pointer accent-accent-bright" /></td>
                )}
                {row.getVisibleCells().map((c) => <td key={c.id} className={`${cell} align-middle`}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
              </tr>
            );
          })}
          {loading && data.length === 0 && Array.from({ length: 5 }, (_, i) => (
            <tr key={`s${i}`} className="border-b border-line last:border-b-0" data-testid="table-skeleton">
              <td colSpan={colCount} className={cell}><Skeleton className="h-3.5 w-full" /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {Boolean(error) && <ErrorState compact error={error} onRetry={onRetry} />}
      {!loading && !error && data.length === 0 && <EmptyState compact action={emptyAction}>{empty ?? t("common.noResults")}</EmptyState>}
      {loading && data.length > 0 && (
        <div className="pointer-events-none absolute end-3 top-2.5 z-(--z-sticky)"><Spinner size={14} /></div>
      )}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav aria-label={t("ds.table.pages")} className="flex items-center justify-between gap-3 border-t border-line px-3.5 py-1.5 text-xs text-muted">
      <span className="tabular-nums">{t("common.range", { from: f.num(from), to: f.num(to), total: f.num(total) })}</span>
      <div className="flex items-center gap-1">
        <IconButton icon="chevronStart" size="sm" label={t("common.previous")} disabled={page <= 1} onClick={() => onPage(page - 1)} />
        <span className="tabular-nums" aria-current="page">{t("common.pageOf", { page: f.num(page), pages: f.num(pages) })}</span>
        <IconButton icon="chevron" size="sm" label={t("common.next")} disabled={page >= pages} onClick={() => onPage(page + 1)} />
      </div>
    </nav>
  );
}

/** Label / value pairs (a record's facts). */
export function DescriptionList({ items, columns = 2, className = "" }: { items: { label: ReactNode; value: ReactNode; wide?: boolean }[]; columns?: 1 | 2 | 3; className?: string }) {
  const cols = columns === 1 ? "grid-cols-1" : columns === 2 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3";
  return (
    <dl className={`grid gap-x-6 gap-y-3.5 ${cols} ${className}`}>
      {items.filter((i) => i.value !== null && i.value !== undefined && i.value !== "").map((item, i) => (
        <div key={i} className={`flex min-w-0 flex-col gap-0.5 ${item.wide ? "sm:col-span-full" : ""}`}>
          <dt className="text-xs text-muted">{item.label}</dt>
          <dd className="text-sm text-fg [overflow-wrap:anywhere]">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export type TimelineState = "done" | "current" | "upcoming";
export type TimelineItem = { key: string; when?: ReactNode; title: ReactNode; detail?: ReactNode; state?: TimelineState; tone?: Tone; extra?: ReactNode };

const DOT: Record<TimelineState, string> = {
  done: "border-accent-bright bg-accent-bright",
  current: "border-accent-bright bg-surface shadow-ring",
  upcoming: "border-line-strong bg-surface",
};

/** A vertical timeline: what happened, what is happening now, what is expected. */
export function Timeline({ items, label }: { items: TimelineItem[]; label?: string }) {
  const { t } = useTranslation();
  return (
    <ol aria-label={label} className="flex flex-col">
      {items.map((item, i) => {
        const state = item.state ?? "done";
        return (
          <li key={item.key} aria-current={state === "current" ? "step" : undefined} className="relative flex gap-3 pb-5 last:pb-0" data-state={state}>
            {i < items.length - 1 && <span aria-hidden className={`absolute start-1.25 top-4 bottom-0 w-px ${state === "upcoming" ? "bg-line" : "bg-accent-line"}`} />}
            <span aria-hidden className={`relative mt-1 size-2.75 shrink-0 rounded-2xl border-2 ${DOT[state]}`} />
            <div className={`flex min-w-0 flex-1 flex-col gap-0.5 ${state === "upcoming" ? "text-muted" : "text-fg"}`}>
              {(item.when || state !== "done") && (
                <span className={`text-xs ${state === "current" ? "text-accent" : "text-muted"}`}>
                  {item.when}{state === "current" && <> · {t("ds.timeline.now")}</>}{state === "upcoming" && !item.when && t("ds.timeline.expected")}
                </span>
              )}
              <span className="text-sm">{item.title}</span>
              {item.detail && <span className="text-xs text-muted">{item.detail}</span>}
              {item.extra}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** A horizontal dated timeline (the tender page): equal steps on a line, the current one marked. */
export function DatedTimeline({ items, label }: { items: TimelineItem[]; label?: string }) {
  return (
    <ol aria-label={label} className="flex min-w-0 overflow-x-auto pb-1">
      {items.map((item, i) => {
        const state = item.state ?? "done";
        return (
          <li key={item.key} aria-current={state === "current" ? "step" : undefined} data-state={state} className="relative flex min-w-32 flex-1 flex-col items-center gap-1.5 px-2 text-center">
            {i > 0 && <span aria-hidden className={`absolute end-1/2 top-1.25 h-px w-full ${state === "upcoming" ? "bg-line" : "bg-accent-line"}`} />}
            <span aria-hidden className={`relative size-2.75 rounded-2xl border-2 ${DOT[state]}`} />
            <span className={`text-xs tabular-nums ${state === "current" ? "text-accent" : "text-muted"}`}>{item.when}</span>
            <span className={`text-sm ${state === "upcoming" ? "text-muted" : "text-fg"}`}>{item.title}</span>
            {item.detail && <span className="text-xs text-muted">{item.detail}</span>}
          </li>
        );
      })}
    </ol>
  );
}

/** The deal path: استعلام ← پیشنهاد ← سفارش ← حمل ← تحویل ← بستن. Each step shows a number or a tick and its name. */
export function Stepper({ steps, label }: { steps: { key: string; label: ReactNode; state: TimelineState; hint?: ReactNode }[]; label: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  return (
    <ol aria-label={label} className="flex min-w-0 items-start overflow-x-auto" data-testid="stepper">
      {steps.map((step, i) => (
        <li key={step.key} aria-current={step.state === "current" ? "step" : undefined} data-state={step.state} className="flex min-w-20 flex-1 flex-col items-center gap-1.5 text-center">
          <span className="flex w-full items-center">
            <span aria-hidden className={`h-px flex-1 ${i === 0 ? "bg-transparent" : step.state === "upcoming" ? "bg-line-strong" : "bg-accent-bright"}`} />
            <span className={`flex size-7 shrink-0 items-center justify-center rounded-2xl border text-xs font-semibold tabular-nums ${step.state === "done" ? "border-accent-bright bg-accent-bright text-accent-fg" : step.state === "current" ? "border-accent-bright text-accent shadow-ring" : "border-line-strong text-muted"}`}>
              {step.state === "done" ? <Icon name="check" size={13} title={t("ds.stepper.done")} /> : f.num(i + 1)}
            </span>
            <span aria-hidden className={`h-px flex-1 ${i === steps.length - 1 ? "bg-transparent" : steps[i + 1].state === "upcoming" ? "bg-line-strong" : "bg-accent-bright"}`} />
          </span>
          <span className={`text-xs ${step.state === "current" ? "font-semibold text-title" : step.state === "done" ? "text-fg-2" : "text-muted"}`}>{step.label}</span>
          {step.hint && <span className="text-2xs text-muted">{step.hint}</span>}
        </li>
      ))}
    </ol>
  );
}

const TONE_TEXT: Record<Tone, string> = { neutral: "text-title", success: "text-success", danger: "text-danger", warning: "text-warning", accent: "text-accent", info: "text-info" };

/** One figure of a dashboard: a label, the big number with its unit, a note, and room for a small chart. */
export function KpiTile({ label, value, unit, note, tone = "neutral", children, estimated, testId, emphasis }: {
  label: ReactNode; value: ReactNode; unit?: ReactNode; note?: ReactNode; tone?: Tone; children?: ReactNode; estimated?: boolean; testId?: string; emphasis?: boolean }) {
  const { t } = useTranslation();
  return (
    <article data-testid={testId} className={`flex min-w-0 flex-col gap-2.5 rounded-2xl border px-5 py-4.5 ${emphasis ? "border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to" : "border-line bg-surface"}`}>
      <span className="flex items-center justify-between gap-2 text-xs text-muted">
        {label}
        {estimated && <span className="rounded-sm border border-warning-line px-1.5 text-2xs text-warning">{t("ds.kpi.estimated")}</span>}
      </span>
      <span className="flex flex-wrap items-baseline gap-2">
        <span className={`text-4xl font-light tabular-nums ${TONE_TEXT[tone]}`}>{value}</span>
        {unit && <span className="text-sm text-muted">{unit}</span>}
      </span>
      {children}
      {note && <span className="text-xs text-fg-2">{note}</span>}
    </article>
  );
}

/** A small label / value pair inside a card. */
export function Stat({ label, value, tone }: { label: ReactNode; value: ReactNode; tone?: Tone }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${tone ? TONE_TEXT[tone] : "text-title"}`}>{value}</span>
    </div>
  );
}

const BAR_TONE: Record<Tone, string> = { neutral: "bg-fg-2", success: "bg-success", danger: "bg-danger", warning: "bg-warning", accent: "bg-accent-bright", info: "bg-info" };

/** A bar from 0 to 100 %. Without `value` it shows that work is going on (indeterminate). */
export function ProgressBar({ value, label, tone = "accent", className = "", segments }: {
  value?: number | null; label: string; tone?: Tone; className?: string; segments?: { value: number; tone: Tone; label: string }[] }) {
  const pct = value === null || value === undefined ? null : Math.max(0, Math.min(100, value));
  if (segments) {
    const total = segments.reduce((s, x) => s + x.value, 0) || 1;
    return (
      <div role="img" aria-label={`${label}: ${segments.map((s) => `${s.label} ${Math.round((s.value / total) * 100)}%`).join("، ")}`}
        className={`flex h-2 w-full gap-px overflow-hidden rounded-2xl bg-chart-track ${className}`}>
        {segments.map((s, i) => <span key={i} style={{ width: `${(s.value / total) * 100}%` }} className={BAR_TONE[s.tone]} />)}
      </div>
    );
  }
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined}
      className={`h-1.5 w-full overflow-hidden rounded-2xl bg-chart-track ${className}`}>
      {pct === null
        ? <span className="block h-full w-full animate-shimmer bg-linear-to-r from-chart-track via-accent-bright to-chart-track bg-size-[200%_100%]" />
        : <span style={{ width: `${pct}%` }} className={`block h-full rounded-2xl transition-[width] duration-200 ease-out ${BAR_TONE[tone]}`} />}
    </div>
  );
}

const RING_TONE: Record<Tone, string> = { neutral: "stroke-fg-2", success: "stroke-success", danger: "stroke-danger", warning: "stroke-warning", accent: "stroke-accent-bright", info: "stroke-info" };

/** A ring from 0 to 100 % with a value in the middle (time left, progress, a score). */
export function ProgressRing({ value, size = 72, stroke = 6, label, tone = "accent", children }: {
  value: number; size?: number; stroke?: number; label: string; tone?: Tone; children?: ReactNode }) {
  const pct = Math.max(0, Math.min(100, value));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-chart-track" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={`${(pct / 100) * c} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`} className={`${RING_TONE[tone]} transition-[stroke-dasharray] duration-200 ease-out`} />
      </svg>
      {children && <span className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</span>}
    </span>
  );
}
