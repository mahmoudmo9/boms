import { describe, expect, it } from "vitest";

import { calendarMonth, dealCashFlow, openAmount } from "./dealCash";
import type { MilestoneRow } from "./types";

const ms = (o: Partial<MilestoneRow>): MilestoneRow => ({
  id: Math.random().toString(36), case_id: "c", direction: "in", sales_order_id: null, purchase_order_id: null, party_id: "p", kind: "advance",
  label: null, position: 1, percent: null, amount: null, amount_currency: null, due_on: "2026-12-05", due_event: null, status: "expected",
  actual_amount: null, actual_amount_currency: null, actual_on: null, method: null, reference: null, receipt_document_id: null, note: null,
  expected_amount: "100", expected_currency: "USD", party: { id: "p", code: null, name_fa: "", name_en: "" } as MilestoneRow["party"], records: [], ...o });

describe("dealCashFlow", () => {
  const label = (d: string) => ({ key: d.slice(0, 7), label: d.slice(0, 7) });
  it("groups open milestones by month and currency, in and out", () => {
    const r = dealCashFlow([ms({}), ms({ due_on: "2026-12-20", direction: "out", expected_amount: "40" }), ms({ due_on: "2027-01-03" }),
      ms({ expected_currency: "EUR", expected_amount: "10" })], "2026-11-12", label);
    expect(r.currencies.map((c) => c.currency)).toEqual(["USD", "EUR"]);
    const usd = r.currencies[0];
    expect(usd.points).toEqual([{ key: "2026-12", label: "2026-12", cashIn: 100, cashOut: 40 }, { key: "2027-01", label: "2027-01", cashIn: 100, cashOut: 0 }]);
    expect([usd.totalIn, usd.totalOut]).toEqual([200, 40]);
  });
  it("keeps overdue and undated beside the chart and skips settled or cancelled milestones", () => {
    const r = dealCashFlow([ms({ due_on: "2026-10-01" }), ms({ due_on: "2026-10-01", direction: "out", expected_amount: "30" }), ms({ due_on: null }),
      ms({ status: "done" }), ms({ status: "cancelled" })], "2026-11-12", label);
    expect(r.undated).toBe(1);
    expect(r.currencies[0]).toMatchObject({ points: [], overdueIn: 100, overdueOut: 30 });
  });
  it("counts only what is still open of a partly paid milestone", () => {
    expect(openAmount(ms({ status: "partly", actual_amount: "35", actual_amount_currency: "USD" }))).toBe(65);
    expect(openAmount(ms({ status: "partly", actual_amount: "200" }))).toBe(0);
    expect(dealCashFlow([ms({ status: "partly", actual_amount: "100" })], "2026-11-12", label).currencies).toEqual([]);
  });
});

describe("calendarMonth", () => {
  it("groups by the user's calendar", () => {
    const j = calendarMonth("jalali", "fa");
    expect(j("2026-11-21").key).toBe("1405-08");          // 30 Aban 1405
    expect(j("2026-11-22").key).toBe("1405-09");          // 1 Azar 1405
    expect(j("2026-11-22").label).toContain("آذر");
    const g = calendarMonth("gregorian", "en");
    expect(g("2026-11-22")).toEqual({ key: "2026-11", label: "November 2026" });
  });
});
