/** Bounded dashboard lists (v0.10.1 sections 1.2 and 2.6): at most 8 rows, then «همه (۴۲)» — a link to the full
 * filtered list where one exists, otherwise a toggle that shows the rest in place. */
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { EmptyState } from "../design/components";
import { useFormat } from "../lib/prefs";

export const LIST_CAP = 8;

export function AllLink({ total, to, open, onToggle }: { total: number; to?: string; open?: boolean; onToggle?: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  if (total <= LIST_CAP) return null;
  const cls = "block w-full px-4 py-2 text-start text-sm text-accent hover:underline";
  if (to) return <Link to={to} className={cls} data-testid="list-all">{t("common.allCount", { n: f.num(total) })}</Link>;
  return (
    <button type="button" className={cls} onClick={onToggle} aria-expanded={open} data-testid="list-all">
      {open ? t("common.showFewer") : t("common.allCount", { n: f.num(total) })}
    </button>
  );
}

/** Rows capped at 8 with the «همه» link or toggle under them. */
export function Capped<T>({ rows, to, render, empty }: { rows: T[]; to?: string; render: (rows: T[]) => ReactNode; empty?: ReactNode }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return <>{empty ?? <EmptyState>{t("cc.nothing")}</EmptyState>}</>;
  const shown = open ? rows : rows.slice(0, LIST_CAP);
  return (
    <>
      {render(shown)}
      <AllLink total={rows.length} to={to} open={open} onToggle={() => setOpen(!open)} />
    </>
  );
}

export type LinkRow = { key: string; to: string; label: ReactNode; extra?: ReactNode };

/** The command center's simple link rows. */
export function LinkRows({ rows, to }: { rows: LinkRow[]; to?: string }) {
  return (
    <Capped rows={rows} to={to} render={(shown) => (
      <ul className="divide-y divide-line">{shown.map((r) => (
        <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
          <Link to={r.to} className="min-w-0 truncate text-accent hover:underline" dir="auto">{typeof r.label === "string" ? <bdi>{r.label}</bdi> : r.label}</Link>{r.extra}
        </li>))}</ul>
    )} />
  );
}
