// @vitest-environment jsdom
/** v0.10.0 the deal cash flow card: the chart with its text alternative from open milestones, overdue and undated named
 * beside it, nothing before an order exists. */
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderDs } from "../../../design/components/testing";
import type { CaseExecution, MilestoneRow } from "../../../lib/types";
import { DealCashCard } from "./DealCashCard";

vi.mock("../../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
afterEach(cleanup);

const ms = (o: Partial<MilestoneRow>): MilestoneRow => ({
  id: Math.random().toString(36), case_id: "c", direction: "in", sales_order_id: "so", purchase_order_id: null, party_id: "p", kind: "advance",
  label: null, position: 1, percent: null, amount: null, amount_currency: null, due_on: "2099-01-10", due_event: null, status: "expected",
  actual_amount: null, actual_amount_currency: null, actual_on: null, method: null, reference: null, receipt_document_id: null, note: null,
  expected_amount: "1000", expected_currency: "USD", party: { id: "p" } as MilestoneRow["party"], records: [], ...o });
const exec = (inn: MilestoneRow[], out: MilestoneRow[]) => ({ sales_orders: [{ milestones: inn }], milestones_out: out }) as unknown as CaseExecution;

describe("DealCashCard", () => {
  it("draws the open milestones with a text alternative and names overdue and undated ones", async () => {
    await renderDs(<DealCashCard execution={exec([ms({}), ms({ due_on: "2000-01-01", expected_amount: "50" }), ms({ due_on: null })],
      [ms({ direction: "out", due_on: "2099-02-03", expected_amount: "400" })])} />);
    expect(screen.getByTestId("deal-cash")).toBeTruthy();
    expect(screen.getByRole("img", { name: /USD/ })).toBeTruthy();
    expect(screen.getByText(/50/)).toBeTruthy();                       // overdue in
    expect(screen.getByText(/1 payments without a due date/)).toBeTruthy();
  });
  it("shows nothing before an order exists", async () => {
    await renderDs(<DealCashCard execution={exec([], [])} />);
    expect(screen.queryByTestId("deal-cash")).toBeNull();
  });
});
