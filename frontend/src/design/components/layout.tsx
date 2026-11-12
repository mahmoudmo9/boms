/** Page patterns of the design system (v0.10.0 section 3): the page header (breadcrumb, display title, code chip,
 * status, primary action, secondary actions in a menu) and the page grid with a side column. */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Menu, type MenuItem } from "./containers";
import { Icon } from "./Icon";
import { CodeChip, IconButton } from "./primitives";

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
            {c.to ? <Link to={c.to} className="rounded-sm transition-colors duration-150 hover:text-fg">{c.label}</Link> : <span aria-current="page" className="text-fg-2">{c.label}</span>}
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
export function PageGrid({ children, side, sideWidth = "xl:grid-cols-[minmax(0,1fr)_22rem]" }: { children: ReactNode; side: ReactNode; sideWidth?: string }) {
  return (
    <div className={`grid grid-cols-1 gap-5 ${sideWidth}`}>
      <div className="flex min-w-0 flex-col gap-5">{children}</div>
      <aside className="flex min-w-0 flex-col gap-5">{side}</aside>
    </div>
  );
}
