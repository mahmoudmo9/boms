/** v0.10.0 attribute editor: validation per attribute type, the values sent, carrying values across templates. */
import { describe, expect, it } from "vitest";

import { attributeProblem, attributeProblems, carryAttributes, cleanAttributes, nounBody, nounOf, parseNumber, sameNoun, type ProductTemplate } from "./nounmod";

const pump: ProductTemplate = { id: "t1", key: "pump", noun_fa: "پمپ", noun_en: "PUMP", status: "active", attributes: [
  { key: "type", type: "choice", values: [{ value: "centrifugal", fa: "گریز از مرکز", en: "CENTRIFUGAL" }, { value: "gear", fa: "دنده‌ای", en: "GEAR" }] },
  { key: "standard", type: "text" },
  { key: "flow", type: "number", unit: "MQH", min: 0 },
  { key: "temp", type: "number", unit: "CEL", min: -50, max: 400 },
] };
const valve: ProductTemplate = { id: "t2", key: "valve", noun_fa: "شیر", noun_en: "VALVE", status: "active", attributes: [
  { key: "type", type: "choice", values: [{ value: "gate", fa: "کشویی", en: "GATE" }] },
  { key: "standard", type: "text" },
] };

describe("attribute validation", () => {
  it("reads numbers in Persian digits and with thousands separators", () => {
    expect(parseNumber("۱۲۰٫۵")).toBe("120.5");
    expect(parseNumber("1,200")).toBe("1200");
    expect(parseNumber("12 m")).toBeNull();
    expect(parseNumber("")).toBeNull();
  });
  it("checks numbers, ranges, choices and length; empty is allowed", () => {
    const [type, standard, flow, temp] = pump.attributes;
    expect(attributeProblem(flow, "")).toBeNull();
    expect(attributeProblem(flow, "۱۲۰")).toBeNull();
    expect(attributeProblem(flow, "abc")).toBe("not_a_number");
    expect(attributeProblem(flow, "-1")).toBe("out_of_range");
    expect(attributeProblem(temp, "401")).toBe("out_of_range");
    expect(attributeProblem(temp, "-50")).toBeNull();
    expect(attributeProblem(type, "gear")).toBeNull();
    expect(attributeProblem(type, "piston")).toBe("not_allowed");
    expect(attributeProblem(standard, "x".repeat(201))).toBe("too_long");
    expect(attributeProblems(pump, { type: "piston", flow: "x", standard: "API 610" })).toEqual({ type: "not_allowed", flow: "not_a_number" });
    expect(attributeProblems(null, { anything: "1" })).toEqual({});
  });
});

describe("values sent", () => {
  it("sends only the template's attributes, numbers in Latin digits, no empty values", () => {
    expect(cleanAttributes(pump, { type: "gear", flow: "۱۲۰", standard: "  API 610 ", temp: "", stray: "x" })).toEqual({ type: "gear", flow: "120", standard: "API 610" });
  });
  it("sends the two texts only with an override", () => {
    const base = nounOf({ template_id: "t1", attributes: { flow: "120" }, canonical_fa: "پمپ، ۱۲۰", canonical_en: "PUMP, 120 m3/h" });
    expect(nounBody(pump, base)).toEqual({ template_id: "t1", attributes: { flow: "120" }, canonical_override: false });
    expect(nounBody(pump, { ...base, canonical_override: true, canonical_en: " My pump " })).toEqual({ template_id: "t1", attributes: { flow: "120" },
      canonical_override: true, canonical_fa: "پمپ، ۱۲۰", canonical_en: "My pump" });
    expect(nounBody(null, nounOf(null))).toEqual({ template_id: null, attributes: {}, canonical_override: false });
  });
  it("keeps shared, still valid values when the template changes", () => {
    expect(carryAttributes(valve, { type: "gear", standard: "API 600", flow: "120" })).toEqual({ standard: "API 600" });
    expect(carryAttributes(null, { standard: "API 600" })).toEqual({});
  });
  it("knows when nothing changed", () => {
    const a = nounOf({ template_id: "t1", attributes: { flow: "120" } });
    expect(sameNoun(a, nounOf({ template_id: "t1", attributes: { flow: "120", head: "" } }))).toBe(true);
    expect(sameNoun(a, nounOf({ template_id: "t1", attributes: { flow: "121" } }))).toBe(false);
    expect(sameNoun(a, { ...a, canonical_override: true })).toBe(false);
  });
});
