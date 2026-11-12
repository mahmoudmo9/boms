/** States every page and data region has (v0.10.0 sections 2 and 6): Skeleton while loading, EmptyState with its one
 * next action, ErrorState with what happened and retry, InlineAlert for a note inside a form or card. No blank areas
 * and no raw error text: `errorMessage` turns an API error code into the user's language. */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Icon } from "./Icon";
import { Button, Spinner, type Tone } from "./primitives";

export function errorMessage(t: (k: string, o?: Record<string, unknown>) => string, error: unknown): string {
  const code = (error as { code?: string })?.code;
  if (code) {
    const key = `errors.${code}`;
    const text = t(key, (error as { details?: Record<string, unknown> }).details ?? {});
    if (text !== key) return text;
  }
  return t("errors.generic");
}

/** A grey shape that stands for content that is loading. `lines` draws a paragraph. */
export function Skeleton({ className = "h-4 w-full", lines }: { className?: string; lines?: number }) {
  const bar = "animate-shimmer rounded-md bg-linear-to-r from-surface-2 via-hover to-surface-2 bg-size-[200%_100%]";
  if (lines) {
    return (
      <div aria-hidden className="flex flex-col gap-2.5">
        {Array.from({ length: lines }, (_, i) => <span key={i} className={`${bar} h-3.5 ${i === lines - 1 ? "w-2/3" : "w-full"}`} />)}
      </div>
    );
  }
  return <span aria-hidden className={`${bar} block ${className}`} />;
}

/** The loading state of a page or a card: skeleton rows, announced once to screen readers. */
export function Loading({ rows = 4, label }: { rows?: number; label?: string }) {
  const { t } = useTranslation();
  return (
    <div role="status" aria-busy="true" aria-label={label ?? t("common.loading")} className="flex flex-col gap-4 p-5" data-testid="loading">
      <Skeleton className="h-5 w-1/3" />
      <Skeleton lines={rows} />
    </div>
  );
}

/** Nothing here yet: an icon, one line, and the one next action. */
export function EmptyState({ icon = "inbox", title, children, action, compact }: { icon?: string; title?: ReactNode; children?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 px-4 text-center ${compact ? "py-6" : "py-12"}`} data-testid="empty-state">
      <span className="flex size-11 items-center justify-center rounded-2xl border border-line bg-surface-2 text-muted"><Icon name={icon} size={20} /></span>
      {title && <p className="text-sm font-medium text-fg">{title}</p>}
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Something failed: what happened in the user's words, and a way to try again. */
export function ErrorState({ error, onRetry, title, compact }: { error: unknown; onRetry?: () => void; title?: ReactNode; compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className={`flex flex-col items-center justify-center gap-2 px-4 text-center ${compact ? "py-6" : "py-12"}`} data-testid="error-state">
      <span className="flex size-11 items-center justify-center rounded-2xl border border-danger-line bg-danger-soft text-danger"><Icon name="alert" size={20} /></span>
      <p className="text-sm font-medium text-fg">{title ?? t("ds.error.title")}</p>
      <p className="max-w-md text-sm text-muted">{errorMessage(t, error)}</p>
      {onRetry && <Button icon="refresh" onClick={onRetry} className="mt-2">{t("ds.error.retry")}</Button>}
    </div>
  );
}

const ALERT: Record<Tone, [string, string]> = {
  neutral: ["border-line bg-surface-2 text-fg-2", "info"],
  info: ["border-info-line bg-info-soft text-info", "info"],
  success: ["border-success-line bg-success-soft text-success", "checkCircle"],
  warning: ["border-warning-line bg-warning-soft text-warning", "alert"],
  danger: ["border-danger-line bg-danger-soft text-danger", "xCircle"],
  accent: ["border-accent-line bg-accent-soft text-accent", "sparkle"],
};

/** A note inside a form or a card. Danger and warning are announced (role alert / status). */
export function InlineAlert({ tone = "info", title, children, action, testId }: { tone?: Tone; title?: ReactNode; children?: ReactNode; action?: ReactNode; testId?: string }) {
  const [cls, icon] = ALERT[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} data-testid={testId} className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm ${cls}`}>
      <Icon name={icon} size={16} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className="text-fg">{children}</div>}
      </div>
      {action}
    </div>
  );
}

/** The error of a request, in place (nothing when there is none). */
export function ErrorNote({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return <InlineAlert tone="danger">{errorMessage(t, error)}</InlineAlert>;
}

/** A small «working…» line for a region that refreshes in place. */
export function Busy({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  return <span className="inline-flex items-center gap-2 text-sm text-muted"><Spinner size={14} />{children ?? t("common.loading")}</span>;
}
