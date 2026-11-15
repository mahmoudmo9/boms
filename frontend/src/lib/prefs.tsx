/** Language / direction / theme application and formatting helpers bound to the user's choices. */
import { useMemo } from "react";

import i18n from "../i18n";
import { useAuth } from "./auth";
import { fromDateString } from "./followups";
import { type Calendar, compactParts, currencyName, type Digits, formatBytes, formatCompact, formatDate, formatLongDate, formatNumber, formatTime, moneyFraction } from "./format";
import type { Language, Theme } from "./types";

let mediaListener: ((e: MediaQueryListEvent) => void) | null = null;

export function applyLanguage(lang: Language) {
  const html = document.documentElement;
  html.lang = lang;
  html.dir = lang === "fa" ? "rtl" : "ltr";
  if (i18n.language !== lang) void i18n.changeLanguage(lang);
  try {
    localStorage.setItem("boms.lang", lang);
  } catch {
    /* storage unavailable: per-viewer convenience only */
  }
}

export function applyTheme(theme: Theme) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const set = (dark: boolean) => document.documentElement.classList.toggle("dark", dark);
  document.documentElement.dataset.theme = theme;
  if (mediaListener) media.removeEventListener("change", mediaListener);
  mediaListener = null;
  if (theme === "system") {
    set(media.matches);
    mediaListener = (e) => set(e.matches);
    media.addEventListener("change", mediaListener);
  } else {
    set(theme === "dark");
  }
  try {
    localStorage.setItem("boms.theme", theme);
  } catch {
    /* ignore */
  }
}

export function storedTheme(): Theme {
  try {
    const value = localStorage.getItem("boms.theme");
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export interface Formatters {
  lang: Language;
  calendar: Calendar;
  digits: Digits;
  date: (iso: string | null | undefined, time?: boolean) => string;
  num: (value: number | string | null | undefined, maxFraction?: number) => string;
  bytes: (value: number | null | undefined) => string;
  /** Date-only value "YYYY-MM-DD" (no time zone), shown in the user's calendar. */
  day: (value: string | null | undefined) => string;
  /** v0.10.1: an amount in full, with the currency's decimals (none for the rial). */
  money: (value: number | string | null | undefined, currency?: string | null) => string;
  /** v0.10.1: compact for tiles, rings and chart labels («۴٫۱ میلیارد»); under a million in full. */
  compact: (value: number | string | null | undefined) => string;
  /** v0.10.1: compact with the currency — fa «۴٫۱ میلیارد ریال», en «IRR 4.1B» — and the full value for the tooltip. */
  compactMoney: (value: number | string | null | undefined, currency?: string | null) => { text: string; full: string; figure: string; unit: string };
  /** v0.10.1: «شنبه ۲۴ آبان ۱۴۰۵» in the user's calendar, and «۱۹:۳۰». */
  longDate: (date: Date) => string;
  time: (date: Date) => string;
}

/** v0.9.0: digits follow the UI language everywhere in the UI (Persian digits in fa, Latin in en); the calendar stays
 * the user's own setting. */
export function digitsFor(lang: Language): Digits {
  return lang === "fa" ? "fa" : "latin";
}

export function useFormat(): Formatters {
  const { user } = useAuth();
  const lang = (user?.language ?? (i18n.language as Language)) || "fa";
  const calendar: Calendar = user?.calendar ?? (lang === "fa" ? "jalali" : "gregorian");
  const digits: Digits = digitsFor(lang);
  return useMemo(
    () => ({
      lang,
      calendar,
      digits,
      date: (iso, time = false) => formatDate(iso, { calendar, digits, time }),
      num: (value, maxFraction = 4) => formatNumber(value, digits, maxFraction),
      bytes: (value) => formatBytes(value, digits, lang),
      day: (value) => (value ? formatDate(fromDateString(value).toISOString(), { calendar, digits }) : ""),
      money: (value, currency) => formatNumber(value, digits, moneyFraction(currency)),
      compact: (value) => formatCompact(value, digits),
      longDate: (date) => formatLongDate(date, lang, calendar),
      time: (date) => formatTime(date, lang),
      compactMoney: (value, currency) => {
        const name = currencyName(currency, lang);
        const full = formatNumber(value, digits, moneyFraction(currency));
        const text = formatCompact(value, digits);
        const { figure, magnitude } = compactParts(value, digits);
        return lang === "fa"
          ? { text: name ? `${text} ${name}` : text, full: name ? `${full} ${name}` : full, figure, unit: [magnitude, name].filter(Boolean).join(" ") }
          : { text: currency ? `${currency} ${text}` : text, full: currency ? `${currency} ${full}` : full, figure: `${figure}${magnitude}`, unit: currency ?? "" };
      },
    }),
    [lang, calendar, digits],
  );
}
