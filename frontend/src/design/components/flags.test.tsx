// @vitest-environment jsdom
/** v0.10.1 (0.4.5): flags are local SVGs, never emoji (Windows draws regional-indicator pairs as two letters); a dial
 * code is a signed value isolated left-to-right; the option reads flag, name, dial code; search finds a country by its
 * name in either language, its ISO code and its dial code. */
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Combobox, Flag, optionText } from ".";
import { regionOptions } from "../../components/PhoneInput";
import { renderDs } from "./testing";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
afterEach(cleanup);

const REGIONAL_INDICATOR = /[\u{1F1E6}-\u{1F1FF}]/u;
const REGIONS = [
  { iso2: "IR", name_fa: "ایران", name_en: "Iran", calling_code: 98 },
  { iso2: "AE", name_fa: "امارات متحده عربی", name_en: "United Arab Emirates", calling_code: 971 },
  { iso2: "CN", name_fa: "چین", name_en: "China", calling_code: 86 },
];

describe("flags", () => {
  it("is an SVG from the local set with the country as its accessible name", async () => {
    await renderDs(<span><Flag code="IR" name="Iran" /><Flag code="x1" name="bad" /></span>);
    const img = screen.getByRole("img", { name: "Iran" });
    expect(img.getAttribute("src")).toBe("/flags/ir.svg");
    expect(screen.queryByRole("img", { name: "bad" })).toBeNull();     // not a country code: nothing, never two letters
  });

  it("ships an SVG and its licence for every flag it can show", () => {
    const dir = join(process.cwd(), "public", "flags");
    for (const iso of ["ir", "ae", "cn", "de", "tr", "us", "gb"]) expect(statSync(join(dir, `${iso}.svg`)).size).toBeGreaterThan(0);
    expect(readFileSync(join(dir, "LICENSE-flag-icons.txt"), "utf8")).toContain("MIT");
  });

  it("phone country options read flag, name, dial code, with no regional-indicator letters", async () => {
    document.documentElement.dir = "rtl";
    await renderDs(<Combobox ariaLabel="country" options={regionOptions(REGIONS, "fa")} value="IR" onChange={() => {}} clearable={false} />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    expect(input.value).toBe("ایران (⁦+98⁩)");                       // isolated: never «98+» in a right-to-left field
    fireEvent.click(input);
    const option = screen.getAllByRole("option").find((o) => o.textContent?.includes("ایران"))!;
    const parts = [...option.children].map((n) => n.tagName.toLowerCase());
    expect(parts.slice(0, 2)).toEqual(["img", "span"]);                       // flag first, then the name
    const code = option.querySelector("bdi[dir=ltr]")!;
    expect(code.textContent).toBe("+98");
    expect(REGIONAL_INDICATOR.test(document.body.textContent ?? "")).toBe(false);
    document.documentElement.dir = "ltr";
  });

  it("finds a country by its name in either language, ISO code and dial code", async () => {
    await renderDs(<Combobox ariaLabel="country" options={regionOptions(REGIONS, "fa")} value={null} onChange={() => {}} />);
    const input = screen.getByRole("combobox");
    const first = async (q: string) => { fireEvent.change(input, { target: { value: q } }); return screen.getAllByRole("option")[0].textContent; };
    expect(await first("امارات")).toContain("امارات");
    expect(await first("China")).toContain("چین");
    expect(await first("ir")).toContain("ایران");
    expect(await first("+971")).toContain("امارات");
    expect(await first("86")).toContain("چین");
  });

  it("isolates only signed codes in the input text", () => {
    expect(optionText({ value: "USD", label: "US dollar", code: "USD" })).toBe("US dollar (USD)");
    expect(optionText({ value: "IR", label: "Iran", code: "+98" })).toBe("Iran (⁦+98⁩)");
  });
});

describe("no regional-indicator characters in the UI", () => {
  it("none in any source file or translation (they render as two letters on Windows)", () => {
    const bad: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.(tsx?|json|css|html)$/.test(name) && !name.endsWith(".test.tsx")) {
          const text = readFileSync(path, "utf8");
          if (REGIONAL_INDICATOR.test(text) || /fromCodePoint\([^)]*0x1f1e6/i.test(text)) bad.push(path);
        }
      }
    };
    walk(join(process.cwd(), "src"));
    expect(bad).toEqual([]);
  });
});
