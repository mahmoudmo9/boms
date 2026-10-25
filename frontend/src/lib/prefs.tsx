/** Language / direction / theme application and formatting helpers bound to the user's choices. */
import { useMemo } from "react";

import i18n from "../i18n";
import { useAuth } from "./auth";
import { fromDateString } from "./followups";
import { type Calendar, type Digits, formatBytes, formatDate, formatNumber } from "./format";
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
}

export function useFormat(): Formatters {
  const { user } = useAuth();
  const lang = (user?.language ?? (i18n.language as Language)) || "fa";
  const calendar: Calendar = user?.calendar ?? (lang === "fa" ? "jalali" : "gregorian");
  const digits: Digits = user?.digits ?? (lang === "fa" ? "fa" : "latin");
  return useMemo(
    () => ({
      lang,
      calendar,
      digits,
      date: (iso, time = false) => formatDate(iso, { calendar, digits, time }),
      num: (value, maxFraction = 4) => formatNumber(value, digits, maxFraction),
      bytes: (value) => formatBytes(value, digits, lang),
      day: (value) => (value ? formatDate(fromDateString(value).toISOString(), { calendar, digits }) : ""),
    }),
    [lang, calendar, digits],
  );
}
