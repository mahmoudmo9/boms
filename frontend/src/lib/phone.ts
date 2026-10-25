/** Phone input logic (pure, tested): country flags, default country, auto-switch on a typed "+"/"00" prefix. */

export interface PhoneRegion {
  iso2: string;
  name_fa: string;
  name_en: string;
  calling_code: number;
}

export const DEFAULT_PHONE_REGION = "IR";

/** Countries sharing a calling code: the one chosen when a "+code" is typed (unless the current one matches). */
const MAIN_REGION: Record<number, string> = {
  1: "US", 7: "RU", 44: "GB", 47: "NO", 61: "AU", 212: "MA", 262: "RE", 290: "SH", 358: "FI", 39: "IT",
  590: "GP", 599: "CW",
};

/** "IR" -> regional-indicator flag emoji. */
export function flagEmoji(iso2: string): string {
  if (!/^[A-Za-z]{2}$/.test(iso2)) return "";
  return String.fromCodePoint(...iso2.toUpperCase().split("").map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

/** Persian/Arabic-Indic digits -> ASCII. */
export function asciiDigits(value: string): string {
  return value.replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0)).replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660));
}

/** The party's country when phonenumbers knows it, else Iran. */
export function defaultPhoneRegion(partyCountry: string | null | undefined, regions: PhoneRegion[]): string {
  const iso2 = (partyCountry ?? "").toUpperCase();
  return regions.some((r) => r.iso2 === iso2) ? iso2 : DEFAULT_PHONE_REGION;
}

/**
 * Country for a number typed in international form ("+971 50…", "0098 912…"), or null when the number has no
 * "+"/"00" prefix or no known calling code yet. Calling codes are 1-3 digits and prefix-free, so the first match
 * is the only one. The current country wins when it shares the code (e.g. Canada for "+1").
 */
export function detectPhoneRegion(typed: string, regions: PhoneRegion[], current?: string): string | null {
  const text = asciiDigits(typed).trim();
  const match = /^(?:\+|00)\s*([\d\s\-().]*)/.exec(text);
  if (!match) return null;
  const digits = match[1].replace(/\D/g, "");
  for (let len = 1; len <= Math.min(3, digits.length); len++) {
    const code = Number(digits.slice(0, len));
    const candidates = regions.filter((r) => r.calling_code === code);
    if (candidates.length === 0) continue;
    if (current && candidates.some((r) => r.iso2 === current)) return current;
    const main = MAIN_REGION[code];
    return candidates.find((r) => r.iso2 === main)?.iso2 ?? candidates[0].iso2;
  }
  return null;
}

/** Next state of the phone input after typing: the text as typed, and the country (switched on "+"/"00"). */
export function phoneInputChange(state: { value: string; region: string }, typed: string, regions: PhoneRegion[]) {
  return { value: typed, region: detectPhoneRegion(typed, regions, state.region) ?? state.region };
}

export const isPhoneType = (type: string) => type === "phone" || type === "whatsapp";
