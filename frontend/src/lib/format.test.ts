import { describe, expect, it } from "vitest";

import { formatBytes, formatDate, formatNumber, parseDateInput, toFaDigits, toLatinDigits } from "./format";

describe("digits", () => {
  it("converts both ways", () => {
    expect(toFaDigits("1405/08/02")).toBe("۱۴۰۵/۰۸/۰۲");
    expect(toLatinDigits("۱۴۰۵/۰۸/۰۲ ٤٥")).toBe("1405/08/02 45");
  });
});

describe("formatDate", () => {
  // 2026-10-24 12:00 local == 1405/08/02 (Jalali)
  const iso = new Date(2026, 9, 24, 12, 5).toISOString();

  it("formats Jalali with Persian digits by default style", () => {
    expect(formatDate(iso, { calendar: "jalali", digits: "fa" })).toBe("۱۴۰۵/۰۸/۰۲");
  });
  it("formats Gregorian with Latin digits and time", () => {
    expect(formatDate(iso, { calendar: "gregorian", digits: "latin", time: true })).toBe("2026/10/24 12:05");
  });
  it("handles empty and invalid values", () => {
    expect(formatDate(null, { calendar: "jalali", digits: "fa" })).toBe("");
    expect(formatDate("nonsense", { calendar: "jalali", digits: "fa" })).toBe("");
  });
});

describe("parseDateInput", () => {
  it("parses Jalali input with Persian digits", () => {
    const d = parseDateInput("۱۴۰۵/۸/۲", "jalali");
    expect(d && [d.getFullYear(), d.getMonth() + 1, d.getDate()]).toEqual([2026, 10, 24]);
  });
  it("parses Gregorian input and rejects invalid dates", () => {
    const d = parseDateInput("2026-10-24", "gregorian");
    expect(d && [d.getFullYear(), d.getMonth() + 1, d.getDate()]).toEqual([2026, 10, 24]);
    expect(parseDateInput("2026/02/30", "gregorian")).toBeNull();
    expect(parseDateInput("hello", "jalali")).toBeNull();
  });
  it("round-trips Jalali formatting", () => {
    const d = parseDateInput("1405/01/01", "jalali")!;
    expect(formatDate(d.toISOString(), { calendar: "jalali", digits: "latin" })).toBe("1405/01/01");
  });
});

describe("numbers", () => {
  it("groups digits without floats", () => {
    expect(formatNumber("1234567.5000", "latin")).toBe("1,234,567.5");
    expect(formatNumber(1234567, "fa")).toBe("۱٬۲۳۴٬۵۶۷");
    expect(formatNumber("-0.0311034768", "latin", 10)).toBe("-0.0311034768");
  });
  it("formats bytes", () => {
    expect(formatBytes(512, "latin")).toBe("512 B");
    expect(formatBytes(1536, "latin")).toBe("1.5 KB");
    expect(formatBytes(100 * 1024 * 1024, "fa")).toBe("۱۰۰ MB");
    expect(formatBytes(64 * 1024, "fa", "fa")).toBe("۶۴ کیلوبایت");
  });
});
