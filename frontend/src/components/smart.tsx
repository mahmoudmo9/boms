/** Shared smart-field components (v0.9.0 section 8.5), in the current visual style so v0.10.0 can restyle them in one
 * place: LookupField, SuggestedValue, ValidatedInput, CodeChip, AmountInWords. The logic lives in lib/smart.ts. */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { acceptSuggestion, lookupKey, lookupLabel, VALIDATORS, type LookupItem, type LookupKey, type Suggestion, type Validation } from "../lib/smart";
import { Input } from "./ui";

// ---- CodeChip ------------------------------------------------------------------------------------------------------

/** A record code in a fixed-width font with a copy button: «CS-1405-0012». */
export function CodeChip({ code, copy = true }: { code: string | null | undefined; copy?: boolean }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  if (!code) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-xs" dir="ltr" data-testid="code-chip">
      <span>{code}</span>
      {copy && (
        <button type="button" className="text-muted hover:text-fg" aria-label={t("smart.copyCode")} title={copied ? t("smart.copied") : t("smart.copyCode")}
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); void navigator.clipboard?.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
          {copied ? "✓" : "⧉"}
        </button>
      )}
    </span>
  );
}

// ---- LookupField ---------------------------------------------------------------------------------------------------

/** Type a name or a code; results ranked by the backend (exact code, code prefix, name prefix, contains, similar).
 * Arrow keys move, Enter or Tab chooses, Escape closes. */
export function LookupField({ kind, value, onChange, placeholder, filters, ariaLabel, testId }: {
  kind: string;
  value: LookupItem | null;
  onChange: (item: LookupItem | null) => void;
  placeholder?: string;
  filters?: Record<string, string>;
  ariaLabel?: string;
  testId?: string;
}) {
  const { t, i18n } = useTranslation();
  const listId = useId();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [state, setState] = useState({ open: false, active: -1 });
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setQ(text), 200);
    return () => window.clearTimeout(timer.current);
  }, [text]);
  const results = useQuery({
    queryKey: ["lookup", kind, q, filters],
    queryFn: () => api<LookupItem[]>("/api/lookup", { query: { kind, q, ...filters }, background: true }),
    enabled: state.open,
  });
  // only results for exactly what is typed: Enter / Tab / arrows never act on a list that is still being replaced
  const fresh = q === text;
  const items = fresh ? results.data ?? [] : [];
  const choose = (i: number | null) => {
    if (i !== null && items[i]) { onChange(items[i]); setText(""); }
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!["ArrowDown", "ArrowUp", "Enter", "Escape", "Tab", "Home", "End"].includes(e.key)) return;
    if (e.key === "Tab" && !state.open) return;
    const next = lookupKey(state, e.key as LookupKey, items.length);
    if (e.key !== "Tab" || next.choose !== null) e.preventDefault();
    setState(next.state);
    choose(next.choose);
  };
  if (value && !state.open) {
    return (
      <div className="flex h-8 items-center justify-between gap-2 rounded-md border border-line-strong bg-surface px-2 text-sm" data-testid={testId}>
        <span className="truncate"><bdi>{lookupLabel(value, i18n.language)}</bdi></span>
        <button type="button" className="text-muted hover:text-fg" aria-label={t("smart.clear")} onClick={() => { onChange(null); setState({ open: true, active: -1 }); }}>✕</button>
      </div>
    );
  }
  return (
    <div className="relative" data-testid={testId}>
      <Input role="combobox" aria-expanded={state.open} aria-controls={listId} aria-label={ariaLabel} dir="auto" value={text}
        placeholder={placeholder ?? t("smart.typeNameOrCode")} onFocus={() => setState({ open: true, active: -1 })}
        onBlur={() => setTimeout(() => setState({ open: false, active: -1 }), 150)}
        onChange={(e) => { setText(e.target.value); setState({ open: true, active: -1 }); }} onKeyDown={onKey} />
      {state.open && (
        <ul id={listId} role="listbox" className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-md border border-line bg-surface shadow-lg">
          {items.length === 0 && <li className="p-2 text-xs text-muted">{!fresh || results.isFetching ? t("common.loading") : t("smart.noMatch")}</li>}
          {items.map((item, i) => (
            <li key={`${item.kind}-${item.id}`} role="option" aria-selected={i === state.active}
              className={`flex cursor-pointer items-center justify-between gap-2 px-2 py-1.5 text-sm ${i === state.active ? "bg-accent-soft" : "hover:bg-surface-2"}`}
              onMouseDown={(e) => { e.preventDefault(); choose(i); setState({ open: false, active: -1 }); }}>
              <span className="flex min-w-0 flex-col">
                <bdi className="truncate">{i18n.language === "fa" ? item.name_fa : item.name_en}</bdi>
                {item.subtitle && <span className="truncate text-xs text-muted"><bdi>{item.subtitle}</bdi></span>}
              </span>
              {item.code && <span className="font-mono text-xs text-muted" dir="ltr">{item.code}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- SuggestedValue ------------------------------------------------------------------------------------------------

/** A proposed value shown greyed with its source chip («از PO-1405-0007»); Tab or a click accepts it while the field is
 * empty. Wraps the field it proposes for. */
export function SuggestedValue<T>({ current, suggestion, render, onAccept, children }: {
  current: T | null | undefined | "";
  suggestion: Suggestion<T> | null | undefined;
  render?: (value: T) => ReactNode;
  onAccept: (value: T) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const show = suggestion && (current === null || current === undefined || current === "");
  return (
    <div className="flex flex-col gap-1" onKeyDown={(e) => {
      if (e.key !== "Tab" || e.shiftKey) return;
      const accepted = acceptSuggestion(current, suggestion, "Tab");
      if (accepted !== null) { e.preventDefault(); onAccept(accepted); }
    }}>
      {children}
      {show && (
        <button type="button" className="flex items-center gap-1.5 self-start text-xs text-muted" data-testid="suggested-value"
          onClick={() => { const v = acceptSuggestion(current, suggestion, "click"); if (v !== null) onAccept(v); }}>
          <span className="italic opacity-70"><bdi>{render ? render(suggestion.value) : String(suggestion.value)}</bdi></span>
          {suggestion.source && <span className="rounded border border-line px-1 font-mono" dir="ltr">{t("smart.from", { source: suggestion.source })}</span>}
          <span className="opacity-60">{t("smart.tabToAccept")}</span>
        </button>
      )}
    </div>
  );
}

// ---- ValidatedInput ------------------------------------------------------------------------------------------------

/** An input that shows valid / invalid while typing (IBAN, BIC, national ID, USCC, e-mail, container number). */
export function ValidatedInput({ kind, value, onChange, id, ariaLabel, testId }: {
  kind: keyof typeof VALIDATORS;
  value: string;
  onChange: (value: string, validation: Validation) => void;
  id?: string;
  ariaLabel?: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const v = VALIDATORS[kind](value);
  const tone = v.state === "valid" ? "border-success" : v.state === "invalid" ? "border-danger" : "";
  return (
    <div className="flex flex-col gap-0.5" data-testid={testId} data-state={v.state}>
      <Input id={id} aria-label={ariaLabel} aria-invalid={v.state === "invalid"} dir="ltr" className={tone} value={value}
        onChange={(e) => onChange(e.target.value, VALIDATORS[kind](e.target.value))}
        onBlur={() => { if (v.state === "valid" && v.normalized && v.normalized !== value) onChange(v.normalized, v); }} />
      {v.state === "invalid" && <span className="text-xs text-danger">{t(`smart.invalid.${v.reason ?? "format"}`)}</span>}
      {v.state === "valid" && <span className="text-xs text-success">✓ {t("smart.valid")}</span>}
    </div>
  );
}

// ---- AmountInWords -------------------------------------------------------------------------------------------------

/** The amount in words (fa and en) next to the field, from the same code the backend uses. */
export function AmountInWords({ amount, currency, lang }: { amount: string | number | null | undefined; currency: string; lang: "fa" | "en" }) {
  const [debounced, setDebounced] = useState(amount);
  useEffect(() => { const h = setTimeout(() => setDebounced(amount), 300); return () => clearTimeout(h); }, [amount]);
  const words = useQuery({
    queryKey: ["words", debounced, currency, lang],
    queryFn: () => api<{ words: string }>("/api/calc/words", { query: { amount: String(debounced), currency, lang }, background: true }),
    enabled: debounced !== null && debounced !== undefined && debounced !== "" && !Number.isNaN(Number(debounced)),
  });
  if (!words.data) return null;
  return <p className="text-xs text-muted" dir={lang === "fa" ? "rtl" : "ltr"} data-testid="amount-in-words">{words.data.words}</p>;
}
