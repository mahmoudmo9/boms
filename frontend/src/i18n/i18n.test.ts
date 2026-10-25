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
    expect([...used].filter((k) => !enKeys.includes(k))).toEqual([]);
  });

  it("every workspace and backend error code used by the UI is translated", () => {
    for (const key of ["commandCenter", "market", "parties", "outreach", "sourcing", "cases", "tenders", "execution",
      "finance", "documents", "reports", "settings"]) {
      expect(enKeys).toContain(`nav.${key}`);
    }
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
