/** v0.10.0 command palette: ranking (exact code first, as the server ranks), groups, actions, recent items, keyboard. */
import { describe, expect, it } from "vitest";

import { buildSections, flatten, fold, highlight, matchActions, moveActive, type PaletteAction, pushRecent, type Recent, slashOpens, staticActions } from "./palette";
import type { SearchGroup } from "./types";

const hit = (id: string, title: string, match = "name_contains", subtitle: string | null = null) =>
  ({ id, title, link: `/x/${id}`, score: 1, subtitle, title_i18n: null, extra: {}, match });
const GROUPS: SearchGroup[] = [
  { type: "code", label_key: "search.type.code", items: [hit("c1", "CS-1405-0003", "exact_code", "Pumps")] },
  { type: "case", label_key: "search.type.case", items: [hit("k1", "پمپ صنعتی و شیرآلات"), hit("k2", "پمپ‌های آتش‌نشانی")] },
  { type: "party", label_key: "search.type.party", items: [hit("p1", "Shanghai Valve")] },
] as SearchGroup[];
const actions = staticActions();
const label = (a: PaletteAction) => a.labelKey;

describe("sections", () => {
  it("for a query: the server's groups in its order (exact code first), then the actions with «new inquiry for…» first", () => {
    const s = buildSections({ q: "CS-1405-0003", groups: GROUPS, actions, recent: [], label, titleOf: (h) => h.title });
    expect(s.map((x) => x.key)).toEqual(["code", "case", "party", "actions"]);
    const rows = flatten(s);
    expect(rows[0]).toMatchObject({ kind: "hit", exact: true, title: "CS-1405-0003" });
    const firstAction = s[3].rows[0];
    expect(firstAction.kind === "action" && firstAction.action.id).toBe("new-inquiry-for");
    expect(firstAction.kind === "action" && firstAction.action.run).toEqual({ kind: "navigate", to: "/sourcing?new=1&subject=CS-1405-0003" });
  });
  it("with no query: recent items, then the main actions", () => {
    const recent: Recent[] = [{ id: "k1", type: "case", title: "Pumps", subtitle: null, link: "/cases/k1" }];
    const s = buildSections({ q: " ", groups: GROUPS, actions, recent, label, titleOf: (h) => h.title });
    expect(s.map((x) => x.key)).toEqual(["recent", "actions"]);
    expect(s[1].rows.map((r) => r.key)).toEqual(["new-inquiry", "new-party", "new-task", "theme-light", "theme-dark", "theme-system", "lang-fa", "lang-en"]);
    expect(buildSections({ q: "", groups: [], actions, recent: [], label, titleOf: (h) => h.title }).map((x) => x.key)).toEqual(["actions"]);
  });
  it("actions match their label or keywords in either language, every word", () => {
    const named = (a: PaletteAction) => ({ "palette.action.theme.dark": "Dark theme", "palette.action.newParty": "طرف تجاری جدید" } as Record<string, string>)[a.labelKey] ?? "";
    expect(matchActions(actions, "dark", named).map((a) => a.id)).toContain("theme-dark");
    expect(matchActions(actions, "تيره", named).map((a) => a.id)).toContain("theme-dark");       // Arabic ي folds to ی
    expect(matchActions(actions, "طرف جدید", named).map((a) => a.id)).toEqual(["new-party"]);
    expect(matchActions(actions, "تنظیمات", named).every((a) => a.id.startsWith("settings-"))).toBe(true);
    expect(matchActions(actions, "zzz", named)).toEqual([]);
  });
  it("every settings page has an action", () => {
    expect(actions.filter((a) => a.id.startsWith("settings-")).map((a) => (a.run as { to: string }).to)).toContain("/settings/ai");
  });
});

describe("keyboard and marking", () => {
  it("arrows wrap, Home and End jump", () => {
    expect([moveActive(0, "ArrowDown", 3), moveActive(2, "ArrowDown", 3), moveActive(0, "ArrowUp", 3), moveActive(1, "End", 3), moveActive(2, "Home", 3), moveActive(0, "ArrowDown", 0)])
      .toEqual([1, 0, 2, 2, 0, -1]);
  });
  it("marks the matched part, folding letter variants and digits", () => {
    expect(highlight("پمپ صنعتی", "پمپ")).toEqual([{ text: "پمپ", match: true }, { text: " صنعتی", match: false }]);
    expect(highlight("Shanghai Valve", "valve")).toEqual([{ text: "Shanghai ", match: false }, { text: "Valve", match: true }]);
    expect(highlight("SO-1405-0002", "۱۴۰۵")).toEqual([{ text: "SO-", match: false }, { text: "1405", match: true }, { text: "-0002", match: false }]);
    expect(highlight("abc", "")).toEqual([{ text: "abc", match: false }]);
    expect(fold("كيف ۱۲")).toBe("کیف 12");
  });
});

describe("recent items and the «/» key", () => {
  it("keeps the newest first, without duplicates, at most eight", () => {
    let list: Recent[] = [];
    for (let i = 0; i < 10; i++) list = pushRecent(list, { id: String(i), type: "case", title: `C${i}`, subtitle: null, link: `/cases/${i}` });
    list = pushRecent(list, { id: "5", type: "case", title: "C5", subtitle: null, link: "/cases/5" });
    expect(list.map((r) => r.id)).toEqual(["5", "9", "8", "7", "6", "4", "3", "2"]);
  });
  it("«/» opens the palette only when no field has focus", () => {
    expect(slashOpens(null)).toBe(true);
    expect(slashOpens({ tagName: "BODY" } as unknown as EventTarget)).toBe(true);
    expect(slashOpens({ tagName: "INPUT" } as unknown as EventTarget)).toBe(false);
    expect(slashOpens({ tagName: "DIV", isContentEditable: true } as unknown as EventTarget)).toBe(false);
  });
});
