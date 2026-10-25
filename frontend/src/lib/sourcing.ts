/** Pure sourcing helpers (tested): template placeholders, pasted-table parser, import column mapping,
 * comparison flattening. They mirror the backend rules so the UI can preview before saving. */

import type { ComparisonItem, ComparisonRow } from "./types";

// ---- message templates ---------------------------------------------------------------------------

export const PLACEHOLDERS = ["supplier_name", "contact_name", "case_title", "items_table", "respond_by", "signature"] as const;
const TOKEN = /\{\{|\}\}|\{([^{}]*)\}|[{}]/g;

/** Placeholder names used in a template; "unbalanced" when a single brace has no partner. */
export function placeholdersIn(template: string): { names: string[]; unbalanced: boolean } {
  const names: string[] = [];
  let unbalanced = false;
  for (const match of template.matchAll(TOKEN)) {
    if (match[0] === "{{" || match[0] === "}}") continue;
    if (match[1] === undefined) unbalanced = true;
    else names.push(match[1].trim());
  }
  return { names, unbalanced };
}

export function unknownPlaceholders(...templates: string[]): string[] {
  const known = new Set<string>(PLACEHOLDERS);
  return [...new Set(templates.flatMap((t) => placeholdersIn(t).names).filter((n) => !known.has(n)))].sort();
}

/** Replace {name} with values; {{ and }} are literal braces; unknown names stay as written. */
export function renderTemplate(template: string, values: Record<string, string>): string {
  return template.replace(TOKEN, (token, name: string | undefined) => {
    if (token === "{{") return "{";
    if (token === "}}") return "}";
    if (name === undefined) return token;
    const key = name.trim();
    return key in values ? values[key] : token;
  });
}

// ---- item import: pasted table / text list ----------------------------------------------------------

export type Delimiter = "auto" | "tab" | "comma" | "semicolon" | "lines";
const SEPARATORS: Record<string, string> = { tab: "\t", comma: ",", semicolon: ";" };

function splitCsvLine(line: string, sep: string): string[] {
  const out: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === sep) { out.push(cell); cell = ""; }
    else cell += ch;
  }
  out.push(cell);
  return out.map((c) => c.trim());
}

/** Rows of cells. Tab/semicolon/comma tables are split; a plain list keeps one column (bullets removed). */
export function parsePasted(text: string, delimiter: Delimiter = "auto"): string[][] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n").filter((l) => l.trim());
  if (lines.length === 0) return [];
  const sample = lines.slice(0, 20);
  let sep = SEPARATORS[delimiter];
  if (!sep && delimiter === "auto") {
    if (sample.some((l) => l.includes("\t"))) sep = "\t";
    else if (sample.join("\n").split(";").length - 1 >= sample.length) sep = ";";
    else if (sample.every((l) => l.includes(","))) sep = ",";
  }
  if (!sep) return lines.map((l) => [l.replace(/^\s*(?:[-*•·]|\(?\d+[.)-])\s*/, "").trim()]);
  return lines.map((l) => splitCsvLine(l, sep));
}

export type ImportField = "name" | "description" | "quantity" | "unit" | "target_price" | "target_currency" | "packaging"
  | "hs_code" | "required_by" | "incoterm" | "incoterm_place" | "notes" | "spec";

export interface ColumnMapping {
  column: number;
  field: ImportField;
  spec_key?: string;
}

export const IMPORT_FIELDS: ImportField[] = ["name", "description", "quantity", "unit", "target_price", "target_currency",
  "packaging", "hs_code", "required_by", "incoterm", "notes", "spec"];

const HINTS: [ImportField, string[]][] = [
  ["name", ["name", "item", "product", "goods", "نام", "کالا", "شرح کالا", "قلم"]],
  ["description", ["description", "desc", "spec", "specification", "شرح", "توضیحات", "مشخصات"]],
  ["quantity", ["qty", "quantity", "amount", "تعداد", "مقدار"]],
  ["unit", ["unit", "uom", "واحد"]],
  ["target_price", ["price", "target price", "unit price", "قیمت"]],
  ["target_currency", ["currency", "cur", "ارز"]],
  ["packaging", ["packaging", "packing", "بسته‌بندی", "بسته بندی"]],
  ["hs_code", ["hs", "hs code", "tariff", "تعرفه", "کد تعرفه"]],
  ["required_by", ["required by", "delivery date", "due", "تاریخ تحویل"]],
  ["incoterm", ["incoterm", "incoterms", "terms", "شرایط تحویل"]],
  ["notes", ["notes", "note", "remarks", "یادداشت"]],
];

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";

export function toNumberText(value: string): string | null {
  let text = (value ?? "").trim();
  if (!text) return null;
  text = text.replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d))).replace(/[٠-٩]/g, (d) => String(AR_DIGITS.indexOf(d)));
  text = text.replace(/[٬،\s]/g, "").replace("٫", ".");
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(text)) text = text.replace(/,/g, "");
  else if (/^\d+,\d+$/.test(text)) text = text.replace(",", ".");
  return /^-?\d+(\.\d+)?$/.test(text) ? text : null;
}

/** Suggest a field per column from a header row; without a header: name, then quantity and unit if numeric. */
export function suggestMapping(rows: string[][]): { mapping: ColumnMapping[]; hasHeader: boolean } {
  if (rows.length === 0) return { mapping: [], hasHeader: false };
  const header = rows[0].map((c) => c.trim().toLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک"));
  const mapping: ColumnMapping[] = [];
  const used = new Set<ImportField>();
  header.forEach((cell, column) => {
    const hit = HINTS.find(([field, hints]) => !used.has(field) && cell && hints.some((h) => cell === h || cell.startsWith(h)));
    if (hit) { mapping.push({ column, field: hit[0] }); used.add(hit[0]); }
  });
  if (mapping.length) {
    if (!used.has("name")) {
      const free = header.findIndex((_, i) => !mapping.some((m) => m.column === i));
      if (free >= 0) mapping.push({ column: free, field: "name" });
    }
    return { mapping: mapping.sort((a, b) => a.column - b.column), hasHeader: true };
  }
  const width = Math.max(...rows.map((r) => r.length));
  const result: ColumnMapping[] = [{ column: 0, field: "name" }];
  if (width > 1 && rows.every((r) => !r[1] || toNumberText(r[1]) !== null)) {
    result.push({ column: 1, field: "quantity" });
    if (width > 2) result.push({ column: 2, field: "unit" });
  }
  return { mapping: result, hasHeader: false };
}

/** Change the field of one column; a field (other than spec) can be mapped to only one column. */
export function setColumnField(mapping: ColumnMapping[], column: number, field: ImportField | "", specKey?: string): ColumnMapping[] {
  const rest = mapping.filter((m) => m.column !== column && (field === "spec" || m.field !== field));
  if (!field) return rest;
  return [...rest, { column, field, ...(field === "spec" ? { spec_key: specKey ?? "" } : {}) }].sort((a, b) => a.column - b.column);
}

// ---- comparison --------------------------------------------------------------------------------------

export interface ComparisonLine {
  kind: "group";
  currency: string;
  unitGroup: string;
  comparable: boolean;
}

export type ComparisonDisplayRow = ComparisonLine | ({ kind: "row" } & ComparisonRow);

/** Flatten the server's groups into display lines: a header per (currency, unit group), then its rows with the
 * lowest price first (rows without a ranking keep their order). */
export function flattenComparison(item: ComparisonItem): ComparisonDisplayRow[] {
  const out: ComparisonDisplayRow[] = [];
  for (const group of item.groups) {
    for (const unit of group.unit_groups) {
      out.push({ kind: "group", currency: group.currency, unitGroup: unit.unit_group, comparable: unit.comparable });
      const rows = unit.comparable
        ? [...unit.rows].sort((a, b) => Number(a.normalized_price ?? Infinity) - Number(b.normalized_price ?? Infinity))
        : unit.rows;
      rows.forEach((row) => out.push({ kind: "row", ...row }));
    }
  }
  return out;
}

export function validityTone(daysLeft: number | null): "danger" | "warning" | "neutral" {
  if (daysLeft === null) return "neutral";
  if (daysLeft < 7) return "danger";
  return daysLeft < 14 ? "warning" : "neutral";
}
