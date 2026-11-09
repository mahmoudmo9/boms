/** v0.9.0 shared components: keyboard behaviour of LookupField, accepting a SuggestedValue with Tab, and the validation
 * states of ValidatedInput with valid and invalid official examples. */
import { describe, expect, it } from "vitest";

import { acceptSuggestion, containerCheckDigit, latinDigits, lookupKey, lookupLabel, numberWordsEn, validateBic, validateContainer, validateEmail,
  validateIban, validateNationalIdIr, validateUscc } from "./smart";

describe("LookupField keyboard", () => {
  it("opens with ArrowDown, moves, wraps, chooses with Enter or Tab, closes with Escape", () => {
    let s = lookupKey({ open: false, active: -1 }, "ArrowDown", 3);
    expect(s.state).toEqual({ open: true, active: 0 });
    s = lookupKey(s.state, "ArrowDown", 3);
    s = lookupKey(s.state, "ArrowDown", 3);
    s = lookupKey(s.state, "ArrowDown", 3);
    expect(s.state.active).toBe(0);                       // wraps
    s = lookupKey(s.state, "ArrowUp", 3);
    expect(s.state.active).toBe(2);
    expect(lookupKey(s.state, "Enter", 3)).toEqual({ state: { open: false, active: -1 }, choose: 2 });
    expect(lookupKey({ open: true, active: 1 }, "Tab", 3).choose).toBe(1);
    expect(lookupKey({ open: true, active: 1 }, "Escape", 3)).toEqual({ state: { open: false, active: -1 }, choose: null });
    expect(lookupKey({ open: true, active: -1 }, "Enter", 3).choose).toBeNull();
    expect(lookupKey({ open: true, active: 0 }, "End", 4).state.active).toBe(3);
  });
  it("labels a choice with its code", () => {
    const item = { kind: "location", id: "x", code: "CNSHA", name_fa: "شانگهای", name_en: "Shanghai" };
    expect(lookupLabel(item, "fa")).toBe("شانگهای (CNSHA)");
    expect(lookupLabel(item, "en")).toBe("Shanghai (CNSHA)");
  });
});

describe("SuggestedValue", () => {
  const s = { value: "USD", source: "PO-1405-0007" };
  it("is accepted with Tab or a click only while the field is empty", () => {
    expect(acceptSuggestion("", s, "Tab")).toBe("USD");
    expect(acceptSuggestion(null, s, "click")).toBe("USD");
    expect(acceptSuggestion("EUR", s, "Tab")).toBeNull();
    expect(acceptSuggestion("", s, "Enter")).toBeNull();
    expect(acceptSuggestion("", null, "Tab")).toBeNull();
  });
});

describe("ValidatedInput states", () => {
  it("IBAN (ISO 13616)", () => {
    expect(validateIban("GB82 WEST 1234 5698 7654 32")).toEqual({ state: "valid", normalized: "GB82 WEST 1234 5698 7654 32" });
    expect(validateIban("GB82 WEST 1234 5698 7654 33").state).toBe("invalid");
    expect(validateIban("IR06 2960 0000 0010 0324 2000 01").state).toBe("valid");
    expect(validateIban("IR06 2960").state).toBe("partial");
    expect(validateIban("").state).toBe("empty");
  });
  it("BIC (ISO 9362)", () => {
    expect(validateBic("DEUTDEFF500").state).toBe("valid");
    expect(validateBic("DEUT1EFF").state).toBe("invalid");
  });
  it("Iranian national ID (10 and 11 digits), Persian digits accepted", () => {
    expect(validateNationalIdIr("0499370899").state).toBe("valid");
    expect(validateNationalIdIr("۰۴۹۹۳۷۰۸۹۹").state).toBe("valid");
    expect(validateNationalIdIr("0499370898").state).toBe("invalid");
    expect(validateNationalIdIr("10380284790").state).toBe("valid");
    expect(validateNationalIdIr("10380284791").state).toBe("invalid");
    expect(validateNationalIdIr("1111111111").state).toBe("invalid");
    expect(validateNationalIdIr("04993").state).toBe("partial");
  });
  it("USCC (GB 32100-2015)", () => {
    expect(validateUscc("91350100M000100Y43").state).toBe("valid");
    expect(validateUscc("91350100M000100Y44").state).toBe("invalid");
  });
  it("e-mail and container number (ISO 6346)", () => {
    expect(validateEmail("sales@valve.cn").state).toBe("valid");
    expect(validateEmail("sales@valve").state).toBe("partial");
    expect(containerCheckDigit("CSQU305438")).toBe(3);
    expect(validateContainer("CSQU3054383").state).toBe("valid");
    expect(validateContainer("CSQU3054384").state).toBe("invalid");
    expect(validateContainer("CSQU30").state).toBe("partial");
  });
  it("digits", () => {
    expect(latinDigits("۱۲۳٤٥")).toBe("12345");
  });
});

describe("AmountInWords (en) matches the backend", () => {
  it("writes numbers", () => {
    expect(numberWordsEn(1250)).toBe("one thousand two hundred fifty");
    expect(numberWordsEn(1_002_003)).toBe("one million two thousand three");
    expect(numberWordsEn(0)).toBe("zero");
  });
});
