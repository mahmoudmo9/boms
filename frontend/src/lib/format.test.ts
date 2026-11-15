import { describe, expect, it } from "vitest";

import { compactParts, formatBytes, formatCompact, formatDate, formatNumber, moneyFraction, parseDateInput, toFaDigits, toLatinDigits } from "./format";

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

describe("digits follow the UI language (v0.9.0)", () => {
  it("Persian digits in fa, Latin digits in en whatever the user's old digits setting", async () => {
    const { digitsFor } = await import("./prefs");
    expect(digitsFor("en")).toBe("latin");
    expect(digitsFor("fa")).toBe("fa");
    expect(formatNumber("1234.5", digitsFor("en"))).toBe("1,234.5");
    expect(formatNumber("1234.5", digitsFor("fa"))).toBe("۱٬۲۳۴٫۵");
  });
});

describe("v0.10.1 numbers (sections 1.3, 1.5, 3.2, 3.3)", () => {
  it("formats with Intl fa-IR: Persian digits, U+066C grouping and U+066B decimals", () => {
    expect(formatNumber("1234.5", "fa")).toBe("۱٬۲۳۴٫۵");
    expect(formatNumber("12345678901234567.25", "fa")).toBe("۱۲٬۳۴۵٬۶۷۸٬۹۰۱٬۲۳۴٬۵۶۷٫۲۵");   // exact, no float rounding
    expect(formatNumber("1234.5", "latin")).toBe("1,234.5");
  });
  it("shows the rial without decimals and keeps other currencies' cents", () => {
    expect(formatNumber("215174999.4000", "latin", moneyFraction("IRR"))).toBe("215,174,999");
    expect(formatNumber("-215174999.4", "fa", moneyFraction("IRR"))).not.toContain("٫");
    expect(formatNumber("1373.50", "latin", moneyFraction("USD"))).toBe("1,373.5");
  });
  it("compacts large figures for tiles and keeps small ones whole", () => {
    expect(formatCompact("4130299990", "fa").replace(/\u00a0/g, " ")).toBe("۴٫۱ میلیارد");
    expect(formatCompact("521500000", "fa").replace(/\u00a0/g, " ")).toBe("۵۲۱٫۵ میلیون");
    expect(formatCompact("1373", "fa")).toBe("۱٬۳۷۳");
    expect(formatCompact("4130299990", "latin")).toBe("4.1B");
    expect(compactParts("-4130299990", "fa").magnitude).toBe("میلیارد");
    expect(compactParts("-4130299990", "latin")).toEqual({ figure: "-4.1", magnitude: "B" });
  });
});
