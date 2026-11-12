/** v0.10.0 section 5: the company's bank details as fields; the printed text is composed from them exactly as the
 * server does (system/settings.py `bank_text`), so the letterhead preview matches the PDF. */
export type PerLang = { fa?: string; en?: string };
export type Bank = { bank_name: PerLang; account_holder: PerLang; iban: string; bic: string; other: PerLang };

const LABELS = {
  fa: { account_holder: "صاحب حساب", iban: "شبا (IBAN)", bic: "BIC / SWIFT" },
  en: { account_holder: "Account holder", iban: "IBAN", bic: "BIC / SWIFT" },
} as const;

export const emptyBank = (): Bank => ({ bank_name: {}, account_holder: {}, iban: "", bic: "", other: {} });

/** The fields from what is stored; before v0.10.0 there were only free-text lines, which become «other lines». */
export function bankFrom(stored: Partial<Bank> | null | undefined, legacyText: PerLang | null | undefined): Bank {
  if (stored) return { ...emptyBank(), ...stored };
  return { ...emptyBank(), other: { fa: legacyText?.fa ?? "", en: legacyText?.en ?? "" } };
}

export function bankIsEmpty(b: Bank): boolean {
  const txt = (p: PerLang) => !(p.fa ?? "").trim() && !(p.en ?? "").trim();
  return txt(b.bank_name) && txt(b.account_holder) && txt(b.other) && !b.iban.trim() && !b.bic.trim();
}

export function bankText(b: Bank, lang: "fa" | "en"): string {
  const pick = (p: PerLang) => (p[lang] ?? "") || (Object.values(p).find((x) => x) ?? "");
  const l = LABELS[lang];
  return [pick(b.bank_name), pick(b.account_holder) && `${l.account_holder}: ${pick(b.account_holder)}`,
    b.iban && `${l.iban}: ${b.iban}`, b.bic && `${l.bic}: ${b.bic}`, pick(b.other)].filter(Boolean).join("\n");
}
