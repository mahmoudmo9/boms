/** v0.10.1 section 4.6: the party page's story blocks render from the scorecard, and say so when there is no data. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import type { PartyDetail } from "../../lib/types";

vi.mock("../../lib/prefs", () => ({
  useFormat: () => ({ lang: i18n.language, num: (v: unknown) => String(Number(v)), money: (v: unknown, c: string) => `${c} ${Number(v)}`,
    compactMoney: (v: unknown, c: string) => ({ text: `${c} ${Number(v)}` }),
    date: (v: string) => `date:${v.slice(0, 10)}`, bytes: (v: number) => String(v) }),
}));

const { initials, PartyDeals, PartyKpis, PartySince, PartyTimeline } = await import("./PartyStory");
import type { Scorecard } from "./PartyStory";

const full: Scorecard = {
  on_time: { value: 67, n: 3, enough: true, on_time: 2, avg_late_days: 4 },
  inspection: { value: 67, n: 3, enough: true, failed: 1 },
  response_time: { value: 36, n: 2, enough: true },
  price_position: { value: 2, n: 3, enough: true, cheapest: 2, compared: 3 },
  min_sample: 2,
  story: {
    since: "2026-02-01T08:00:00Z", counts: { rfqs: 4, orders: 2, claims: 1 },
    timeline: [
      { kind: "payment_out", at: "2026-11-01T00:00:00Z", ref: "PAY-1", amount: "3750", currency: "USD", case_id: "c1" },
      { kind: "rfq_sent", at: "2026-02-01T08:00:00Z", ref: "RFQ-1405-0001", amount: null, currency: null, case_id: "c1" },
    ],
    deals: [
      { case_id: "c1", title: "Fire pumps", status: "closed", margin: { actual: "14.2", planned: "16", expected: null, currency: "IRR" } },
      { case_id: "c2", title: "Valves", status: "open", margin: { actual: null, planned: "20", expected: null, currency: "IRR" } },
    ],
  },
};
const empty: Scorecard = {
  on_time: { value: null, n: 0, enough: false }, inspection: { value: null, n: 0, enough: false },
  response_time: { value: null, n: 1, enough: false }, price_position: { value: null, n: 0, enough: false }, min_sample: 2,
  story: { since: null, counts: { rfqs: 0, orders: 0, claims: 0 }, timeline: [], deals: [] },
};
const party = { id: "p1", roles: [{ role: "supplier", stage: "qualified", stage_changed_at: "" }], contacts: [], documents: [] } as unknown as PartyDetail;

function render(sc: Scorecard, node: React.ReactNode) {
  const client = new QueryClient();
  client.setQueryData(["party-scorecard", "p1"], sc);
  return renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}

describe("party story", () => {
  it("shows since, counts, tiles, timeline and deals from the scorecard", async () => {
    await i18n.changeLanguage("en");
    expect(render(full, <PartySince partyId="p1" />)).toContain("Working together since date:2026-02-01 · 4 RFQs · 2 orders · 1 claims");
    const kpis = render(full, <PartyKpis party={party} ratings={{ average: 4.3, count: 5 }} />);
    expect(kpis).toContain("2 of 3");
    expect(kpis).toContain("4 days late on average");
    expect(kpis).toContain("1 failed");
    expect(kpis).toMatch(/36<\/span>.*hours/);
    expect(kpis).toContain('data-testid="party-rating"');
    const line = render(full, <PartyTimeline partyId="p1" />);
    expect(line.indexOf("Paid PAY-1 · USD 3750")).toBeLessThan(line.indexOf("RFQ RFQ-1405-0001 sent"));
    expect(line).toContain('href="/cases/c1"');
    const deals = render(full, <PartyDeals partyId="p1" />);
    expect(deals).toContain("Profit 14.2%");   // the test formatter keeps decimals
    expect(deals).toContain("In progress · planned 20%");
  });

  it("says when there is not enough data and shows empty states", async () => {
    await i18n.changeLanguage("en");
    expect(render(empty, <PartySince partyId="p1" />)).toBe("");
    const kpis = render(empty, <PartyKpis party={party} ratings={{ average: null, count: 0 }} />);
    expect(kpis).toContain("Not enough data (1 of at least 2)");
    expect(kpis).not.toContain('data-testid="party-rating"');
    expect(render(empty, <PartyTimeline partyId="p1" />)).toContain("Nothing has happened with this party yet.");
    expect(render(empty, <PartyDeals partyId="p1" />)).toContain("No deals with this party yet.");
    const buyer = { ...party, roles: [{ role: "buyer", stage: "lead", stage_changed_at: "" }] } as unknown as PartyDetail;
    const none = { ...empty, response_time: { value: null, n: 0, enough: false } };   // a buyer with no supplier data: no tiles
    expect(render(none, <PartyKpis party={buyer} ratings={{ average: null, count: 0 }} />)).toBe("");
  });

  it("makes initials from the name", () => {
    expect(initials("Shanghai Valve Co.")).toBe("SV");
    expect(initials("شیرآلات نینگبو")).toBe("شن");
    expect(initials("")).toBe("?");
  });
});
