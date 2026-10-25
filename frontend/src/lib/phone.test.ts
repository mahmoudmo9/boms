import { describe, expect, it } from "vitest";

import { defaultPhoneRegion, detectPhoneRegion, flagEmoji, phoneInputChange, type PhoneRegion } from "./phone";

const REGIONS: PhoneRegion[] = [
  { iso2: "AE", name_fa: "امارات", name_en: "United Arab Emirates", calling_code: 971 },
  { iso2: "CA", name_fa: "کانادا", name_en: "Canada", calling_code: 1 },
  { iso2: "CN", name_fa: "چین", name_en: "China", calling_code: 86 },
  { iso2: "DE", name_fa: "آلمان", name_en: "Germany", calling_code: 49 },
  { iso2: "IR", name_fa: "ایران", name_en: "Iran", calling_code: 98 },
  { iso2: "TR", name_fa: "ترکیه", name_en: "Türkiye", calling_code: 90 },
  { iso2: "US", name_fa: "آمریکا", name_en: "United States", calling_code: 1 },
];

describe("phone input", () => {
  it("defaults to the party's country, else Iran", () => {
    expect(defaultPhoneRegion("AE", REGIONS)).toBe("AE");
    expect(defaultPhoneRegion("de", REGIONS)).toBe("DE");
    expect(defaultPhoneRegion(null, REGIONS)).toBe("IR");
    expect(defaultPhoneRegion("XX", REGIONS)).toBe("IR");
  });

  it("switches the country on a leading + or 00", () => {
    const start = { value: "", region: "IR" };
    expect(phoneInputChange(start, "+971 50 123 4567", REGIONS)).toEqual({ value: "+971 50 123 4567", region: "AE" });
    expect(phoneInputChange(start, "0049 30 1234567", REGIONS).region).toBe("DE");
    expect(phoneInputChange({ value: "", region: "AE" }, "+98 912 345 6789", REGIONS).region).toBe("IR");
    expect(phoneInputChange(start, "۰۰۹۰ ۵۳۲", REGIONS).region).toBe("TR");
  });

  it("keeps the country for local numbers and incomplete codes", () => {
    const uae = { value: "", region: "AE" };
    expect(phoneInputChange(uae, "050 123 4567", REGIONS).region).toBe("AE");
    expect(phoneInputChange(uae, "+", REGIONS).region).toBe("AE");
    expect(phoneInputChange(uae, "+9", REGIONS).region).toBe("AE");
    expect(phoneInputChange(uae, "0912", REGIONS).region).toBe("AE");
  });

  it("prefers the current or main country for shared codes", () => {
    expect(detectPhoneRegion("+1 416", REGIONS, "CA")).toBe("CA");
    expect(detectPhoneRegion("+1 212", REGIONS, "IR")).toBe("US");
  });

  it("builds flag emoji", () => {
    expect(flagEmoji("IR")).toBe("🇮🇷");
    expect(flagEmoji("ae")).toBe("🇦🇪");
    expect(flagEmoji("")).toBe("");
  });
});
