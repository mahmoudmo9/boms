/** Form controls of the design system (v0.10.0 section 2): Field (label, hint, source chip, error), Input, Textarea,
 * Select, Combobox, Checkbox, Radio, Switch, Segmented, DatePicker (Jalali / Gregorian), MoneyInput (amount + ISO
 * currency), QuantityInput (amount + UN/ECE unit), FileDrop. Controls are 40 px high (the pointer target), take their
 * width from the caller (`w-…` in className) or fill the row, and show hover, focus, invalid and disabled states. */
import { cloneElement, type InputHTMLAttributes, isValidElement, type KeyboardEvent, type ReactElement, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { lookupKey, type LookupKey } from "../../lib/smart";
import { parseDateInput } from "../../lib/format";
import { useFormat } from "../../lib/prefs";
import { isRtl } from "../dom";
import { addMonths, type CalendarKind, monthGrid, moveFocus, sameDay, weekdays, yearMonth } from "../calendar";
import { Icon } from "./Icon";
import { IconButton } from "./primitives";

/** Full width unless the caller gives an explicit width class. */
const width = (className: string) => (/(^|\s)(w-|flex-1|grow)/.test(className) ? "" : "w-full");

export const CONTROL = "h-10 rounded-md border border-control bg-sunken px-3 text-sm text-fg transition-[border-color,box-shadow] duration-150 ease-out placeholder:text-muted hover:border-fg-2 focus:border-accent focus:shadow-ring focus:outline-none aria-invalid:border-danger disabled:cursor-not-allowed disabled:border-line-strong disabled:bg-surface-2 disabled:text-muted read-only:bg-surface-2";

/** One row of a form: the label, the control, then a hint or the error. `source` is the chip that says where a
 * suggested or filled value came from. The control is wired to the hint and error for screen readers. */
export function Field({ label, hint, error, children, htmlFor, source, required }: {
  label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; htmlFor?: string; source?: ReactNode; required?: boolean }) {
  const auto = useId();
  const describedBy = error ? `${auto}-error` : hint ? `${auto}-hint` : undefined;
  const control = isValidElement(children) && htmlFor && (children.props as { id?: string }).id === htmlFor
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
      "aria-describedby": describedBy ?? (children.props as Record<string, unknown>)["aria-describedby"],
      ...(error ? { "aria-invalid": true } : {}), ...(required ? { "aria-required": true } : {}),
    })
    : children;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={htmlFor} className="text-xs font-medium text-fg-2">
          {label}{required && <span aria-hidden className="ms-0.5 text-danger">*</span>}
        </label>
        {source}
      </div>
      {control}
      {hint && !error && <p id={`${auto}-hint`} className="text-xs text-muted">{hint}</p>}
      {error && <p id={`${auto}-error`} role="alert" className="flex items-center gap-1 text-xs text-danger"><Icon name="alert" size={12} />{error}</p>}
    </div>
  );
}
export const FormRow = Field;

/** The chip beside a field that names the source of its value («از آخرین پیشنهاد»). */
export function SourceChip({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center gap-1 rounded-sm bg-accent-soft px-1.5 py-0.5 text-2xs text-accent"><Icon name="sparkle" size={10} />{children}</span>;
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL} ${width(className)} ${className}`} />;
}

export function Textarea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL} ${width(className)} h-auto min-h-24 py-2 leading-6 ${className}`} />;
}

/** The native select (the platform's keyboard and screen-reader behaviour) in the system's frame. */
export function Select({ className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={`relative inline-flex min-w-0 ${width(className)} ${className}`}>
      <select {...props} className={`${CONTROL} w-full min-w-0 cursor-pointer appearance-none pe-9`}>{children}</select>
      <Icon name="chevronDown" size={15} className="pointer-events-none absolute end-3 top-1/2 -translate-y-1/2 text-muted" />
    </span>
  );
}

export function Checkbox({ label, checked, onChange, disabled, hint, id: given }: {
  label: ReactNode; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; hint?: ReactNode; id?: string }) {
  const auto = useId();
  const id = given ?? auto;
  return (
    <label htmlFor={id} className={`inline-flex min-h-10 items-center gap-2.5 text-sm ${disabled ? "cursor-not-allowed text-muted" : "cursor-pointer text-fg"}`}>
      <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)}
        className="size-4.5 shrink-0 cursor-pointer accent-accent-bright disabled:cursor-not-allowed" />
      <span className="flex flex-col">{label}{hint && <span className="text-xs text-muted">{hint}</span>}</span>
    </label>
  );
}

export function RadioGroup<T extends string>({ value, options, onChange, label, name, inline = true }: {
  value: T | null; options: { value: T; label: ReactNode; hint?: ReactNode; disabled?: boolean }[]; onChange: (v: T) => void; label: string; name?: string; inline?: boolean }) {
  const auto = useId();
  return (
    <div role="radiogroup" aria-label={label} className={`flex ${inline ? "flex-wrap gap-x-5 gap-y-1" : "flex-col"}`}>
      {options.map((o) => (
        <label key={o.value} className={`inline-flex min-h-10 items-center gap-2.5 text-sm ${o.disabled ? "cursor-not-allowed text-muted" : "cursor-pointer text-fg"}`}>
          <input type="radio" name={name ?? auto} value={o.value} checked={o.value === value} disabled={o.disabled} onChange={() => onChange(o.value)}
            className="size-4.5 shrink-0 cursor-pointer accent-accent-bright" />
          <span className="flex flex-col">{o.label}{o.hint && <span className="text-xs text-muted">{o.hint}</span>}</span>
        </label>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled, id }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean; id?: string }) {
  return (
    <label className={`inline-flex min-h-10 items-center gap-3 text-sm ${disabled ? "cursor-not-allowed text-muted" : "cursor-pointer text-fg"}`}>
      <button id={id} type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-2xl border border-control bg-sunken transition-colors duration-150 after:absolute after:-inset-2 aria-checked:border-transparent aria-checked:bg-accent-bright disabled:cursor-not-allowed disabled:opacity-50">
        <span aria-hidden className={`ms-0.5 size-4.5 rounded-2xl transition-transform duration-150 ease-out ${checked ? "translate-x-5 bg-accent-fg rtl:-translate-x-5" : "bg-fg-2"}`} />
      </button>
      {label}
    </label>
  );
}

/** A few exclusive choices side by side (a radio group; arrow keys move the choice). */
export function Segmented<T extends string>({ value, options, onChange, label, size = "md" }: {
  value: T; options: { value: T; label: ReactNode; icon?: string }[]; onChange: (v: T) => void; label?: string; size?: "sm" | "md" }) {
  const move = (e: KeyboardEvent, i: number) => {
    const rtl = isRtl(e.currentTarget);
    const step = e.key === "ArrowDown" || e.key === (rtl ? "ArrowLeft" : "ArrowRight") ? 1 : e.key === "ArrowUp" || e.key === (rtl ? "ArrowRight" : "ArrowLeft") ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = options[(i + step + options.length) % options.length];
    onChange(next.value);
    (e.currentTarget.parentElement?.querySelector(`[data-value="${next.value}"]`) as HTMLElement | null)?.focus();
  };
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex gap-0.5 rounded-md border border-line-strong bg-sunken p-0.5">
      {options.map((o, i) => (
        <button key={o.value} type="button" role="radio" data-value={o.value} aria-checked={o.value === value} tabIndex={o.value === value ? 0 : -1}
          onClick={() => onChange(o.value)} onKeyDown={(e) => move(e, i)}
          className={`relative inline-flex cursor-pointer items-center gap-1.5 rounded-sm px-3 text-sm transition-colors duration-150 ${size === "sm" ? "h-7 after:absolute after:-inset-y-1.5 after:inset-x-0" : "h-9"} ${o.value === value ? "bg-accent-bright font-semibold text-accent-fg" : "text-fg-2 hover:bg-hover hover:text-fg"}`}>
          {o.icon && <Icon name={o.icon} size={14} />}{o.label}
        </button>
      ))}
    </div>
  );
}

// ---- Combobox ----------------------------------------------------------------------------------------------------------

export type Option = { value: string; label: string; code?: string | null; hint?: string | null };

/** The list part shared by Combobox and LookupField: options with `role="option"`, the active one marked. */
export function OptionList({ id, options, active, selected, onPick, onHover, empty, labelledBy }: {
  id: string; options: Option[]; active: number; selected?: string | null; onPick: (o: Option) => void; onHover?: (i: number) => void; empty?: ReactNode; labelledBy?: string }) {
  return (
    <ul id={id} role="listbox" aria-labelledby={labelledBy}
      className="absolute inset-x-0 top-full z-(--z-popover) mt-1 max-h-72 min-w-56 animate-fade-in overflow-y-auto rounded-lg border border-line-strong bg-surface-3 p-1 shadow-md">
      {options.length === 0 && <li role="presentation" className="px-3 py-2 text-sm text-muted">{empty}</li>}
      {options.map((o, i) => (
        <li key={o.value} id={`${id}-${i}`} role="option" aria-selected={i === active} data-current={o.value === selected || undefined}
          onMouseDown={(e) => { e.preventDefault(); onPick(o); }} onMouseEnter={() => onHover?.(i)}
          ref={i === active ? (el) => el?.scrollIntoView?.({ block: "nearest" }) : undefined}
          className={`flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-sm ${i === active ? "bg-accent-soft text-title" : "text-fg"}`}>
          <span className="flex min-w-0 flex-1 flex-col">
            <bdi className="truncate">{o.label}</bdi>
            {o.hint && <bdi className="truncate text-xs text-muted">{o.hint}</bdi>}
          </span>
          {o.code && <bdi dir="ltr" className="shrink-0 font-mono text-xs text-muted">{o.code}</bdi>}
          {o.value === selected && <Icon name="check" size={14} className="shrink-0 text-accent" />}
        </li>
      ))}
    </ul>
  );
}

const LIST_KEYS = new Set(["ArrowDown", "ArrowUp", "Enter", "Escape", "Tab", "Home", "End"]);

/** A searchable choice from a known list (currencies, units, countries): type to filter by name or code; arrows,
 * Enter, Escape; the chosen option is shown as «name (code)». */
export function Combobox({ options, value, onChange, placeholder, id, ariaLabel, clearable = true, className = "", disabled, dir, testId }: {
  options: Option[]; value: string | null; onChange: (value: string | null, option?: Option) => void; placeholder?: string; id?: string; ariaLabel?: string;
  clearable?: boolean; className?: string; disabled?: boolean; dir?: "ltr" | "rtl" | "auto"; testId?: string }) {
  const { t } = useTranslation();
  const listId = useId();
  const [text, setText] = useState<string | null>(null);       // null = showing the chosen value
  const [state, setState] = useState({ open: false, active: -1 });
  const chosen = options.find((o) => o.value === value) ?? null;
  const shownLabel = chosen ? (chosen.code && chosen.code !== chosen.label ? `${chosen.label} (${chosen.code})` : chosen.label) : "";
  const filtered = useMemo(() => {
    const q = (text ?? "").trim().toLowerCase();
    if (!q) return options;
    const starts = options.filter((o) => o.code?.toLowerCase() === q || o.label.toLowerCase().startsWith(q) || o.code?.toLowerCase().startsWith(q));
    const contains = options.filter((o) => !starts.includes(o) && (o.label.toLowerCase().includes(q) || (o.hint ?? "").toLowerCase().includes(q)));
    return [...starts, ...contains];
  }, [options, text]);
  const pick = (o: Option) => { onChange(o.value, o); setText(null); setState({ open: false, active: -1 }); };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!LIST_KEYS.has(e.key)) return;
    if (e.key === "Tab" && !state.open) return;
    const next = lookupKey(state, e.key as LookupKey, filtered.length);
    if (e.key !== "Tab") e.preventDefault();
    setState(next.state);
    if (next.choose !== null) pick(filtered[next.choose]);
    else if (e.key === "Escape") setText(null);
  };
  return (
    <span className={`relative inline-flex min-w-0 ${width(className)} ${className}`}>
      <input id={id} role="combobox" data-value={value ?? ""} aria-label={ariaLabel} aria-expanded={state.open} aria-controls={listId} aria-autocomplete="list" autoComplete="off"
        aria-activedescendant={state.open && state.active >= 0 ? `${listId}-${state.active}` : undefined} disabled={disabled} dir={dir} data-testid={testId}
        value={text ?? shownLabel} placeholder={placeholder}
        onChange={(e) => { setText(e.target.value); setState({ open: true, active: 0 }); }}
        onFocus={(e) => e.target.select()} onClick={() => setState((s) => ({ open: true, active: s.active }))}
        onBlur={() => { setText(null); setState({ open: false, active: -1 }); }} onKeyDown={onKey}
        className={`${CONTROL} w-full min-w-0 pe-16`} />
      <span className="absolute end-1 top-1/2 flex -translate-y-1/2 items-center">
        {clearable && value && !disabled && (
          <button type="button" tabIndex={-1} aria-label={t("smart.clear")} onMouseDown={(e) => { e.preventDefault(); onChange(null); setText(null); }}
            className="inline-flex size-7 cursor-pointer items-center justify-center rounded-md text-muted hover:bg-hover hover:text-fg"><Icon name="x" size={13} /></button>
        )}
        <Icon name="chevronDown" size={15} className="pointer-events-none mx-1.5 text-muted" />
      </span>
      {state.open && !disabled && <OptionList id={listId} options={filtered} active={state.active} selected={value} onPick={pick}
        onHover={(i) => setState({ open: true, active: i })} empty={t("smart.noMatch")} />}
    </span>
  );
}

// ---- dates -------------------------------------------------------------------------------------------------------------

/** A date in the user's calendar (Jalali or Gregorian): type it, or open the month grid. Emits a local-midnight Date. */
export function DatePicker({ value, onChange, id, calendar: forced, className = "", disabled, ariaLabel }: {
  value: Date | null; onChange: (d: Date | null) => void; id?: string; calendar?: CalendarKind; className?: string; disabled?: boolean; ariaLabel?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const kind: CalendarKind = forced ?? f.calendar;
  const show = (d: Date | null) => (d ? f.date(d.toISOString()) : "");
  const [text, setText] = useState(show(value));
  const [invalid, setInvalid] = useState(false);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<Date>(value ?? new Date());
  const root = useRef<HTMLSpanElement>(null);
  const grid = useRef<HTMLDivElement>(null);
  const gridId = useId();
  useEffect(() => { setText(show(value)); /* re-render when the calendar or digit style changes */ }, [value, f]);     // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    grid.current?.querySelector<HTMLElement>("[tabindex='0']")?.focus();
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const commit = () => {
    if (!text.trim()) { setInvalid(false); if (value) onChange(null); return; }
    const parsed = parseDateInput(text, kind);
    setInvalid(!parsed);
    if (parsed && !sameDay(parsed, value)) onChange(parsed);
  };
  const choose = (d: Date) => { onChange(d); setInvalid(false); setOpen(false); root.current?.querySelector("input")?.focus(); };
  const [year, month] = yearMonth(cursor, kind);
  const today = new Date();
  const onGridKey = (e: KeyboardEvent) => {
    const rtl = isRtl(grid.current);
    if (e.key === "Escape") { setOpen(false); root.current?.querySelector("input")?.focus(); return; }
    const next = moveFocus(cursor, e.key, kind, rtl);
    if (!next) return;
    e.preventDefault();
    setCursor(next);
    window.requestAnimationFrame(() => grid.current?.querySelector<HTMLElement>("[tabindex='0']")?.focus());
  };
  return (
    <span ref={root} className={`relative inline-flex ${/(^|\s)w-/.test(className) ? "" : "w-40"} ${className}`}>
      <input id={id} dir="ltr" value={text} disabled={disabled} aria-label={ariaLabel} aria-invalid={invalid || undefined} inputMode="numeric" autoComplete="off"
        placeholder={kind === "jalali" ? t("date.placeholderJalali") : t("date.placeholderGregorian")}
        onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "ArrowDown" && e.altKey) setOpen(true); }}
        className={`${CONTROL} w-full pe-10 text-center tabular-nums`} />
      <IconButton icon="calendar" size="sm" label={t("ds.date.open")} disabled={disabled} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? gridId : undefined}
        onClick={() => { setCursor(value ?? new Date()); setOpen(!open); }} className="absolute end-1 top-1/2 -translate-y-1/2" />
      {open && (
        <div id={gridId} role="dialog" aria-label={t("ds.date.choose")} data-calendar={kind}
          className="absolute start-0 top-full z-(--z-popover) mt-1 w-72 animate-fade-in rounded-xl border border-line-strong bg-surface-3 p-3 shadow-md">
          <div className="mb-2 flex items-center justify-between">
            <IconButton icon="chevronStart" size="sm" label={t("ds.date.previousMonth")} onClick={() => setCursor(addMonths(cursor, -1, kind))} />
            <span className="text-sm font-semibold text-title" aria-live="polite" data-testid="date-month">{t(`ds.date.months.${kind}.${month}`)} {f.num(String(year)).replace(/[٬,]/g, "")}</span>
            <IconButton icon="chevron" size="sm" label={t("ds.date.nextMonth")} onClick={() => setCursor(addMonths(cursor, 1, kind))} />
          </div>
          <div ref={grid} role="grid" onKeyDown={onGridKey}>
            <div role="row" className="grid grid-cols-7">
              {weekdays(kind).map((w) => <span key={w} role="columnheader" aria-label={t(`ds.date.weekdays.long.${w}`)} className="flex h-8 items-center justify-center text-2xs text-muted">{t(`ds.date.weekdays.short.${w}`)}</span>)}
            </div>
            {monthGrid(cursor, kind).map((week, i) => (
              <div key={i} role="row" className="grid grid-cols-7">
                {week.map((c) => {
                  const selected = sameDay(c.date, value), focused = sameDay(c.date, cursor);
                  return (
                    <button key={c.date.getTime()} type="button" role="gridcell" tabIndex={focused ? 0 : -1} aria-selected={selected}
                      aria-current={sameDay(c.date, today) ? "date" : undefined} aria-label={f.date(c.date.toISOString())} onClick={() => choose(c.date)}
                      className={`m-px flex h-9 cursor-pointer items-center justify-center rounded-md text-sm tabular-nums transition-colors duration-150 ${selected ? "bg-accent-bright font-semibold text-accent-fg" : c.inMonth ? "text-fg hover:bg-hover" : "text-muted hover:bg-hover"} ${sameDay(c.date, today) && !selected ? "border border-accent-line" : ""}`}>
                      {f.num(String(c.day))}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="mt-2 flex justify-between border-t border-line pt-2">
            <button type="button" className="cursor-pointer rounded-sm px-2 py-1 text-xs text-accent hover:bg-hover" onClick={() => choose(new Date(today.getFullYear(), today.getMonth(), today.getDate()))}>{t("ds.date.today")}</button>
            {value && <button type="button" className="cursor-pointer rounded-sm px-2 py-1 text-xs text-muted hover:bg-hover" onClick={() => { onChange(null); setOpen(false); }}>{t("common.clear")}</button>}
          </div>
        </div>
      )}
    </span>
  );
}
export const DateInput = DatePicker;

// ---- money and quantity ----------------------------------------------------------------------------------------------

function AmountBox({ id, value, onChange, ariaLabel, disabled, invalid, placeholder, testId }: {
  id?: string; value: string | null; onChange: (v: string | null) => void; ariaLabel?: string; disabled?: boolean; invalid?: boolean; placeholder?: string; testId?: string }) {
  return (
    <input id={id} dir="ltr" inputMode="decimal" autoComplete="off" value={value ?? ""} disabled={disabled} aria-label={ariaLabel} aria-invalid={invalid || undefined}
      placeholder={placeholder} data-testid={testId} onChange={(e) => onChange(e.target.value || null)} className={`${CONTROL} min-w-0 flex-1 tabular-nums`} />
  );
}

/** Money is always an amount with its ISO 4217 currency, written left to right. */
export function MoneyInput({ id, amount, currency, onChange, currencies, disabled, invalid, amountLabel, currencyLabel, clearableCurrency = true, testId }: {
  id?: string; amount: string | null; currency: string | null; onChange: (v: { amount: string | null; currency: string | null }) => void; currencies: Option[];
  disabled?: boolean; invalid?: boolean; amountLabel?: string; currencyLabel?: string; clearableCurrency?: boolean; testId?: string }) {
  const { t } = useTranslation();
  return (
    <span className="flex min-w-0 gap-1.5" dir="ltr">
      <AmountBox id={id} value={amount} onChange={(v) => onChange({ amount: v, currency })} ariaLabel={amountLabel ?? t("ds.money.amount")} disabled={disabled} invalid={invalid} testId={testId} />
      <Combobox options={currencies} value={currency} onChange={(v) => onChange({ amount, currency: v })} ariaLabel={currencyLabel ?? t("ds.money.currency")}
        className="w-32 shrink-0" clearable={clearableCurrency} disabled={disabled} dir="ltr" placeholder="USD" testId={testId ? `${testId}-currency` : undefined} />
    </span>
  );
}

/** A quantity is an amount with its unit (a UN/ECE Recommendation 20 unit of the reference data). */
export function QuantityInput({ id, amount, unit, onChange, units, disabled, invalid, amountLabel, unitLabel, testId }: {
  id?: string; amount: string | null; unit: string | null; onChange: (v: { amount: string | null; unit: string | null }) => void; units: Option[];
  disabled?: boolean; invalid?: boolean; amountLabel?: string; unitLabel?: string; testId?: string }) {
  const { t } = useTranslation();
  return (
    <span className="flex min-w-0 gap-1.5">
      <AmountBox id={id} value={amount} onChange={(v) => onChange({ amount: v, unit })} ariaLabel={amountLabel ?? t("ds.quantity.amount")} disabled={disabled} invalid={invalid} testId={testId} />
      <Combobox options={units} value={unit} onChange={(v) => onChange({ amount, unit: v })} ariaLabel={unitLabel ?? t("ds.quantity.unit")} className="w-40 shrink-0"
        disabled={disabled} testId={testId ? `${testId}-unit` : undefined} />
    </span>
  );
}

// ---- files -------------------------------------------------------------------------------------------------------------

/** Drop files here or choose them; works with the keyboard (it is a button) and shows the dragging and busy states. */
export function FileDrop({ onFiles, accept, multiple = true, label, hint, busy, disabled, testId }: {
  onFiles: (files: File[]) => void; accept?: string; multiple?: boolean; label?: ReactNode; hint?: ReactNode; busy?: boolean; disabled?: boolean; testId?: string }) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const off = disabled || busy;
  return (
    <div data-testid={testId} data-over={over || undefined}
      onDragOver={(e) => { if (off) return; e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!off && e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); }}
      className={`rounded-xl border border-dashed transition-colors duration-150 ${over ? "border-accent bg-accent-soft" : "border-accent-line bg-transparent"} ${off ? "opacity-60" : ""}`}>
      <button type="button" disabled={off} aria-busy={busy || undefined} onClick={() => input.current?.click()}
        className="flex min-h-24 w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl px-4 py-5 text-center disabled:cursor-not-allowed">
        <Icon name="upload" size={22} className="text-accent" />
        <span className="text-sm text-accent">{label ?? t("ds.fileDrop.label")}</span>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </button>
      <input ref={input} type="file" hidden tabIndex={-1} accept={accept} multiple={multiple}
        onChange={(e) => { if (e.target.files?.length) onFiles([...e.target.files]); e.target.value = ""; }} />
    </div>
  );
}
