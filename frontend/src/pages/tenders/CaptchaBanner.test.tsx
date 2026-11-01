import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import i18n from "../../i18n";
import { CaptchaBanner } from "./ConnectionBar";

describe("captcha banner", () => {
  it("is shown only while the agent waits for a captcha, in both languages", async () => {
    await i18n.changeLanguage("en");
    expect(renderToStaticMarkup(<CaptchaBanner waiting={false} message="x" />)).toBe("");
    const en = renderToStaticMarkup(<CaptchaBanner waiting message="Page 2 asked for a captcha" />);
    expect(en).toContain('role="alert"');
    expect(en).toContain("Setad is asking for a captcha.");
    expect(en).toContain("Page 2 asked for a captcha");
    await i18n.changeLanguage("fa");
    const fa = renderToStaticMarkup(<CaptchaBanner waiting />);
    expect(fa).toContain("ستاد کپچا خواسته است.");
    expect(fa).toContain("پنجرهٔ ستاد");
  });
});
