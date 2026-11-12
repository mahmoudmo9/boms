/** The command palette (v0.10.0 section 3): what it lists for a query. Pure, tested without a browser.
 *
 * One field over `/api/search` (which ranks an exact code first and already groups cases, listings, parties,
 * products, documents and records by code) plus the palette's own actions. With an empty field it lists the recent
 * items and the main actions. Arrow keys move through one flat list across the groups. */
import { WORKSPACES } from "./nav";
import type { SearchGroup, SearchHit } from "./types";

export type PaletteRun =
  | { kind: "navigate"; to: string }
  | { kind: "theme"; theme: "light" | "dark" | "system" }
  | { kind: "language"; language: "fa" | "en" };

export type PaletteAction = { id: string; labelKey: string; labelValues?: Record<string, string>; icon: string; keywords: string[]; run: PaletteRun; hint?: string };

export type Recent = { id: string; type: string; title: string; subtitle: string | null; link: string };

export type PaletteRow =
  | { kind: "hit"; key: string; group: string; hit: SearchHit; title: string; exact: boolean }
  | { kind: "recent"; key: string; recent: Recent }
  | { kind: "action"; key: string; action: PaletteAction };

export type PaletteSection = { key: string; labelKey: string; rows: PaletteRow[] };

/** Search groups the palette shows, in the order the mockup names them; others follow in the server's order. */
export const GROUP_ICON: Record<string, string> = {
  case: "folder", listing: "file", party: "user", contact: "user", product: "box", document: "file", code: "tag", inquiry: "inbox", quote: "receipt",
  sales_order: "receipt", purchase_order: "receipt", shipment: "ship", sales_invoice: "receipt", purchase_invoice: "receipt", payment: "bank",
  claim: "alert", interaction: "inbox", cost_sheet: "scale", process_step: "check", actual_cost: "coins",
};

export function staticActions(): PaletteAction[] {
  const settings = WORKSPACES.find((w) => w.key === "settings")?.children ?? [];
  return [
    { id: "new-inquiry", labelKey: "palette.action.newInquiry", icon: "plus", keywords: ["inquiry", "rfq", "استعلام", "درخواست"], run: { kind: "navigate", to: "/sourcing?new=1" }, hint: "N" },
    { id: "new-party", labelKey: "palette.action.newParty", icon: "users", keywords: ["party", "supplier", "buyer", "طرف", "تامین", "خریدار"], run: { kind: "navigate", to: "/parties?new=1" } },
    { id: "new-task", labelKey: "palette.action.newTask", icon: "check", keywords: ["task", "todo", "کار"], run: { kind: "navigate", to: "/tasks?new=1" } },
    ...settings.map((c) => ({ id: `settings-${c.key}`, labelKey: "palette.action.openSettings", labelValues: { page: `nav.sub.${c.key}` }, icon: "settings",
      keywords: ["settings", "تنظیمات", c.key], run: { kind: "navigate", to: c.path } as PaletteRun })),
    ...(["light", "dark", "system"] as const).map((theme) => ({ id: `theme-${theme}`, labelKey: `palette.action.theme.${theme}`, icon: theme === "light" ? "sun" : theme === "dark" ? "moon" : "monitor",
      keywords: ["theme", "dark", "light", "تم", "تیره", "روشن"], run: { kind: "theme", theme } as PaletteRun })),
    ...(["fa", "en"] as const).map((language) => ({ id: `lang-${language}`, labelKey: `palette.action.language.${language}`, icon: "globe",
      keywords: ["language", "زبان", "english", "فارسی"], run: { kind: "language", language } as PaletteRun })),
  ];
}

const FA_FOLD: Record<string, string> = { "ي": "ی", "ك": "ک", "ى": "ی", "ة": "ه", "ۀ": "ه", "‌": " " };
/** Comparison form: case, Arabic/Persian letter variants and digits unified. */
export function fold(text: string): string {
  return text.replace(/[يكىةۀ‌]/g, (c) => FA_FOLD[c]).replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d))).toLowerCase().trim();
}

/** Actions whose label or keywords contain every word of the query. `label` gives the action's text in the UI language. */
export function matchActions(actions: PaletteAction[], q: string, label: (a: PaletteAction) => string): PaletteAction[] {
  const words = fold(q).split(/\s+/).filter(Boolean);
  if (!words.length) return actions;
  return actions.filter((a) => {
    const hay = fold([label(a), ...a.keywords].join(" "));
    return words.every((w) => hay.includes(w));
  });
}

/** Builds the sections: for a query the search groups (exact code first, as the server ranks), then the actions with
 * «new inquiry for "<q>"» first; with no query the recent items and the main actions. */
export function buildSections({ q, groups, actions, recent, label, titleOf }: {
  q: string; groups: SearchGroup[]; actions: PaletteAction[]; recent: Recent[]; label: (a: PaletteAction) => string; titleOf: (hit: SearchHit) => string }): PaletteSection[] {
  const query = q.trim();
  if (!query) {
    const out: PaletteSection[] = [];
    if (recent.length) out.push({ key: "recent", labelKey: "palette.recent", rows: recent.map((r) => ({ kind: "recent", key: `recent-${r.type}-${r.id}`, recent: r })) });
    const main = actions.filter((a) => a.id.startsWith("new-") || a.id.startsWith("theme-") || a.id.startsWith("lang-"));
    out.push({ key: "actions", labelKey: "palette.actions", rows: main.map((a) => ({ kind: "action", key: a.id, action: a })) });
    return out;
  }
  const out: PaletteSection[] = groups.map((g) => ({
    key: g.type, labelKey: g.label_key,
    rows: g.items.map((hit) => ({ kind: "hit", key: `${g.type}-${hit.id}`, group: g.type, hit, title: titleOf(hit),
      exact: (hit as SearchHit & { match?: string }).match === "exact_code" })),
  }));
  const forQuery: PaletteAction = { ...actions.find((a) => a.id === "new-inquiry")!, id: "new-inquiry-for", labelKey: "palette.action.newInquiryFor",
    labelValues: { q: query }, run: { kind: "navigate", to: `/sourcing?new=1&subject=${encodeURIComponent(query)}` } };
  const matched = matchActions(actions, query, label);
  out.push({ key: "actions", labelKey: "palette.actions", rows: [forQuery, ...matched].map((a) => ({ kind: "action", key: a.id, action: a })) });
  return out;
}

export function flatten(sections: PaletteSection[]): PaletteRow[] {
  return sections.flatMap((s) => s.rows);
}

/** The next active row for a key; wraps at both ends. */
export function moveActive(active: number, key: "ArrowDown" | "ArrowUp" | "Home" | "End", count: number): number {
  if (count === 0) return -1;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return key === "ArrowDown" ? (active + 1) % count : (active - 1 + count) % count;
}

/** The text cut around every occurrence of the query (folded), to mark the matched part. */
export function highlight(text: string, q: string): { text: string; match: boolean }[] {
  const needle = fold(q);
  if (!needle) return [{ text, match: false }];
  const hay = fold(text);
  if (hay.length !== text.length) return [{ text, match: false }];     // folding changed the length: no safe offsets
  const out: { text: string; match: boolean }[] = [];
  let at = 0;
  for (let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + needle.length)) {
    if (i > at) out.push({ text: text.slice(at, i), match: false });
    out.push({ text: text.slice(i, i + needle.length), match: true });
    at = i + needle.length;
  }
  if (at < text.length) out.push({ text: text.slice(at), match: false });
  return out.length ? out : [{ text, match: false }];
}

// ---- recent items ------------------------------------------------------------------------------------------------------

const RECENT_KEY = "boms.palette.recent";
export const RECENT_MAX = 8;

/** Adds an opened item to the front of the recent list (no duplicates, at most RECENT_MAX). */
export function pushRecent(list: Recent[], item: Recent): Recent[] {
  return [item, ...list.filter((r) => !(r.type === item.type && r.id === item.id))].slice(0, RECENT_MAX);
}

export function loadRecent(): Recent[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((r) => r && typeof r.link === "string" && r.link.startsWith("/")).slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

export function saveRecent(list: Recent[]): void {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* per-browser convenience only */ }
}

/** Whether the palette may open on «/»: not while the user is typing in a field. */
export function slashOpens(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return true;
  return !(["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
}
