/** Display formatting. Values are stored/transmitted as ISO UTC; conversion happens only here. */
import { format as formatJalali, isValid, parse as parseJalali } from "date-fns-jalali";

export type Calendar = "jalali" | "gregorian";
export type Digits = "fa" | "latin";

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";

export function toFaDigits(value: string): string {
  return value.replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)]);
}

export function toLatinDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String(AR_DIGITS.indexOf(d)));
}

export function applyDigits(value: string, digits: Digits): string {
  return digits === "fa" ? toFaDigits(value) : value;
}

const pad = (n: number) => String(n).padStart(2, "0");

export interface DateOptions {
  calendar: Calendar;
  digits: Digits;
  time?: boolean;
  seconds?: boolean;
}

/** ISO string (UTC) -> local date, e.g. Jalali "1405/08/02" or Gregorian "2026/10/24". */
export function formatDate(iso: string | null | undefined, opts: DateOptions): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const day =
    opts.calendar === "jalali"
      ? formatJalali(date, "yyyy/MM/dd")
      : `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())}`;
  let text = day;
  if (opts.time) {
    text += ` ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    if (opts.seconds) text += `:${pad(date.getSeconds())}`;
  }
  return applyDigits(text, opts.digits);
}

/** Parse a user-typed date ("1405/08/02", "۱۴۰۵/۸/۲", "2026-10-24") as local midnight. */
export function parseDateInput(text: string, calendar: Calendar): Date | null {
  const clean = toLatinDigits(text.trim()).replace(/[-.]/g, "/");
  const match = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(clean);
  if (!match) return null;
  const [, y, m, d] = match.map(Number);
  if (calendar === "jalali") {
    const date = parseJalali(`${y}/${pad(m)}/${pad(d)}`, "yyyy/MM/dd", new Date(2000, 0, 1));
    return isValid(date) ? date : null;
  }
  const date = new Date(y, m - 1, d);
  return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d ? date : null;
}

const numberFormats = new Map<string, Intl.NumberFormat>();
function numberFormat(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let nf = numberFormats.get(key);
  if (!nf) { nf = new Intl.NumberFormat(locale, options); numberFormats.set(key, nf); }
  return nf;
}

/** v0.10.1 section 3.3: Intl.NumberFormat — fa-IR gives Persian digits, «٬» (U+066C) grouping and «٫» (U+066B)
 * decimals. Decimal strings are formatted exactly (no float rounding of large amounts). */
export function formatNumber(value: number | string | null | undefined, digits: Digits, maxFraction = 4): string {
  if (value === null || value === undefined || value === "") return "";
  const text = typeof value === "number" ? value : String(value).trim();
  if (typeof text === "string" && !/^-?\d+(\.\d+)?$/.test(text)) return digits === "fa" ? toFaDigits(text) : text;
  return numberFormat(digits === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: maxFraction })
    .format(text as unknown as number);   // a decimal string is accepted (Intl.NumberFormat v3) and kept exact
}

/** Currencies shown without decimals: the rial (and the toman) have no minor unit in use (section 1.5). */
export const NO_DECIMALS = new Set(["IRR", "IRT"]);

export function moneyFraction(currency: string | null | undefined, fallback = 2): number {
  return currency && NO_DECIMALS.has(currency) ? 0 : fallback;
}

/** The compact form split into the figure and its magnitude word («۴٫۱» + «میلیارد», «4.1» + «B»), so a tile can
 * show the figure large and the word with the currency beside it. */
export function compactParts(value: number | string | null | undefined, digits: Digits): { figure: string; magnitude: string } {
  const n = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(n)) return { figure: "", magnitude: "" };
  const locale = digits === "fa" ? "fa-IR" : "en-US";
  if (Math.abs(n) < 1_000_000) return { figure: numberFormat(locale, { maximumFractionDigits: 0 }).format(n), magnitude: "" };
  const parts = numberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).formatToParts(n);
  return { figure: parts.filter((p) => p.type !== "compact" && p.type !== "literal").map((p) => p.value).join(""),
    magnitude: parts.filter((p) => p.type === "compact").map((p) => p.value).join("") };
}

/** The Persian name of a common currency for compact figures («ریال», «دلار»); other codes stay as they are. */
const CURRENCY_FA: Record<string, string> = { IRR: "ریال", IRT: "تومان", USD: "دلار", EUR: "یورو", AED: "درهم", CNY: "یوان", GBP: "پوند", TRY: "لیر", RUB: "روبل", INR: "روپیه" };
export function currencyName(currency: string | null | undefined, lang: string): string {
  if (!currency) return "";
  return lang === "fa" ? CURRENCY_FA[currency] ?? currency : currency;
}

/** Compact numbers for tiles, rings and chart labels (section 3.2): «۴٫۱ میلیارد», «521.5M». Values under a million
 * keep their full grouped form («۱٬۳۷۳»). */
export function formatCompact(value: number | string | null | undefined, digits: Digits, maxFraction = 0): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const locale = digits === "fa" ? "fa-IR" : "en-US";
  if (Math.abs(n) < 1_000_000) return numberFormat(locale, { maximumFractionDigits: maxFraction }).format(n);
  return numberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

const UNITS = ["B", "KB", "MB", "GB", "TB"];
// Persian unit names avoid mixing Latin "MB" with Persian digits in right-to-left text.
const UNITS_FA = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"];

export function formatBytes(bytes: number | null | undefined, digits: Digits, lang: "fa" | "en" = "en"): string {
  if (bytes === null || bytes === undefined) return "";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const shown = unit === 0 ? String(value) : value.toFixed(value < 10 ? 1 : 0);
  return `${formatNumber(shown, digits, 1)} ${(lang === "fa" ? UNITS_FA : UNITS)[unit]}`;
}

/** Local-midnight Date -> ISO UTC string for API filters. */
export function toIsoUtc(date: Date): string {
  return date.toISOString();
}

/** v0.10.1: «شنبه ۲۴ آبان ۱۴۰۵» / «Saturday, November 14, 2026» in the user's calendar, and the time «۱۹:۳۰». */
export function formatLongDate(date: Date, lang: string, calendar: Calendar): string {
  const cal = calendar === "jalali" ? "persian" : "gregory";
  const nf = new Intl.DateTimeFormat(`${lang === "fa" ? "fa-IR" : "en-US"}-u-ca-${cal}`, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  if (lang !== "fa") return nf.format(date).replace(/ AP$/, "");
  const part = (type: string) => nf.formatToParts(date).find((p) => p.type === type)?.value ?? "";
  return `${part("weekday")} ${part("day")} ${part("month")} ${part("year")}`;
}

export function formatTime(date: Date, lang: string): string {
  return new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}
