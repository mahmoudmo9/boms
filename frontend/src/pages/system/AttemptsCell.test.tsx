import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import i18n from "../../i18n";
import { toFaDigits } from "../../lib/format";
import { AttemptsCell } from "./SystemPage";

describe("jobs table attempts column", () => {
  it("English: '1 of 2' with each number isolated left-to-right", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<AttemptsCell attempts="1" max="2" />);
    expect(html).toContain('<bdi dir="ltr">1</bdi> of <bdi dir="ltr">2</bdi>');
    expect(i18n.t("system.attempts")).toBe("Attempts (of max)");
  });

  it("Persian: '۱ از ۲', never a bare '۱ / ۲' that RTL can flip", async () => {
    await i18n.changeLanguage("fa");
    const html = renderToStaticMarkup(<AttemptsCell attempts={toFaDigits("1")} max={toFaDigits("2")} />);
    expect(html).toContain('<bdi dir="ltr">۱</bdi> از <bdi dir="ltr">۲</bdi>');
    expect(html).not.toContain(" / ");
    expect(i18n.t("system.attempts")).toContain("حداکثر");
  });
});
