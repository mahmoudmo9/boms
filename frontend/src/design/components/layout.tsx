/** Page patterns of the design system (v0.10.0 section 3): the page header (breadcrumb, display title, code chip,
 * status, primary action, secondary actions in a menu) and the page grid with a side column. */
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Drawer, Menu, type MenuItem } from "./containers";
import { Icon } from "./Icon";
import { Button, CodeChip, IconButton } from "./primitives";

export type Crumb = { label: ReactNode; to?: string };

export function Breadcrumb({ items }: { items: Crumb[] }) {
  const { t } = useTranslation();
  if (items.length === 0) return null;
  return (
    <nav aria-label={t("ds.breadcrumb")} className="mb-1.5">
      <ol className="flex flex-wrap items-center gap-1 text-xs text-muted">
        {items.map((c, i) => (
          <li key={i} className="inline-flex items-center gap-1">
            {i > 0 && <Icon name="chevron" size={12} className="text-faint" />}
            {c.to ? <Link to={c.to} className="rounded-sm transition-colors duration-150 hover:text-fg"><bdi>{c.label}</bdi></Link> : <span aria-current="page" className="text-fg-2"><bdi>{c.label}</bdi></span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** The top of every page. The title is the page's only h1, set in the display face. */
export function PageHeader({ title, subtitle, actions, breadcrumb, code, status, menu, eyebrow, children }: {
  title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; breadcrumb?: Crumb[]; code?: string | null; status?: ReactNode; menu?: MenuItem[];
  eyebrow?: ReactNode; children?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <header className="mb-5 flex flex-col gap-3" data-testid="page-header">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          {breadcrumb && <Breadcrumb items={breadcrumb} />}
          {eyebrow && <p className="mb-1 text-xs tracking-wide text-accent">{eyebrow}</p>}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <h1 className="font-display text-3xl font-semibold text-title [overflow-wrap:anywhere]">{title}</h1>
            {code && <CodeChip code={code} />}
            {status}
          </div>
          {subtitle && <div className="mt-1.5 text-sm text-muted">{subtitle}</div>}
        </div>
        {(actions || (menu && menu.length > 0)) && (
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            {menu && menu.length > 0 && (
              <Menu label={t("ds.moreActions")} items={menu} testId="page-menu"
                trigger={(props) => <IconButton icon="more" label={t("ds.moreActions")} data-testid="page-menu" {...props} />} />
            )}
          </div>
        )}
      </div>
      {children}
    </header>
  );
}

/** The main column with a side column; the side column moves under the main one below 1280 px. */
export function PageGrid({ children, side, sideWidth = "xl:grid-cols-[minmax(0,1fr)_22rem]", sideLabel }: {
  children: ReactNode; side: ReactNode; sideWidth?: string;
  /** v0.10.1: with a label, below 1280 px the side column is a drawer opened from a button (never a block pushed to
   * the bottom of the page); from 1280 px it sits beside the content. */
  sideLabel?: string }) {
  const wide = useMinWidth("(min-width: 80rem)");
  const [open, setOpen] = useState(false);
  const drawer = Boolean(sideLabel) && !wide;
  // one tree for both layouts: crossing 1280 px must not remount the content (an open dialog in it would close)
  return (
    <div className={`grid grid-cols-1 gap-5 ${drawer ? "" : sideWidth}`}>
      <div className="flex min-w-0 flex-col gap-5">
        {drawer && <div className="flex justify-end"><Button icon="panel" onClick={() => setOpen(true)} data-testid="side-drawer-open">{sideLabel}</Button></div>}
        {children}
      </div>
      {drawer
        ? <Drawer open={open} title={sideLabel} onClose={() => setOpen(false)} testId="side-drawer">{side}</Drawer>
        : <aside className="flex min-w-0 flex-col gap-5">{side}</aside>}
    </div>
  );
}

function useMinWidth(query: string): boolean {
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [on, setOn] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const m = window.matchMedia(query);
    const set = () => setOn(m.matches);
    m.addEventListener("change", set);
    return () => m.removeEventListener("change", set);
  }, [query]);
  return on;
}
