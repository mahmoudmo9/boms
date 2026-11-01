import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import i18n from "../../i18n";
import { BlockerList, EnvelopeProgressBadge, TenderStepper } from "./Tender";

describe("tender stepper rendering", () => {
  it("renders every stage with its state and the hint ring", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<TenderStepper stage="pricing" hint="envelopes" />);
    expect(html.match(/<li /g)).toHaveLength(9);
    expect(html.match(/data-state="done"/g)).toHaveLength(2);
    expect(html.match(/aria-current="step"/g)).toHaveLength(1);
    expect(html.match(/data-hinted="true"/g)).toHaveLength(1);
    expect(html).toContain("Pricing");
  });
});

describe("blockers rendering", () => {
  it("lists all blockers together with their details", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<BlockerList blockers={[
      { code: "bid_bond_not_issued" }, { code: "envelopes_incomplete", envelopes: { A: 2 } }, { code: "proposal_not_approved" }]} />);
    expect(html.match(/data-code=/g)).toHaveLength(3);
    expect(html).toContain("The bid bond is not issued.");
    expect(html).toContain("Envelope items not ready: A: 2");
  });
  it("shows ready when nothing blocks, in Persian too", async () => {
    await i18n.changeLanguage("fa");
    const html = renderToStaticMarkup(<BlockerList blockers={[]} />);
    expect(html).not.toContain("data-code");
    expect(html).toContain(i18n.t("tenders.submit.ready"));
  });
});

describe("envelope progress rendering", () => {
  it("shows done/total with the formatter and marks completion", async () => {
    await i18n.changeLanguage("en");
    const num = (n: number) => `#${n}`;
    expect(renderToStaticMarkup(<EnvelopeProgressBadge p={[2, 5]} num={num} />)).toContain("#2/#5");
    const full = renderToStaticMarkup(<EnvelopeProgressBadge p={[5, 5]} num={num} long />);
    expect(full).toContain('data-complete="true"');
    expect(full).toContain("#5 of #5 ready");
  });
});
