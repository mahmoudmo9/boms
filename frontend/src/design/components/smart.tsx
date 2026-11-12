/** The smart fields (v0.9.0 section 8, restyled in v0.10.0 as the only pickers of the app): LookupField (any record
 * or reference row by name or code), SuggestedValue (a proposed value with its source chip, Tab accepts),
 * ValidatedInput (IBAN, BIC, national ID, USCC, e-mail, container number) and AmountInWords. Logic: lib/smart.ts. */
import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../lib/api";
import { acceptSuggestion, lookupKey, lookupLabel, type LookupItem, type LookupKey, type Suggestion, type Validation, VALIDATORS } from "../../lib/smart";
import { CONTROL, OptionList, SourceChip } from "./forms";
import { Icon } from "./Icon";
import { Kbd } from "./primitives";

const LIST_KEYS = ["ArrowDown", "ArrowUp", "Enter", "Escape", "Tab", "Home", "End"];
const width = (className: string) => (/(^|\s)(w-|flex-1|grow)/.test(className) ? "" : "w-full");

/** Type a name or a code; results are ranked by the backend (exact code, code prefix, name prefix, contains,
 * similar). Arrow keys move, Enter or Tab chooses, Escape closes. The chosen row is shown as «name (code)». */
export function LookupField({ kind, value, onChange, placeholder, filters, ariaLabel, testId, id, className = "", disabled, create, renderValue }: {
  kind: string; value: LookupItem | null; onChange: (item: LookupItem | null) => void; placeholder?: string; filters?: Record<string, string>;
  ariaLabel?: string; testId?: string; id?: string; className?: string; disabled?: boolean;
  /** A last option that creates a record from the typed text («+ طرف جدید: …»). */
  create?: { label: (text: string) => string; onCreate: (text: string) => void };
  /** How the chosen value is shown (default: its name and code). */
  renderValue?: (item: LookupItem) => ReactNode }) {
  const { t, i18n } = useTranslation();
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [state, setState] = useState({ open: false, active: -1 });
  useEffect(() => {
    const timer = window.setTimeout(() => setQ(text), 200);
    return () => window.clearTimeout(timer);
  }, [text]);
  const results = useQuery({
    queryKey: ["lookup", kind, q, filters],
    queryFn: () => api<LookupItem[]>("/api/lookup", { query: { kind, q, ...filters }, background: true }),
    enabled: state.open,
  });
  // only results for exactly what is typed: Enter / Tab / arrows never act on a list that is still being replaced
  const fresh = q === text;
  const items = fresh ? results.data ?? [] : [];
  const creating = !!create && fresh && text.trim().length > 0 && !results.isFetching;
  const count = items.length + (creating ? 1 : 0);
  const choose = (i: number | null) => {
    if (i !== null && items[i]) { onChange(items[i]); setText(""); }
    else if (i !== null && creating && i === items.length) { create!.onCreate(text.trim()); setText(""); }
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!LIST_KEYS.includes(e.key)) return;
    if (e.key === "Tab" && !state.open) return;
    const next = lookupKey(state, e.key as LookupKey, count);
    if (e.key !== "Tab" || next.choose !== null) e.preventDefault();
    setState(next.state);
    choose(next.choose);
  };
  if (value && !state.open) {
    return (
      <div className={`${CONTROL} flex items-center justify-between gap-2 ${width(className)} ${className}`} data-testid={testId} data-chosen>
        <span className="min-w-0 truncate">{renderValue ? renderValue(value) : <bdi>{lookupLabel(value, i18n.language)}</bdi>}</span>
        {!disabled && (
          <button type="button" id={id} aria-label={`${t("smart.clear")}: ${lookupLabel(value, i18n.language)}`}
            onClick={() => { onChange(null); setState({ open: true, active: -1 }); window.requestAnimationFrame(() => input.current?.focus()); }}
            className="relative inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted after:absolute after:-inset-2 hover:bg-hover hover:text-fg">
            <Icon name="x" size={13} />
          </button>
        )}
      </div>
    );
  }
  return (
    <div className={`relative ${width(className)} ${className}`} data-testid={testId}>
      <input ref={input} id={id} role="combobox" aria-expanded={state.open} aria-controls={listId} aria-autocomplete="list" aria-label={ariaLabel} autoComplete="off"
        aria-activedescendant={state.open && state.active >= 0 ? `${listId}-${state.active}` : undefined} dir="auto" value={text} disabled={disabled}
        placeholder={placeholder ?? t("smart.typeNameOrCode")} onFocus={() => setState({ open: true, active: -1 })}
        onClick={() => setState((s) => (s.open ? s : { open: true, active: -1 }))}
        onBlur={() => window.setTimeout(() => setState({ open: false, active: -1 }), 150)}
        onChange={(e) => { setText(e.target.value); setState({ open: true, active: -1 }); }} onKeyDown={onKey}
        className={`${CONTROL} w-full pe-9`} />
      <Icon name="search" size={15} className="pointer-events-none absolute end-3 top-1/2 -translate-y-1/2 text-muted" />
      {state.open && (
        <OptionList id={listId} active={state.active} empty={!fresh || results.isFetching ? t("common.loading") : t("smart.noMatch")}
          options={[...items.map((item) => ({ value: `${item.kind}-${item.id}`, label: i18n.language === "fa" ? item.name_fa || item.name_en : item.name_en || item.name_fa,
            code: item.code, hint: item.subtitle })), ...(creating ? [{ value: "__create", label: create!.label(text.trim()), code: "+" }] : [])]}
          onPick={(o) => { choose(o.value === "__create" ? items.length : items.findIndex((item) => `${item.kind}-${item.id}` === o.value)); setState({ open: false, active: -1 }); }}
          onHover={(i) => setState({ open: true, active: i })} />
      )}
    </div>
  );
}

/** A proposed value shown under the field with its source chip («از PO-1405-0007»); Tab or a click accepts it while
 * the field is empty. Wraps the field it proposes for. */
export function SuggestedValue<T>({ current, suggestion, render, onAccept, children }: {
  /** The field's present value; only whether it is empty matters (a suggested price fills an amount and currency). */
  current: unknown; suggestion: Suggestion<T> | null | undefined; render?: (value: T) => ReactNode; onAccept: (value: T) => void; children: ReactNode }) {
  const { t } = useTranslation();
  const show = suggestion && (current === null || current === undefined || current === "");
  return (
    <div className="flex min-w-0 flex-col gap-1.5" onKeyDown={(e) => {
      if (e.key !== "Tab" || e.shiftKey) return;
      const accepted = acceptSuggestion(current as T | null | undefined | "", suggestion, "Tab");
      if (accepted !== null) { e.preventDefault(); onAccept(accepted); }
    }}>
      {children}
      {show && (
        <button type="button" data-testid="suggested-value" onClick={() => { const v = acceptSuggestion(current as T | null | undefined | "", suggestion, "click"); if (v !== null) onAccept(v); }}
          className="flex min-h-6 cursor-pointer flex-wrap items-center gap-1.5 self-start rounded-sm text-start text-xs text-muted hover:text-fg">
          <span className="text-fg-2"><bdi>{render ? render(suggestion.value) : String(suggestion.value)}</bdi></span>
          {suggestion.source && <SourceChip><bdi dir="ltr">{t("smart.from", { source: suggestion.source })}</bdi></SourceChip>}
          <Kbd>Tab</Kbd>
          <span className="sr-only">{t("smart.tabToAccept")}</span>
        </button>
      )}
    </div>
  );
}

/** An input that shows valid / invalid while typing, with an icon and a word (never by colour alone). */
export function ValidatedInput({ kind, value, onChange, id, ariaLabel, testId, className = "", placeholder }: {
  kind: keyof typeof VALIDATORS; value: string; onChange: (value: string, validation: Validation) => void; id?: string; ariaLabel?: string; testId?: string;
  className?: string; placeholder?: string }) {
  const { t } = useTranslation();
  const noteId = useId();
  const v = VALIDATORS[kind](value);
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${width(className)} ${className}`} data-testid={testId} data-state={v.state}>
      <span className="relative">
        <input id={id} aria-label={ariaLabel} aria-invalid={v.state === "invalid" || undefined} aria-describedby={v.state === "invalid" || v.state === "valid" ? noteId : undefined}
          dir="ltr" value={value} placeholder={placeholder} autoComplete="off"
          onChange={(e) => onChange(e.target.value, VALIDATORS[kind](e.target.value))}
          onBlur={() => { if (v.state === "valid" && v.normalized && v.normalized !== value) onChange(v.normalized, v); }}
          className={`${CONTROL} w-full pe-9 font-mono tracking-wide ${v.state === "valid" ? "border-success" : ""}`} />
        {v.state === "valid" && <Icon name="checkCircle" size={15} className="pointer-events-none absolute end-3 top-1/2 -translate-y-1/2 text-success" />}
        {v.state === "invalid" && <Icon name="alert" size={15} className="pointer-events-none absolute end-3 top-1/2 -translate-y-1/2 text-danger" />}
      </span>
      {v.state === "invalid" && <span id={noteId} className="text-xs text-danger">{t(`smart.invalid.${v.reason ?? "format"}`)}</span>}
      {v.state === "valid" && <span id={noteId} className="text-xs text-success">{t("smart.valid")}</span>}
    </div>
  );
}

/** The amount in words (fa or en) next to the field, from the same code the backend uses. */
export function AmountInWords({ amount, currency, lang }: { amount: string | number | null | undefined; currency: string; lang: "fa" | "en" }) {
  const [debounced, setDebounced] = useState(amount);
  useEffect(() => { const h = setTimeout(() => setDebounced(amount), 300); return () => clearTimeout(h); }, [amount]);
  const words = useQuery({
    queryKey: ["words", debounced, currency, lang],
    queryFn: () => api<{ words: string }>("/api/calc/words", { query: { amount: String(debounced), currency, lang }, background: true }),
    enabled: debounced !== null && debounced !== undefined && debounced !== "" && !Number.isNaN(Number(debounced)),
  });
  if (!words.data) return null;
  return <p className="text-xs text-muted" dir={lang === "fa" ? "rtl" : "ltr"} lang={lang} data-testid="amount-in-words">{words.data.words}</p>;
}
