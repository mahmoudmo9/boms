import { describe, expect, it } from "vitest";

import {
  flattenComparison,
  isActiveRfq,
  parsePasted,
  personName,
  placeholdersIn,
  renderTemplate,
  rfqDefaultOpen,
  setColumnField,
  sortRfqs,
  suggestMapping,
  toNumberText,
  unknownPlaceholders,
  validityTone,
} from "./sourcing";
import type { ComparisonItem, ComparisonRow } from "./types";

describe("template placeholders", () => {
  const values = {
    supplier_name: "ACME", contact_name: "Mr. Wang", case_title: "PE", items_table: "1. PE100", respond_by: "2026-11-20",
    signature: "Kimia",
  };

  it("renders every placeholder and literal braces", () => {
    expect(renderTemplate("Dear {contact_name} ({supplier_name})\n{items_table}\nBy {respond_by} — {case_title}\n{signature} {{x}}", values))
      .toBe("Dear Mr. Wang (ACME)\n1. PE100\nBy 2026-11-20 — PE\nKimia {x}");
  });

  it("renders Persian templates unchanged around placeholders", () => {
    expect(renderTemplate("{contact_name} گرامی، لطفاً تا {respond_by}", values)).toBe("Mr. Wang گرامی، لطفاً تا 2026-11-20");
  });

  it("finds unknown and unbalanced placeholders", () => {
    expect(unknownPlaceholders("Hi {contact}", "{price} {signature}")).toEqual(["contact", "price"]);
    expect(placeholdersIn("Hi {").unbalanced).toBe(true);
    expect(placeholdersIn("{{ok}} {signature}")).toEqual({ names: ["signature"], unbalanced: false });
  });
});

describe("pasted table parser", () => {
  it("splits tab tables and keeps quotes", () => {
    expect(parsePasted('Item\tQty\tUnit\r\nSteel pipe 2"\t1,200\tm\n\n')).toEqual([["Item", "Qty", "Unit"], ['Steel pipe 2"', "1,200", "m"]]);
  });

  it("splits comma and semicolon CSV with quoted cells", () => {
    expect(parsePasted('name,qty\n"Bolt, M8",100')).toEqual([["name", "qty"], ["Bolt, M8", "100"]]);
    expect(parsePasted("a;b\nc;d")).toEqual([["a", "b"], ["c", "d"]]);
  });

  it("turns a text list into one column without bullets", () => {
    expect(parsePasted("1. پلی‌اتیلن\n- اسید\n• Valve")).toEqual([["پلی‌اتیلن"], ["اسید"], ["Valve"]]);
    expect(parsePasted("Steel pipe, 2 inch\nValve, DN50", "lines")).toEqual([["Steel pipe, 2 inch"], ["Valve, DN50"]]);
  });

  it("reads Persian digits and thousands separators", () => {
    expect(toNumberText("۱٬۲۰۰٫۵")).toBe("1200.5");
    expect(toNumberText("1,200")).toBe("1200");
    expect(toNumberText("abc")).toBeNull();
  });
});

describe("import column mapping", () => {
  it("maps header words in English and Persian", () => {
    expect(suggestMapping([["Item", "Qty", "Unit", "Price"], ["x", "1", "kg", "2"]])).toEqual({
      mapping: [{ column: 0, field: "name" }, { column: 1, field: "quantity" }, { column: 2, field: "unit" }, { column: 3, field: "target_price" }],
      hasHeader: true,
    });
    expect(suggestMapping([["كالا", "مقدار"], ["x", "1"]]).mapping).toEqual([{ column: 0, field: "name" }, { column: 1, field: "quantity" }]);
  });

  it("guesses name, quantity and unit without a header", () => {
    expect(suggestMapping([["Valve", "12", "pc"], ["Pump", "۳", "pc"]])).toEqual({
      mapping: [{ column: 0, field: "name" }, { column: 1, field: "quantity" }, { column: 2, field: "unit" }], hasHeader: false,
    });
    expect(suggestMapping([["Valve", "red"]]).mapping).toEqual([{ column: 0, field: "name" }]);
  });

  it("keeps one column per field, many spec columns", () => {
    let m = setColumnField([{ column: 0, field: "name" }, { column: 1, field: "quantity" }], 2, "name");
    expect(m).toEqual([{ column: 1, field: "quantity" }, { column: 2, field: "name" }]);
    m = setColumnField(m, 3, "spec", "Brand");
    m = setColumnField(m, 4, "spec", "Grade");
    expect(m.filter((x) => x.field === "spec")).toHaveLength(2);
    expect(setColumnField(m, 1, "")).not.toContainEqual({ column: 1, field: "quantity" });
  });
});

describe("comparison grouping", () => {
  const row = (id: string, price: string, extra: Partial<ComparisonRow> = {}): ComparisonRow => ({
    offer_item_id: id, offer_id: id, party_id: id, party_name_fa: null, party_name_en: id, unit_price: price, currency: "USD",
    price_per_quantity: "1", unit_code: "kg", unit_text: null, unit_group: "kind:weight", normalized_price: price, incoterm: "FOB",
    incoterm_place: null, moq: null, moq_unit: null, lead_time_days: null, payment_terms: null, valid_until: null, days_left: null,
    expiring: false, compliance_notes: null, spec_deviation: null, packaging: null, notes: null, documents: [], badges: [],
    lowest: false, selected: false, ...extra,
  });

  it("puts a header per currency/unit group and sorts comparable rows by price", () => {
    const item: ComparisonItem = {
      item_id: "i", position: 1, name: "PE", status: "has_offer", quantity: null, unit_code: null, unit_text: null,
      selected_offer_item_id: null,
      groups: [
        { currency: "EUR", unit_groups: [{ unit_group: "kind:weight", comparable: false, rows: [row("e1", "9", { currency: "EUR" }), row("e2", "1", { currency: "EUR" })] }] },
        { currency: "USD", unit_groups: [{ unit_group: "kind:weight", comparable: true, rows: [row("a", "1.2"), row("b", "0.9", { lowest: true })] }] },
      ],
    };
    const lines = flattenComparison(item);
    expect(lines.map((l) => (l.kind === "group" ? `#${l.currency}` : l.offer_id))).toEqual(["#EUR", "e1", "e2", "#USD", "b", "a"]);
    expect(lines[0]).toMatchObject({ kind: "group", comparable: false });
  });

  it("colours validity", () => {
    expect([validityTone(3), validityTone(10), validityTone(30), validityTone(null)]).toEqual(["danger", "warning", "neutral", "neutral"]);
  });
});

describe("RFQ tab (v0.3.2)", () => {
  it("opens draft RFQs and collapses every finished state", () => {
    expect(rfqDefaultOpen("draft")).toBe(true);
    for (const status of ["sent", "answered", "no_response", "expired", "cancelled"] as const) expect(rfqDefaultOpen(status)).toBe(false);
  });
  it("lists active RFQs first, each group newest first", () => {
    const rows = [
      { id: "old-answered", status: "answered", created_at: "2026-10-01T10:00:00Z" },
      { id: "new-cancelled", status: "cancelled", created_at: "2026-10-20T10:00:00Z" },
      { id: "old-sent", status: "sent", created_at: "2026-10-02T10:00:00Z" },
      { id: "new-draft", status: "draft", created_at: "2026-10-21T10:00:00Z" },
      { id: "mid-no-response", status: "no_response", created_at: "2026-10-10T10:00:00Z" },
    ] as const;
    expect(sortRfqs([...rows]).map((r) => r.id)).toEqual(["new-draft", "old-sent", "new-cancelled", "mid-no-response", "old-answered"]);
    expect(isActiveRfq({ status: "sent" })).toBe(true);
    expect(isActiveRfq({ status: "no_response" })).toBe(false);
  });
  it("names a person in the UI language with a fallback", () => {
    expect(personName("عباس", "Abbas", "fa")).toBe("عباس");
    expect(personName("عباس", "Abbas", "en")).toBe("Abbas");
    expect(personName(null, "Abbas", "fa")).toBe("Abbas");
    expect(personName(null, null, "en")).toBe("");
  });
});
