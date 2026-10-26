/** Basic UI building blocks. Layout uses logical properties only (ms/me/ps/pe/start/end). */
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  useEffect,
  useId,
  useRef,
} from "react";
import { useTranslation } from "react-i18next";

import { Icon } from "./Icon";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover border-transparent",
  secondary: "bg-surface text-fg border-line-strong hover:bg-surface-2",
  ghost: "bg-transparent text-fg border-transparent hover:bg-surface-2",
  danger: "bg-surface text-danger border-line-strong hover:bg-danger-soft",
};

export function Button({
  variant = "secondary",
  icon,
  busy,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; icon?: string; busy?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    >
      {busy ? <Spinner size={14} /> : icon ? <Icon name={icon} size={15} /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({ href, variant = "secondary", icon, children, newTab }: {
  href: string;
  variant?: Variant;
  icon?: string;
  children: ReactNode;
  newTab?: boolean;
}) {
  return (
    <a
      href={href}
      target={newTab ? "_blank" : undefined}
      rel={newTab ? "noreferrer" : undefined}
      className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition-colors ${VARIANTS[variant]}`}
    >
      {icon && <Icon name={icon} size={15} />}
      {children}
    </a>
  );
}

export function IconButton({ icon, label, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; label: string }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      {...props}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg ${className}`}
    >
      <Icon name={icon} size={17} />
    </button>
  );
}

export function Card({ title, actions, children, className = "", padded = true }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b border-line px-4 py-2">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function Field({ label, hint, error, children, htmlFor }: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}

/** Full width unless the caller gives an explicit width class. */
const width = (className: string) => (/(^|\s)w-/.test(className) ? "" : "w-full");

const INPUT = "h-8 rounded-md border border-line-strong bg-surface px-2.5 text-sm text-fg placeholder:text-muted focus:border-accent focus:outline-none disabled:bg-surface-2 disabled:text-muted";

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${INPUT} ${width(className)} ${className}`} />;
}

export function Textarea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${INPUT} ${width(className)} h-auto min-h-20 py-1.5 ${className}`} />;
}

export function Select({ className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={`${INPUT} ${width(className)} pe-7 ${className}`}>
      {children}
    </select>
  );
}

export function Checkbox({ label, checked, onChange, disabled }: {
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="inline-flex items-center gap-2 text-sm">
      <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--accent)]" />
      {label}
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  label?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line-strong bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`h-7 rounded px-3 text-sm ${o.value === value ? "bg-accent text-accent-fg" : "text-fg hover:bg-surface-2"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

type Tone = "neutral" | "success" | "danger" | "warning" | "accent";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted border-line",
  success: "bg-success-soft text-success border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  warning: "bg-warning-soft text-warning border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      role="status"
      style={{ width: size, height: size }}
      className="inline-block animate-spin rounded-full border-2 border-line-strong border-t-accent"
    />
  );
}

export function Loading() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 p-6 text-muted">
      <Spinner /> {t("common.loading")}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <div className="flex items-center gap-2 rounded-md border border-transparent bg-danger-soft px-3 py-2 text-sm text-danger">
      <Icon name="alert" size={16} />
      {errorMessage(t, error)}
    </div>
  );
}

export function errorMessage(t: (k: string, o?: Record<string, unknown>) => string, error: unknown): string {
  const code = (error as { code?: string })?.code;
  if (code) {
    const key = `errors.${code}`;
    const text = t(key, (error as { details?: Record<string, unknown> }).details ?? {});
    if (text !== key) return text;
  }
  return t("errors.generic");
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-muted">{children}</div>;
}

export function Modal({ open, title, onClose, children, footer, wide }: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const { t } = useTranslation();
  const panel = useRef<HTMLDivElement>(null);
  // Callers pass inline onClose arrows (a new function every render). Keep it in a ref so the effect below runs
  // only when the dialog opens: re-running it on each keystroke moved focus away from the field being typed in.
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onKey);
    const root = panel.current;
    (root?.querySelector<HTMLElement>("[data-modal-body] :is(input, select, textarea)")
      ?? root?.querySelector<HTMLElement>("[data-modal-body] button, footer button"))?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[10vh]" onMouseDown={onClose}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
        className={`w-full ${wide ? "max-w-2xl" : "max-w-md"} rounded-lg border border-line bg-surface shadow-xl`}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <IconButton icon="x" label={t("common.close")} onClick={onClose} />
        </header>
        <div className="p-4" data-modal-body>{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, tone }: { label: ReactNode; value: ReactNode; tone?: Tone }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${tone === "danger" ? "text-danger" : tone === "success" ? "text-success" : ""}`}>
        {value}
      </span>
    </div>
  );
}
