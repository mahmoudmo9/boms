import { describe, expect, it } from "vitest";

import { bankFrom, bankIsEmpty, bankText, emptyBank } from "./bank";

describe("bank details", () => {
  const b = { bank_name: { fa: "بانک ملت", en: "Bank Mellat" }, account_holder: { en: "Sample Trading" }, iban: "GB82 WEST 1234 5698 7654 32", bic: "BKMTIRTH",
    other: { en: "Branch 1234" } };
  it("prints the same lines as the server", () => {
    expect(bankText(b, "en").split("\n")).toEqual(["Bank Mellat", "Account holder: Sample Trading", "IBAN: GB82 WEST 1234 5698 7654 32", "BIC / SWIFT: BKMTIRTH", "Branch 1234"]);
    expect(bankText(b, "fa").split("\n")).toEqual(["بانک ملت", "صاحب حساب: Sample Trading", "شبا (IBAN): GB82 WEST 1234 5698 7654 32", "BIC / SWIFT: BKMTIRTH", "Branch 1234"]);
  });
  it("keeps the old free text as other lines", () => {
    const old = bankFrom(null, { fa: "متن قبلی", en: "Old text" });
    expect(bankText(old, "fa")).toBe("متن قبلی");
    expect(bankIsEmpty(emptyBank())).toBe(true);
    expect(bankIsEmpty(old)).toBe(false);
  });
});
