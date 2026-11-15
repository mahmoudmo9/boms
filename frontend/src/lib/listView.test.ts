import { describe, expect, it } from "vitest";

import { keepView, readView, writeView } from "./listView";

const d = { size: 50, sort: "deadline", dir: "asc" as const };

describe("list view in the URL (v0.10.1 section 1.10)", () => {
  it("keeps page 2 through any params change that is not a filter or sort change", () => {
    let p = writeView(new URLSearchParams("source=setad_tender"), { page: 2 }, d);
    expect(readView(p, d).page).toBe(2);
    p.set("listing", "abc");                                  // opening a row in the panel (or a live update) keeps it
    expect(readView(p, d).page).toBe(2);
    p = writeView(p, { size: 50 }, d);                          // the same size: no reset
    expect(readView(p, d).page).toBe(2);
  });
  it("goes back to page 1 when the sort, the page size or a filter changes", () => {
    const p2 = writeView(new URLSearchParams(), { page: 3 }, d);
    expect(readView(writeView(p2, { sort: "price" }, d), d)).toMatchObject({ page: 1, sort: "price" });
    expect(readView(writeView(p2, { size: 100 }, d), d).page).toBe(1);
    const filtered = keepView(writeView(p2, { sort: "price", dir: "desc" }, d), new URLSearchParams("q=pump"));
    expect(readView(filtered, d)).toMatchObject({ page: 1, sort: "price", dir: "desc" });
    expect(filtered.get("q")).toBe("pump");
  });
  it("reads back exactly what a reload or back/forward restores", () => {
    const p = writeView(new URLSearchParams(), { page: 4, sort: "price", dir: "desc", size: 100 }, d);
    expect(readView(new URLSearchParams(p.toString()), d)).toEqual({ page: 4, sort: "price", dir: "desc", size: 100 });
    expect(p.toString()).not.toContain("deadline");             // defaults stay out of the URL
  });
});
