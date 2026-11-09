/** Smart fields (v0.9.0 section 8): the pure logic behind the shared components, so it is tested without a browser.
 *
 * - lookup keyboard navigation (arrows, Enter, Escape, Tab) for LookupField;
 * - accepting a suggested value (Tab or click) for SuggestedValue;
 * - validators that mirror the backend's (IBAN ISO 13616, BIC ISO 9362, Iranian national ID, USCC GB 32100-2015,
 *   e-mail, container ISO 6346) so a field shows its state while typing; the backend checks again on save. */

export type LookupItem = { kind: string; id: string; code: string | null; name_fa: string; name_en: string; subtitle?: string | null; match?: string };

export type LookupState = { open: boolean; active: number };

export type LookupKey = "ArrowDown" | "ArrowUp" | "Enter" | "Escape" | "Tab" | "Home" | "End";

/** The next state and the item to choose (if any) for a key in an open or closed result list. */
export function lookupKey(state: LookupState, key: LookupKey, count: number): { state: LookupState; choose: number | null } {
  if (!state.open) {
    if (key === "ArrowDown" && count) return { state: { open: true, active: 0 }, choose: null };
    return { state, choose: null };
  }
  switch (key) {
    case "ArrowDown": return { state: { open: true, active: count ? (state.active + 1) % count : -1 }, choose: null };
    case "ArrowUp": return { state: { open: true, active: count ? (state.active - 1 + count) % count : -1 }, choose: null };
    case "Home": return { state: { open: true, active: count ? 0 : -1 }, choose: null };
    case "End": return { state: { open: true, active: count - 1 }, choose: null };
    case "Enter":
    case "Tab": return { state: { open: false, active: -1 }, choose: state.active >= 0 && state.active < count ? state.active : null };
    case "Escape": return { state: { open: false, active: -1 }, choose: null };
  }
}

/** The label shown for a chosen item: «نام (کد)» in the UI language. */
export function lookupLabel(item: LookupItem, lang: string): string {
  const name = lang === "fa" ? item.name_fa || item.name_en : item.name_en || item.name_fa;
  return item.code && item.code !== name ? `${name} (${item.code})` : name;
}

export type Suggestion<T> = { value: T; source: string | null; source_kind?: string | null; source_id?: string | null };

/** A suggested value is accepted with Tab (or a click) only while the field is still empty. */
export function acceptSuggestion<T>(current: T | null | undefined | "", suggestion: Suggestion<T> | null | undefined, key: string): T | null {
  if (!suggestion || (current !== null && current !== undefined && current !== "")) return null;
  return key === "Tab" || key === "click" ? suggestion.value : null;
}

// ---- validators ------------------------------------------------------------------------------------------------------

export type Validation = { state: "empty" | "valid" | "invalid" | "partial"; normalized?: string; reason?: string };

const FA = "۰۱۲۳۴۵۶۷۸۹";
const AR = "٠١٢٣٤٥٦٧٨٩";
export function latinDigits(v: string): string {
  return v.replace(/[۰-۹]/g, (d) => String(FA.indexOf(d))).replace(/[٠-٩]/g, (d) => String(AR.indexOf(d)));
}
const clean = (v: string) => latinDigits(v).replace(/[\s\-.]/g, "").toUpperCase();

const IBAN_LENGTHS: Record<string, number> = { AE: 23, DE: 22, FR: 27, GB: 22, IR: 26, IT: 27, NL: 18, TR: 26, CH: 21, ES: 24, OM: 23, SA: 24, QA: 29, IQ: 23 };

export function validateIban(v: string): Validation {
  const s = clean(v);
  if (!s) return { state: "empty" };
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$/.test(s)) return { state: s.length < 15 ? "partial" : "invalid", reason: "format" };
  if (IBAN_LENGTHS[s.slice(0, 2)] && s.length !== IBAN_LENGTHS[s.slice(0, 2)]) {
    return { state: s.length < IBAN_LENGTHS[s.slice(0, 2)] ? "partial" : "invalid", reason: "length" };
  }
  const digits = (s.slice(4) + s.slice(0, 4)).split("").map((c) => (/[A-Z]/.test(c) ? String(c.charCodeAt(0) - 55) : c)).join("");
  let r = 0;
  for (const d of digits) r = (r * 10 + Number(d)) % 97;
  if (r !== 1) return { state: "invalid", reason: "checksum" };
  return { state: "valid", normalized: s.replace(/(.{4})/g, "$1 ").trim() };
}

export function validateBic(v: string): Validation {
  const s = clean(v);
  if (!s) return { state: "empty" };
  if (/^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$/.test(s)) return { state: "valid", normalized: s };
  return { state: s.length < 8 ? "partial" : "invalid", reason: "format" };
}

export function validateNationalIdIr(v: string): Validation {
  const s = clean(v);
  if (!s) return { state: "empty" };
  if (!/^\d+$/.test(s)) return { state: "invalid", reason: "format" };
  if (s.length < 10) return { state: "partial", reason: "length" };
  if (s.length === 10) {
    if (new Set(s).size === 1) return { state: "invalid", reason: "checksum" };
    const sum = [...s.slice(0, 9)].reduce((a, d, i) => a + Number(d) * (10 - i), 0) % 11;
    const check = sum < 2 ? sum : 11 - sum;
    return check === Number(s[9]) ? { state: "valid", normalized: s } : { state: "invalid", reason: "checksum" };
  }
  if (s.length === 11) {
    const d = Number(s[9]) + 2;
    const w = [29, 27, 23, 19, 17, 29, 27, 23, 19, 17];
    const sum = [...s.slice(0, 10)].reduce((a, c, i) => a + (Number(c) + d) * w[i], 0) % 11;
    return (sum === 10 ? 0 : sum) === Number(s[10]) ? { state: "valid", normalized: s } : { state: "invalid", reason: "checksum" };
  }
  return { state: "invalid", reason: "length" };
}

const USCC = "0123456789ABCDEFGHJKLMNPQRTUWXY";
const USCC_W = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28];

export function validateUscc(v: string): Validation {
  const s = clean(v);
  if (!s) return { state: "empty" };
  if ([...s].some((c) => !USCC.includes(c))) return { state: "invalid", reason: "format" };
  if (s.length < 18) return { state: "partial", reason: "length" };
  if (s.length > 18) return { state: "invalid", reason: "length" };
  const total = [...s.slice(0, 17)].reduce((a, c, i) => a + USCC.indexOf(c) * USCC_W[i], 0);
  return USCC[(31 - (total % 31)) % 31] === s[17] ? { state: "valid", normalized: s } : { state: "invalid", reason: "checksum" };
}

export function validateEmail(v: string): Validation {
  const s = v.trim();
  if (!s) return { state: "empty" };
  return /^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/.test(s)
    ? { state: "valid", normalized: s.toLowerCase() } : { state: s.includes("@") ? "partial" : "invalid", reason: "format" };
}

export function containerCheckDigit(prefix10: string): number {
  const values: Record<string, number> = {};
  let n = 10;
  for (const c of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") {
    if (n % 11 === 0) n++;
    values[c] = n++;
  }
  const total = [...prefix10].reduce((a, c, i) => a + (/\d/.test(c) ? Number(c) : values[c]) * 2 ** i, 0);
  return (total % 11) % 10;
}

export function validateContainer(v: string): Validation {
  const s = clean(v);
  if (!s) return { state: "empty" };
  if (!/^[A-Z]{0,3}([UJZ]\d{0,7})?$/.test(s) && !/^[A-Z]{3}[UJZ]\d{7}$/.test(s)) return { state: "invalid", reason: "format" };
  if (s.length < 11) return { state: "partial", reason: "length" };
  return containerCheckDigit(s.slice(0, 10)) === Number(s[10]) ? { state: "valid", normalized: s } : { state: "invalid", reason: "checksum" };
}

export const VALIDATORS: Record<string, (v: string) => Validation> = {
  iban: validateIban, bic: validateBic, national_id_ir: validateNationalIdIr, uscc: validateUscc, email: validateEmail,
  container: validateContainer,
};

// ---- amount in words (en; fa comes from the backend's Persian words) -------------------------------------------------

const ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
  "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];

function below1000(n: number): string {
  const out: string[] = [];
  if (n >= 100) { out.push(`${ONES[Math.floor(n / 100)]} hundred`); n %= 100; }
  if (n >= 20) out.push(TENS[Math.floor(n / 10)] + (n % 10 ? `-${ONES[n % 10]}` : ""));
  else if (n) out.push(ONES[n]);
  return out.join(" ");
}

/** The same words as the backend's ``number_words_en`` (integers up to trillions). */
export function numberWordsEn(n: number): string {
  if (n === 0) return "zero";
  const parts: string[] = [];
  for (const [size, name] of [[1e12, "trillion"], [1e9, "billion"], [1e6, "million"], [1e3, "thousand"]] as const) {
    if (n >= size) { parts.push(`${below1000(Math.floor(n / size))} ${name}`); n %= size; }
  }
  if (n) parts.push(below1000(n));
  return parts.join(" ");
}
