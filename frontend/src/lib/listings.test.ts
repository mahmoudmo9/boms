import { describe, expect, it } from "vitest";

import {
  activeFilterCount, bulkBody, clearFilters, COLUMNS, daysLeft, deadlineTone, DEFAULT_FILTERS, defaultColumns,
  documentsState, EMPTY_SELECTION, filterStorageKey, filtersFromParams, filtersToParams, isSelected, paramsToRemember,
  parseColumns, queryBody, rememberedParams,
  selectAllResults, selectionCount, toggleColumn, toggleRow,
} from "./listings";

describe("filter state", () => {
  it("round-trips through the URL and keeps only what differs from the defaults", () => {
    const f = { ...DEFAULT_FILTERS, source: "setad_tender" as const, q: " کالا ", organizations: ["شهرداری تفت", "دانشگاه"],
      status: "starred" as const, deadline: "within" as const, within_days: 7, downloaded: true, price: "free" as const };
    const params = filtersToParams(f);
    expect(params.get("q")).toBe("کالا");
    expect(params.getAll("organizations")).toEqual(["شهرداری تفت", "دانشگاه"]);
    expect(params.has("my_calls")).toBe(false);
    expect(filtersFromParams(params)).toEqual({ ...f, q: "کالا" });
    expect(filtersToParams(DEFAULT_FILTERS).toString()).toBe("");
  });
  it("opens with the deadline filter «open» (v0.6.0); «any» stays representable", () => {
    expect(DEFAULT_FILTERS.deadline).toBe("open");
    expect(filtersFromParams(new URLSearchParams("")).deadline).toBe("open");
    const any = filtersToParams({ ...DEFAULT_FILTERS, deadline: null });
    expect(any.get("deadline")).toBe("any");
    expect(filtersFromParams(any).deadline).toBeNull();
    expect(activeFilterCount(DEFAULT_FILTERS)).toBe(0);
    expect(activeFilterCount({ ...DEFAULT_FILTERS, deadline: null })).toBe(1);
  });
  it("remembers the filters of each tab", () => {
    const f = { ...DEFAULT_FILTERS, source: "setad_tender" as const, q: "پمپ", price: "free" as const };
    const saved = paramsToRemember(f);
    expect(saved).not.toContain("source");
    const back = filtersFromParams(rememberedParams("setad_tender", saved));
    expect(back).toEqual(f);
    expect(rememberedParams("setad_purchase", null).toString()).toBe("");
    expect(filterStorageKey("setad_tender")).toBe("boms.listings.filters.setad_tender");
  });
  it("ignores invalid values and counts active filters; clear keeps the tab", () => {
    const f = filtersFromParams(new URLSearchParams("source=bogus&status=x&deadline=passed&within_days=999&my_calls=1"));
    expect(f.source).toBe("setad_purchase");
    expect(f.status).toBeNull();
    expect(f.within_days).toBe(3);
    expect(activeFilterCount(f)).toBe(2);
    expect(clearFilters({ ...f, source: "setad_tender" })).toEqual({ ...DEFAULT_FILTERS, source: "setad_tender" });
  });
  it("builds the query body without empty search text", () => {
    expect(queryBody({ ...DEFAULT_FILTERS, q: "  " }, 2, 500, "deadline", "desc")).toMatchObject({ q: null, page: 2, page_size: 500, dir: "desc" });
  });
});

describe("column chooser", () => {
  it("has per-source defaults, keeps table order and never hides the title", () => {
    expect(defaultColumns("setad_purchase")).not.toContain("price");
    expect(defaultColumns("setad_tender")).toContain("price");
    const cols = toggleColumn(toggleColumn(defaultColumns("setad_purchase"), "documents"), "row");
    expect(cols.indexOf("documents")).toBeGreaterThan(cols.indexOf("deadline"));
    expect(cols).not.toContain("row");
    expect(toggleColumn(cols, "title")).toEqual(cols);
    expect(cols.filter((c) => !COLUMNS.includes(c))).toEqual([]);
  });
  it("reads a saved choice defensively", () => {
    expect(parseColumns('["status","title","bogus"]', "setad_tender")).toEqual(["title", "status"]);
    expect(parseColumns("not json", "setad_tender")).toEqual(defaultColumns("setad_tender"));
    expect(parseColumns(null, "setad_purchase")).toEqual(defaultColumns("setad_purchase"));
  });
});

describe("bulk selection over all results", () => {
  it("switches from ticked rows to the whole result and back", () => {
    let sel = toggleRow(toggleRow(EMPTY_SELECTION, "a"), "b");
    expect(selectionCount(sel)).toBe(2);
    expect(bulkBody(sel, "star")).toEqual({ ids: ["a", "b"], action: "star" });
    const filters = { ...DEFAULT_FILTERS, q: " پمپ ", provinces: ["یزد"] };
    sel = selectAllResults(filters, 12345);
    expect(selectionCount(sel)).toBe(12345);
    expect(isSelected(sel, "anything")).toBe(true);
    expect(bulkBody(sel, "dismiss", "مهلت کافی نیست")).toEqual({
      filters: { ...filters, q: "پمپ" }, action: "dismiss", reason: "مهلت کافی نیست" });
    sel = toggleRow(sel, "c");                      // ticking a row leaves "all results" mode
    expect(sel.mode === "ids" && [...sel.ids]).toEqual(["c"]);
  });
});

describe("display helpers", () => {
  const now = new Date("2026-11-01T10:00:00Z");
  it("counts whole days left and colours them", () => {
    expect(daysLeft("2026-11-04T09:00:00Z", now)).toBe(2);
    expect(daysLeft("2026-10-31T09:00:00Z", now)).toBe(-2);
    expect(daysLeft(null, now)).toBeNull();
    expect([deadlineTone(0), deadlineTone(2), deadlineTone(9), deadlineTone(-1)]).toEqual(["danger", "warning", "success", "neutral"]);
  });
  it("documents column: complete / partial / empty", () => {
    expect(documentsState({ downloaded: 3, total: 3 })).toBe("complete");
    expect(documentsState({ downloaded: 1, total: 3 })).toBe("partial");
    expect(documentsState({ downloaded: 0, total: 3 })).toBe("empty");
  });
});
