/** Noun-modifier attribute editor (v0.10.0 section 0.2.3): the pure logic, tested without a browser.
 *
 * A template has a noun and ordered attributes (text, number with a UN/ECE unit and an optional range, or a choice of
 * allowed values). The checks mirror `catalog/nounmod.py` so a field shows its problem while typing; the backend
 * validates again on save and builds the canonical description (one source of truth, fetched live as a preview). */
import { latinDigits } from "./smart";

export type TemplateAttribute = {
  key: string; label_fa?: string; label_en?: string; type?: "text" | "number" | "choice"; short?: boolean;
  unit?: string; unit_en?: string; unit_fa?: string; min?: number; max?: number;
  values?: { value: string; fa: string; en: string }[];
};

export type ProductTemplate = { id: string; key: string; noun_fa: string; noun_en: string; attributes: TemplateAttribute[]; status: string };

export type NounValue = { template_id: string | null; attributes: Record<string, string>; canonical_fa: string | null; canonical_en: string | null;
  canonical_override: boolean };

export const EMPTY_NOUN: NounValue = { template_id: null, attributes: {}, canonical_fa: null, canonical_en: null, canonical_override: false };

export type AttributeProblem = "not_a_number" | "out_of_range" | "not_allowed" | "too_long";

/** «۱۲۰٫۵» / "1,200" -> "120.5" / "1200"; null when it is not a number. */
export function parseNumber(value: string): string | null {
  const s = latinDigits(value).replace(/٫/g, ".").replace(/[,٬\s]/g, "");
  return /^-?(\d+(\.\d*)?|\.\d+)$/.test(s) ? s : null;
}

/** The problem with one value, or null when it fits the attribute (an empty value is always allowed). */
export function attributeProblem(a: TemplateAttribute, value: string | null | undefined): AttributeProblem | null {
  if (value === null || value === undefined || value === "") return null;
  if (a.type === "number") {
    const n = parseNumber(value);
    if (n === null) return "not_a_number";
    if ((a.min !== undefined && Number(n) < a.min) || (a.max !== undefined && Number(n) > a.max)) return "out_of_range";
    return null;
  }
  if (a.type === "choice") return (a.values ?? []).some((v) => v.value === value) ? null : "not_allowed";
  return value.trim().length > 200 ? "too_long" : null;
}

/** Every problem of the entered values, by attribute key. */
export function attributeProblems(template: ProductTemplate | null | undefined, values: Record<string, string>): Record<string, AttributeProblem> {
  const out: Record<string, AttributeProblem> = {};
  for (const a of template?.attributes ?? []) {
    const p = attributeProblem(a, values[a.key]);
    if (p) out[a.key] = p;
  }
  return out;
}

/** The values to send: only the template's attributes, numbers in Latin digits, empty ones left out. */
export function cleanAttributes(template: ProductTemplate | null | undefined, values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const a of template?.attributes ?? []) {
    const v = values[a.key];
    if (v === null || v === undefined || String(v).trim() === "") continue;
    out[a.key] = a.type === "number" ? parseNumber(String(v)) ?? String(v) : String(v).trim();
  }
  return out;
}

/** Changing the template keeps the values of attributes the new template also has (same key and still valid). */
export function carryAttributes(next: ProductTemplate | null | undefined, values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const a of next?.attributes ?? []) {
    if (values[a.key] && !attributeProblem(a, values[a.key])) out[a.key] = values[a.key];
  }
  return out;
}

/** The request body fields for a product or a line item. With an override the owner's two texts are sent; without
 * one the backend generates them, so they are not sent. */
export function nounBody(template: ProductTemplate | null | undefined, v: NounValue): Record<string, unknown> {
  const body: Record<string, unknown> = { template_id: v.template_id, attributes: cleanAttributes(template, v.attributes),
    canonical_override: v.canonical_override };
  if (v.canonical_override) {
    body.canonical_fa = v.canonical_fa?.trim() || null;
    body.canonical_en = v.canonical_en?.trim() || null;
  }
  return body;
}

export function sameNoun(a: NounValue, b: NounValue): boolean {
  const keys = new Set([...Object.keys(a.attributes), ...Object.keys(b.attributes)]);
  return a.template_id === b.template_id && a.canonical_override === b.canonical_override
    && (a.canonical_fa ?? "") === (b.canonical_fa ?? "") && (a.canonical_en ?? "") === (b.canonical_en ?? "")
    && [...keys].every((k) => (a.attributes[k] ?? "") === (b.attributes[k] ?? ""));
}

export function nounOf(row: Partial<NounValue> | null | undefined): NounValue {
  return { template_id: row?.template_id ?? null, attributes: { ...(row?.attributes ?? {}) }, canonical_fa: row?.canonical_fa ?? null,
    canonical_en: row?.canonical_en ?? null, canonical_override: Boolean(row?.canonical_override) };
}
