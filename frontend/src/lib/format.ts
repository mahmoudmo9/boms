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

export function formatNumber(value: number | string | null | undefined, digits: Digits, maxFraction = 4): string {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value);
  const [intPart, fracPart] = text.replace(/^-/, "").split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = fracPart ? fracPart.slice(0, maxFraction).replace(/0+$/, "") : "";
  const result = (text.startsWith("-") ? "-" : "") + grouped + (frac ? `.${frac}` : "");
  return digits === "fa" ? toFaDigits(result).replace(/,/g, "٬").replace(".", "٫") : result;
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
