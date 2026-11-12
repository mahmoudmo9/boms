/** Primitives of the design system (v0.10.0 section 2): Button, IconButton, TextLink, Badge / Chip / Status, CodeChip,
 * Tooltip, Kbd, Spinner, Bdi. Every state is styled here once (hover, focus-visible through the global ring, active,
 * disabled, loading); nothing reads a colour, size or font except through tokens. Layout is logical (RTL and LTR). */
import { type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { Icon } from "./Icon";

export type Variant = "primary" | "secondary" | "ghost" | "danger";
export type Size = "sm" | "md" | "lg";
export type Tone = "neutral" | "success" | "danger" | "warning" | "accent" | "info";

/** Isolates mixed-direction values (codes, file names, e-mails, numbers) from the surrounding text. */
export function Bdi({ children, ltr = false, className }: { children: ReactNode; ltr?: boolean; className?: string }) {
  return <bdi dir={ltr ? "ltr" : undefined} className={className}>{children}</bdi>;
}

const VARIANTS: Record<Variant, string> = {
  primary: "border-transparent bg-linear-to-br from-accent-fill-from to-accent-fill-to font-semibold text-accent-fg shadow-accent hover:brightness-105 active:brightness-95",
  secondary: "border-line-strong bg-surface text-fg hover:border-control hover:bg-hover active:bg-surface-2",
  ghost: "border-transparent bg-transparent text-fg-2 hover:bg-hover hover:text-fg active:bg-surface-2",
  danger: "border-danger-line bg-surface text-danger hover:bg-danger-soft active:bg-danger-soft",
};
/** Heights 32 / 40 / 48 px. The small size keeps a 40 px pointer target through its ::after area. */
const SIZES: Record<Size, string> = {
  sm: "h-8 gap-1.5 rounded-md px-3 text-sm after:absolute after:-inset-1",
  md: "h-10 gap-2 rounded-md px-4 text-sm",
  lg: "h-12 gap-2.5 rounded-lg px-5 text-base",
};
const BUTTON = "relative inline-flex shrink-0 cursor-pointer items-center justify-center border font-medium whitespace-nowrap transition-[background-color,border-color,color,filter] duration-150 ease-out select-none disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none disabled:hover:brightness-100 aria-busy:cursor-progress";

export function buttonClass(variant: Variant = "secondary", size: Size = "sm", className = ""): string {
  return `${BUTTON} ${SIZES[size]} ${VARIANTS[variant]} ${className}`;
}

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  const { t } = useTranslation();
  return (
    <span role="status" aria-label={label ?? t("common.loading")} style={{ width: size, height: size }}
      className="inline-block shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-accent" />
  );
}

export function Button({ variant = "secondary", size = "sm", icon, iconEnd, busy, className = "", children, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: string; iconEnd?: string; busy?: boolean }) {
  return (
    <button type="button" {...props} disabled={props.disabled || busy} aria-busy={busy || undefined} className={buttonClass(variant, size, className)}>
      {busy ? <Spinner size={size === "lg" ? 18 : 14} /> : icon ? <Icon name={icon} size={size === "lg" ? 18 : 15} /> : null}
      {children}
      {iconEnd && !busy && <Icon name={iconEnd} size={size === "lg" ? 18 : 15} />}
    </button>
  );
}

export function ButtonLink({ href, variant = "secondary", size = "sm", icon, children, newTab, className = "", ...props }:
  AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; variant?: Variant; size?: Size; icon?: string; newTab?: boolean }) {
  return (
    <a {...props} href={href} target={newTab ? "_blank" : undefined} rel={newTab ? "noreferrer" : undefined} className={buttonClass(variant, size, className)}>
      {icon && <Icon name={icon} size={15} />}
      {children}
    </a>
  );
}

/** An icon-only button: the label is its accessible name and its tooltip. 40 px target at every size. */
export function IconButton({ icon, label, size = "md", className = "", active, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; label: string; size?: "sm" | "md"; active?: boolean }) {
  return (
    <button type="button" title={label} aria-label={label} aria-pressed={active} {...props}
      className={`relative inline-flex shrink-0 cursor-pointer items-center justify-center rounded-md text-muted transition-colors duration-150 ease-out hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:bg-accent-soft aria-pressed:text-accent ${size === "sm" ? "size-8 after:absolute after:-inset-1" : "size-10"} ${className}`}>
      <Icon name={icon} size={size === "sm" ? 16 : 18} />
    </button>
  );
}

/** A text link inside prose or a table cell. */
export function TextLink({ className = "", children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a {...props} className={`text-accent underline-offset-4 transition-colors duration-150 hover:text-accent-hover hover:underline ${className}`}>{children}</a>;
}
export const linkClass = "text-accent underline-offset-4 transition-colors duration-150 hover:text-accent-hover hover:underline";

const TONES: Record<Tone, string> = {
  neutral: "border-line bg-surface-2 text-fg-2",
  success: "border-success-line bg-success-soft text-success",
  danger: "border-danger-line bg-danger-soft text-danger",
  warning: "border-warning-line bg-warning-soft text-warning",
  accent: "border-accent-line bg-accent-soft text-accent",
  info: "border-info-line bg-info-soft text-info",
};
const TONE_ICON: Record<Tone, string> = { neutral: "minus", success: "checkCircle", danger: "xCircle", warning: "alert", accent: "sparkle", info: "info" };

/** A small label. `icon` adds a mark so the tone is never the only signal. */
export function Badge({ tone = "neutral", icon, children, className = "" }: { tone?: Tone; icon?: string | true; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]} ${className}`}>
      {icon && <Icon name={icon === true ? TONE_ICON[tone] : icon} size={12} />}
      {children}
    </span>
  );
}

/** A status always carries an icon and a word (meaning is never by colour alone). */
export function Status({ tone, children, icon }: { tone: Tone; children: ReactNode; icon?: string }) {
  return <Badge tone={tone} icon={icon ?? true}>{children}</Badge>;
}

/** A pill: a filter that can be on or off, or a removable tag. */
export function Chip({ selected, onClick, onRemove, removeLabel, icon, children, className = "" }: {
  selected?: boolean; onClick?: () => void; onRemove?: () => void; removeLabel?: string; icon?: string; children: ReactNode; className?: string }) {
  const tone = selected ? "border-transparent bg-accent-bright font-semibold text-accent-fg" : "border-line-strong bg-transparent text-fg-2 hover:border-control hover:text-fg";
  const base = `inline-flex h-8 items-center gap-1.5 rounded-2xl border px-3 text-xs whitespace-nowrap transition-colors duration-150 ${tone} ${className}`;
  const body = <>{icon && <Icon name={icon} size={13} />}{children}</>;
  if (onClick) {
    return <button type="button" aria-pressed={selected ?? false} onClick={onClick} className={`relative cursor-pointer after:absolute after:-inset-y-1 after:inset-x-0 ${base}`}>{body}</button>;
  }
  return (
    <span className={base}>
      {body}
      {onRemove && (
        <button type="button" aria-label={removeLabel} title={removeLabel} onClick={onRemove} className="relative -me-1 inline-flex size-5 cursor-pointer items-center justify-center rounded-2xl after:absolute after:-inset-2.5 hover:bg-hover">
          <Icon name="x" size={12} />
        </button>
      )}
    </span>
  );
}

/** A keyboard key. */
export function Kbd({ children }: { children: ReactNode }) {
  return <kbd dir="ltr" className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-accent-line px-1.5 font-mono text-2xs text-accent">{children}</kbd>;
}

/** A record code (CS-1405-0003, PO-…) in the fixed-width face; one click copies it. */
export function CodeChip({ code, copy = true, className = "" }: { code: string | null | undefined; copy?: boolean; className?: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  if (!code) return null;
  const body = <bdi dir="ltr" className="font-mono text-xs tracking-wide">{code}</bdi>;
  const cls = `inline-flex h-6 items-center gap-1.5 rounded-sm border border-line bg-surface-2 px-2 text-fg-2 ${className}`;
  if (!copy) return <span className={cls} data-testid="code-chip">{body}</span>;
  return (
    <button type="button" data-testid="code-chip" title={copied ? t("smart.copied") : t("smart.copyCode")} aria-label={`${t("smart.copyCode")}: ${code}`}
      onClick={() => { void navigator.clipboard?.writeText(code); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}
      className={`relative cursor-pointer transition-colors duration-150 after:absolute after:-inset-2 hover:border-accent-line hover:text-fg ${cls}`}>
      {body}
      <Icon name={copied ? "check" : "copy"} size={12} className={copied ? "text-success" : "text-muted"} />
      <span aria-live="polite" className="sr-only">{copied ? t("smart.copied") : ""}</span>
    </button>
  );
}

/** A hint shown on hover and on keyboard focus of its child; the child is described by it. */
export function Tooltip({ text, children, side = "top" }: { text: ReactNode; children: ReactNode; side?: "top" | "bottom" }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex" aria-describedby={open ? id : undefined}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      {children}
      {open && (
        <span id={id} role="tooltip"
          className={`pointer-events-none absolute start-1/2 z-(--z-popover) w-max max-w-64 -translate-x-1/2 animate-fade-in rounded-md border border-line-strong bg-surface-3 px-2.5 py-1.5 text-xs text-fg shadow-md rtl:translate-x-1/2 ${side === "top" ? "bottom-full mb-2" : "top-full mt-2"}`}>
          {text}
        </span>
      )}
    </span>
  );
}
