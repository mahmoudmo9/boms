/** Containers of the design system (v0.10.0 section 2): Card (plain, raised, accent-bordered), Section, Tabs and the
 * scrolling tab bar, Modal, Drawer, Popover, Menu, ConfirmDialog (with the typed confirmation), Toast.
 * Overlays trap focus, close on Escape, restore focus to what opened them and carry the right roles and names. */
import { createContext, type ReactNode, type RefObject, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { isRtl } from "../dom";
import { Icon } from "./Icon";
import { Button, IconButton, type Variant } from "./primitives";
import { Input } from "./forms";

// ---- cards ---------------------------------------------------------------------------------------------------------------

export type CardKind = "plain" | "raised" | "accent" | "sunken";
const CARDS: Record<CardKind, string> = {
  plain: "border-line bg-surface",
  raised: "border-line-strong bg-surface-3 shadow-md",
  accent: "border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to",
  sunken: "border-line bg-surface-2",
};

export function Card({ title, subtitle, actions, children, className = "", padded = true, kind = "plain", eyebrow, testId, as: Tag = "section" }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean; kind?: CardKind;
  eyebrow?: ReactNode; testId?: string; as?: "section" | "article" | "div" }) {
  return (
    <Tag className={`min-w-0 rounded-2xl border ${CARDS[kind]} ${className}`} data-testid={testId}>
      {(title || actions || eyebrow) && (
        <header className={`flex min-h-14 flex-wrap items-center justify-between gap-3 px-5 py-3 ${padded ? "" : "border-b border-line"}`}>
          <div className="flex min-w-0 flex-col">
            {eyebrow && <span className="text-xs tracking-wide text-accent">{eyebrow}</span>}
            {title && <h2 className="truncate text-base font-medium text-title">{title}</h2>}
            {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? `px-5 pb-5 ${title || actions || eyebrow ? "" : "pt-5"}` : ""}>{children}</div>
    </Tag>
  );
}

/** A titled group inside a page or a card (no frame of its own). */
export function Section({ title, actions, children, className = "" }: { title: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`flex flex-col gap-3 ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-title">{title}</h3>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

// ---- tabs ----------------------------------------------------------------------------------------------------------------

export interface TabItem { key: string; label: ReactNode; testId?: string; count?: ReactNode }

/** A tab bar that never clips: it scrolls horizontally, fades at the edge that has more tabs, keeps the active tab in
 * view and offers an overflow menu listing every tab. Arrow keys move between tabs (roving tabindex). */
export function Tabs({ tabs, active, onSelect, label, panelId }: { tabs: TabItem[]; active: string; onSelect: (key: string) => void; label?: string; panelId?: string }) {
  const { t } = useTranslation();
  const bar = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const measure = useCallback(() => {
    const el = bar.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const pos = Math.abs(el.scrollLeft);              // RTL scrollLeft runs negative in Chromium and Firefox
    setEdges({ start: pos > 1, end: pos < max - 1 });
  }, []);
  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    el.querySelector<HTMLElement>(`[data-tab="${active}"]`)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(el);
    return () => observer?.disconnect();
  }, [active, measure, tabs.length]);
  const onKey = (e: React.KeyboardEvent) => {
    const rtl = isRtl(e.currentTarget);
    const i = tabs.findIndex((x) => x.key === active);
    const step = e.key === (rtl ? "ArrowLeft" : "ArrowRight") ? 1 : e.key === (rtl ? "ArrowRight" : "ArrowLeft") ? -1 : 0;
    const next = e.key === "Home" ? tabs[0] : e.key === "End" ? tabs[tabs.length - 1] : step ? tabs[(i + step + tabs.length) % tabs.length] : null;
    if (!next) return;
    e.preventDefault();
    onSelect(next.key);
    window.requestAnimationFrame(() => bar.current?.querySelector<HTMLElement>(`[data-tab="${next.key}"]`)?.focus());
  };
  return (
    <div className="relative flex items-stretch border-b border-line" data-testid="scroll-tabs">
      <div ref={bar} role="tablist" aria-label={label} onScroll={measure} onKeyDown={onKey} className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
        {tabs.map((tab) => (
          <button key={tab.key} type="button" role="tab" aria-selected={tab.key === active} aria-controls={panelId} tabIndex={tab.key === active ? 0 : -1}
            data-tab={tab.key} data-testid={tab.testId} onClick={() => onSelect(tab.key)}
            className={`-mb-px inline-flex h-11 shrink-0 cursor-pointer items-center gap-1.5 border-b-2 px-3.5 text-sm whitespace-nowrap transition-colors duration-150 ${tab.key === active ? "border-accent-bright font-semibold text-title" : "border-transparent text-muted hover:text-fg"}`}>
            {tab.label}
            {tab.count !== undefined && tab.count !== null && <span className="rounded-2xl bg-surface-2 px-1.5 text-2xs text-fg-2 tabular-nums">{tab.count}</span>}
          </button>
        ))}
      </div>
      {edges.start && <span aria-hidden className="pointer-events-none absolute inset-y-0 start-0 w-8 bg-linear-to-r from-bg to-transparent rtl:bg-linear-to-l" data-fade="start" />}
      {edges.end && <span aria-hidden className="pointer-events-none absolute inset-y-0 end-10 w-8 bg-linear-to-l from-bg to-transparent rtl:bg-linear-to-r" data-fade="end" />}
      <Menu label={t("common.moreTabs")} testId="tabs-more" align="end"
        trigger={(props) => <IconButton icon="more" label={t("common.moreTabs")} data-testid="tabs-more" {...props} />}
        items={tabs.map((tab) => ({ key: tab.key, label: tab.label, checked: tab.key === active, onSelect: () => onSelect(tab.key) }))} />
    </div>
  );
}
export const ScrollTabs = Tabs;

// ---- overlays --------------------------------------------------------------------------------------------------------------

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keeps Tab inside `ref` while `active`, closes on Escape and gives focus back to what had it before. */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, onClose: () => void, initial?: "first-field" | "panel") {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    const before = document.activeElement as HTMLElement | null;
    const first = initial === "panel" ? null
      : root?.querySelector<HTMLElement>("[data-autofocus]") ?? root?.querySelector<HTMLElement>("[data-overlay-body] :is(input, select, textarea):not([disabled])");
    (first ?? root?.querySelector<HTMLElement>("[data-overlay-body] button:not([disabled]), footer button:not([disabled])") ?? root)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); return; }
      if (e.key !== "Tab" || !root) return;
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (items.length === 0) { e.preventDefault(); return; }
      const [head, tail] = [items[0], items[items.length - 1]];
      if (e.shiftKey && (document.activeElement === head || !root.contains(document.activeElement))) { e.preventDefault(); tail.focus(); }
      else if (!e.shiftKey && document.activeElement === tail) { e.preventDefault(); head.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); before?.focus?.(); };
  }, [active, ref, initial]);
}

const MODAL_SIZES = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-4xl", xl: "max-w-6xl" };

export function Modal({ open, title, onClose, children, footer, wide, size, subtitle, testId }: {
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean; size?: keyof typeof MODAL_SIZES;
  subtitle?: ReactNode; testId?: string }) {
  const { t } = useTranslation();
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(panel, open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-(--z-modal) flex animate-fade-in items-start justify-center overflow-y-auto bg-overlay p-4 pt-16" onMouseDown={onClose}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} data-testid={testId} onMouseDown={(e) => e.stopPropagation()}
        className={`mb-12 w-full animate-rise-in rounded-2xl border border-line-strong bg-surface-3 shadow-xl ${MODAL_SIZES[size ?? (wide ? "md" : "sm")]}`}>
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            <h2 id={titleId} className="font-display text-lg font-semibold text-title">{title}</h2>
            {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
          </div>
          <IconButton icon="x" size="sm" label={t("common.close")} onClick={onClose} />
        </header>
        <div className="p-5" data-overlay-body data-modal-body>{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</footer>}
      </div>
    </div>
  );
}

/** A side panel that slides in from the end edge (side panels become drawers below 1280 px). */
export function Drawer({ open, title, onClose, children, footer, side = "end", width = "w-96", testId }: {
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; side?: "start" | "end"; width?: string; testId?: string }) {
  const { t } = useTranslation();
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(panel, open, onClose, "panel");
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-(--z-drawer) animate-fade-in bg-overlay" onMouseDown={onClose}>
      <aside ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} data-testid={testId} onMouseDown={(e) => e.stopPropagation()}
        className={`absolute inset-y-0 flex max-w-full flex-col border-line-strong bg-surface-3 shadow-xl ${width} ${side === "end" ? "end-0 border-s" : "start-0 border-e"}`}>
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 id={titleId} className="font-display text-lg font-semibold text-title">{title}</h2>
          <IconButton icon="x" size="sm" label={t("common.close")} onClick={onClose} />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5" data-overlay-body>{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</footer>}
      </aside>
    </div>
  );
}

type TriggerProps = { onClick: () => void; "aria-expanded": boolean; "aria-haspopup": "menu" | "dialog"; "aria-controls"?: string };

function useDismiss(open: boolean, root: RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) close(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); close(); root.current?.querySelector<HTMLElement>("[aria-haspopup]")?.focus(); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key, true); };
  }, [open, root, close]);
}

/** A small floating panel attached to its trigger (filters, details). Closes on Escape and on a click outside. */
export function Popover({ trigger, children, label, align = "start", width = "w-72" }: {
  trigger: (props: TriggerProps) => ReactNode; children: ReactNode | ((close: () => void) => ReactNode); label: string; align?: "start" | "end"; width?: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const id = useId();
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, root, close);
  return (
    <span ref={root} className="relative inline-flex">
      {trigger({ onClick: () => setOpen(!open), "aria-expanded": open, "aria-haspopup": "dialog", "aria-controls": open ? id : undefined })}
      {open && (
        <div id={id} role="dialog" aria-label={label}
          className={`absolute top-full z-(--z-popover) mt-1.5 animate-fade-in rounded-xl border border-line-strong bg-surface-3 p-3 shadow-md ${width} ${align === "end" ? "end-0" : "start-0"}`}>
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </span>
  );
}

export type MenuItem = { key: string; label: ReactNode; icon?: string; onSelect: () => void; danger?: boolean; disabled?: boolean; checked?: boolean; hint?: ReactNode };

/** A menu of actions: arrows, Home, End and first letters move; Enter or Space runs; Escape closes and returns focus. */
export function Menu({ trigger, items, label, align = "end", testId }: {
  trigger: (props: TriggerProps) => ReactNode; items: MenuItem[]; label: string; align?: "start" | "end"; testId?: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, root, close);
  useLayoutEffect(() => {
    if (open) (list.current?.querySelector<HTMLElement>("[aria-checked='true']") ?? list.current?.querySelector<HTMLElement>("[role^='menuitem']:not([disabled])"))?.focus();
  }, [open]);
  const onKey = (e: React.KeyboardEvent) => {
    const nodes = [...(list.current?.querySelectorAll<HTMLElement>("[role^='menuitem']:not([disabled])") ?? [])];
    const i = nodes.indexOf(document.activeElement as HTMLElement);
    const to = e.key === "ArrowDown" ? nodes[(i + 1) % nodes.length] : e.key === "ArrowUp" ? nodes[(i - 1 + nodes.length) % nodes.length]
      : e.key === "Home" ? nodes[0] : e.key === "End" ? nodes[nodes.length - 1]
        : e.key.length === 1 ? nodes.find((n, j) => j !== i && n.textContent?.trim().toLowerCase().startsWith(e.key.toLowerCase())) : undefined;
    if (to) { e.preventDefault(); to.focus(); }
    if (e.key === "Tab") setOpen(false);
  };
  const some = items.some((x) => x.checked !== undefined);
  return (
    <span ref={root} className="relative inline-flex shrink-0">
      {trigger({ onClick: () => setOpen(!open), "aria-expanded": open, "aria-haspopup": "menu", "aria-controls": open ? id : undefined })}
      {open && (
        <ul ref={list} id={id} role="menu" aria-label={label} data-testid={testId ? `${testId}-menu` : undefined} onKeyDown={onKey}
          className={`absolute top-full z-(--z-popover) mt-1.5 max-h-96 min-w-52 animate-fade-in overflow-y-auto rounded-xl border border-line-strong bg-surface-3 p-1 shadow-md ${align === "end" ? "end-0" : "start-0"}`}>
          {items.map((item) => (
            <li key={item.key} role="none">
              <button type="button" role={some ? "menuitemradio" : "menuitem"} aria-checked={some ? Boolean(item.checked) : undefined} disabled={item.disabled} tabIndex={-1}
                onClick={() => { setOpen(false); root.current?.querySelector<HTMLElement>("[aria-haspopup]")?.focus(); item.onSelect(); }}
                className={`flex min-h-10 w-full cursor-pointer items-center gap-2.5 rounded-md px-3 text-start text-sm transition-colors duration-150 focus:bg-accent-soft focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${item.danger ? "text-danger hover:bg-danger-soft" : "text-fg hover:bg-hover"} ${item.checked ? "font-semibold text-title" : ""}`}>
                {item.icon && <Icon name={item.icon} size={15} className="text-muted" />}
                <span className="min-w-0 flex-1">{item.label}</span>
                {item.hint && <span className="text-xs text-muted">{item.hint}</span>}
                {item.checked && <Icon name="check" size={14} className="text-accent" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

/** Asks before an action that cannot be undone. With `typed`, the button stays off until that word is typed. */
export function ConfirmDialog({ open, title, children, confirmLabel, onConfirm, onClose, busy, variant = "danger", typed, typedLabel, error }: {
  open: boolean; title: ReactNode; children?: ReactNode; confirmLabel: ReactNode; onConfirm: () => void; onClose: () => void; busy?: boolean;
  variant?: Variant; typed?: string; typedLabel?: ReactNode; error?: ReactNode }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const id = useId();
  useEffect(() => { if (!open) setText(""); }, [open]);
  const ready = !typed || text.trim() === typed;
  return (
    <Modal open={open} title={title} onClose={onClose} testId="confirm-dialog"
      footer={<>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant={variant} disabled={!ready} busy={busy} onClick={onConfirm} data-testid="confirm-yes">{confirmLabel}</Button>
      </>}>
      <form className="flex flex-col gap-3 text-sm text-fg" onSubmit={(e) => { e.preventDefault(); if (ready && !busy) onConfirm(); }}>
        {children}
        {typed && (
          <label htmlFor={id} className="flex flex-col gap-1.5 text-xs text-fg-2">
            {typedLabel ?? t("ds.confirm.type", { word: typed })}
            <Input id={id} dir="auto" autoComplete="off" value={text} onChange={(e) => setText(e.target.value)} data-testid="confirm-typed" />
          </label>
        )}
        {error}
      </form>
    </Modal>
  );
}

// ---- toasts ----------------------------------------------------------------------------------------------------------------

type ToastTone = "success" | "error" | "info";
interface ToastItem { id: number; tone: ToastTone; text: ReactNode }
const ToastContext = createContext<(text: ReactNode, tone?: ToastTone) => void>(() => undefined);
const TOAST: Record<ToastTone, [string, string]> = { success: ["text-success", "checkCircle"], error: ["text-danger", "xCircle"], info: ["text-info", "info"] };

/** Short confirmations at the bottom corner; errors are announced at once, the rest politely. They leave after 5 s
 * (8 s for errors) and can be closed. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const drop = useCallback((id: number) => setToasts((list) => list.filter((x) => x.id !== id)), []);
  const push = useCallback((text: ReactNode, tone: ToastTone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list.slice(-3), { id, tone, text }]);
    window.setTimeout(() => drop(id), tone === "error" ? 8000 : 5000);
  }, [drop]);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed end-4 bottom-4 z-(--z-toast) flex w-88 max-w-full flex-col gap-2" data-testid="toasts">
        {toasts.map((toast) => (
          <div key={toast.id} role={toast.tone === "error" ? "alert" : "status"}
            className="pointer-events-auto flex animate-rise-in items-start gap-2.5 rounded-xl border border-line-strong bg-surface-3 px-3.5 py-3 text-sm shadow-md">
            <Icon name={TOAST[toast.tone][1]} size={16} className={`mt-0.5 ${TOAST[toast.tone][0]}`} />
            <div className="min-w-0 flex-1 text-fg">{toast.text}</div>
            <button type="button" aria-label={t("common.close")} onClick={() => drop(toast.id)} className="relative inline-flex size-5 cursor-pointer items-center justify-center rounded-sm text-muted after:absolute after:-inset-2.5 hover:text-fg"><Icon name="x" size={13} /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
