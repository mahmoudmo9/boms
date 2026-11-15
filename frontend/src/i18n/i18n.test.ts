import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import en from "./en.json";
import fa from "./fa.json";

function flatten(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? flatten(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(name) && !name.endsWith(".test.ts") ? [path] : [];
  });
}

describe("translations", () => {
  const enKeys = flatten(en).sort();
  const faKeys = flatten(fa).sort();

  it("fa.json and en.json have identical keys", () => {
    expect(faKeys.filter((k) => !enKeys.includes(k))).toEqual([]);
    expect(enKeys.filter((k) => !faKeys.includes(k))).toEqual([]);
  });

  it("no empty translations", () => {
    const empty = (obj: Record<string, unknown>) => flatten(obj).filter((k) => {
      const value = k.split(".").reduce<unknown>((o, p) => (o as Record<string, unknown>)[p], obj);
      return typeof value !== "string" || value.trim() === "";
    });
    expect(empty(en)).toEqual([]);
    expect(empty(fa)).toEqual([]);
  });

  it("every literal t('key') used in the code exists", () => {
    const used = new Set<string>();
    for (const file of sourceFiles(join(__dirname, ".."))) {
      for (const match of readFileSync(file, "utf-8").matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) used.add(match[1]);
    }
    expect(used.size).toBeGreaterThan(50);
    // a plural key exists as key_one / key_other (v0.10.1: Intl.PluralRules through i18next)
    expect([...used].filter((k) => !enKeys.includes(k) && !enKeys.includes(`${k}_other`))).toEqual([]);
  });

  it("every workspace and backend error code used by the UI is translated", () => {
    for (const key of ["commandCenter", "market", "parties", "outreach", "sourcing", "cases", "tenders", "execution",
      "finance", "documents", "reports", "settings"]) {
      expect(enKeys).toContain(`nav.${key}`);
    }
  });

  it("Persian uses the reference-flow terms for exposure, margin and markup (v0.5.0)", () => {
    const values = flatten(fa).map((k) => k.split(".").reduce<unknown>((o, p) => (o as Record<string, unknown>)[p], fa) as string);
    expect(values.filter((v) => /درگیری مالی|سربار سود|ریسک مالی/.test(v))).toEqual([]);
    const pricing = (fa as unknown as { costing: { pricing: Record<string, string>; money: Record<string, string> } }).costing;
    expect([pricing.pricing.margin, pricing.pricing.markup, pricing.money.exposure]).toEqual(["حاشیهٔ سود", "مارک‌آپ", "نقدینگی درگیر"]);
  });

  it("every funnel stage of migration 0004 has a label in both languages", () => {
    const stages: Record<string, string[]> = {
      buyer: ["new_lead", "contacted", "in_conversation", "inquiry_received", "quoted", "won", "lost", "dormant"],
      supplier: ["identified", "contacted", "responded", "qualified", "in_use", "blacklisted", "dormant"],
      forwarder: ["active", "dormant"],
      customs_broker: ["active", "dormant"],
      agent: ["active", "dormant"],
      other: ["active", "dormant"],
    };
    for (const [role, codes] of Object.entries(stages)) {
      expect(enKeys).toContain(`parties.roles.${role}`);
      for (const code of codes) expect(enKeys).toContain(`funnel.stages.${role}.${code}`);
    }
  });
});

describe("numbers inside translations (v0.10.1 section 3.3)", () => {
  it("formats a number passed to t() with Persian digits in fa and Latin in en", async () => {
    const { default: i18n } = await import("./index");
    await i18n.changeLanguage("fa");
    expect(i18n.t("ai.settings.cap.warning", { level: 80 })).toBe("هشدار ۸۰٪");
    expect(i18n.t("ai.settings.cap.subscription", { count: 1234 })).toContain("۱٬۲۳۴");
    await i18n.changeLanguage("en");
    expect(i18n.t("ai.settings.cap.subscription", { count: 1234 })).toContain("1,234");
  });
});

describe("English plurals (v0.10.1 section 3.5)", () => {
  it("never writes «(s)»: counts use plural keys (Intl.PluralRules through i18next)", async () => {
    const text = readFileSync(join(__dirname, "en.json"), "utf-8");
    expect(text.match(/\(s\)|\(es\)/g) ?? []).toEqual([]);
    const { default: i18n } = await import("./index");
    await i18n.changeLanguage("en");
    expect(i18n.t("execution.header.warnings", { count: 1, n: "1" })).toBe("1 delay warning");
    expect(i18n.t("execution.header.warnings", { count: 3, n: "3" })).toBe("3 delay warnings");
  });
});
