import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import i18n from "../../i18n";
import { GateChecklist } from "./Costing";

const failures = [
  { code: "sheet_not_final", status: "draft" },
  { code: "fx_missing", from_currency: "EUR", to_currency: "IRR" },
  { code: "validity_too_long", max_valid_until: "2026-10-30" },
];

describe("gate checklist rendering", () => {
  it("lists every condition with a pass / fail mark and the failure details", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<GateChecklist failures={failures} day={(d) => `day:${d}`} />);
    expect(html.match(/<li /g)).toHaveLength(9);
    expect(html.match(/data-ok="false"/g)).toHaveLength(3);
    expect(html).toContain("Sheet is final");
    expect(html).toContain("EUR → IRR");
    expect(html).toContain("day:2026-10-30");
    expect(html).not.toContain("Override");
  });

  it("offers an override only for overridable failures, and shows an existing override", async () => {
    await i18n.changeLanguage("fa");
    const html = renderToStaticMarkup(
      <GateChecklist failures={[{ code: "fx_stale", as_of: "2026-10-01" }]} overrides={{ fx_stale: null, unconfirmed_parameter: "تأیید تلفنی" }}
        day={(d) => d} onOverride={() => undefined} />,
    );
    expect(html).toContain("نرخ‌های ارز تازه‌اند");
    expect(html.match(/نادیده گرفتن/g)).toHaveLength(1);
    expect(html).toContain("تأیید تلفنی");
  });
});
