import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import i18n from "../../../i18n";
import type { ExecutionSummary, ProcessRow } from "../../../lib/types";

// the components format numbers and dates through useFormat (which needs a signed-in user): a plain stand-in
vi.mock("../../../lib/prefs", () => ({
  useFormat: () => ({ lang: i18n.language, calendar: "gregorian", digits: "latin", num: (v: unknown) => String(Number(v)), day: (v: string) => `day:${v}`,
    date: (v: string) => `date:${v}`, bytes: (v: number) => String(v) }),
}));

const { ProcessStepper } = await import("./LogisticsTab");
const { CashCard } = await import("./OrderTab");
const { ItemProgressBar } = await import("./DeliveryTab");
const { ExecutionSection } = await import("../../parties/CommandCenterPage");

const step = (code: string, group: string, status: ProcessRow["steps"][number]["status"], due_on: string | null, position: number) => ({
  id: code, process_id: "p", position, group, code, label_fa: code, label_en: code, reference_label: null, requires_document: false, status,
  reference: null, started_on: null, done_on: null, due_on, remind_days_before: [3, 1], document_id: null, no_document_reason: null,
  shipment_id: null, note: null, updated_at: "", reminders: [] });

describe("process stepper rendering", () => {
  it("one block per group with done counts and a dot per step state", async () => {
    await i18n.changeLanguage("en");
    const process = { id: "p", case_id: "c", deal_type: "import", template_id: null, name: "Import", base_date: null,
      progress: { done: 2, total: 4, next: null },
      steps: [step("a", "supplier_order", "done", null, 1), step("b", "supplier_order", "pending", "2000-01-01", 2),
        step("c", "customs", "not_applicable", null, 3), step("d", "customs", "in_progress", "2999-01-01", 4)] } as ProcessRow;
    const html = renderToStaticMarkup(<ProcessStepper process={process} />);
    expect(html.match(/data-group=/g)).toHaveLength(2);
    expect(html).toContain("Supplier and order 1/2") ;
    expect(html).toContain("Customs 1/2");
    for (const state of ["done", "overdue", "na", "current"]) expect(html).toContain(`data-state="${state}"`);
  });
});

describe("cash position display", () => {
  it("received, paid and the cash tied up per currency next to the plan", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<CashCard cash={{ actual: { USD: { received: "1000", paid: "600", net_tied_up: "-400" } },
      outstanding: { USD: { in: "0", out: "900" } }, plan: { exposure: "5000", currency: "IRR" } }} />);
    expect(html).toContain("Received from the customer") ;
    expect(html).toContain("Cash tied up");
    expect(html).toContain('data-currency="USD"');
    expect(html).toContain("Cost sheet exposure (plan)");
    expect(html).toContain("Still expected: in 0 · out 900 USD");
  });
  it("says so when nothing was paid yet, in Persian", async () => {
    await i18n.changeLanguage("fa");
    const html = renderToStaticMarkup(<CashCard cash={{ actual: {}, outstanding: {}, plan: null }} />);
    expect(html).toContain("هنوز پرداختی ثبت نشده است.");
  });
});

describe("delivery progress rendering", () => {
  it("«30 of 88 delivered» and the complete mark", async () => {
    await i18n.changeLanguage("en");
    expect(renderToStaticMarkup(<ItemProgressBar ordered="88" delivered="30" />)).toContain("30 of 88 delivered");
    expect(renderToStaticMarkup(<ItemProgressBar ordered="2" delivered="2" />)).toContain('data-complete="true"');
  });
});

describe("command-center «اجرا» rendering", () => {
  it("every card with its count and links to the right case tab", async () => {
    await i18n.changeLanguage("en");
    const s: ExecutionSummary = {
      pos_unconfirmed: [{ purchase_order_id: "po1", case_id: "c1", number: "PO-1405-0001", sent_at: "2026-11-01T10:00:00Z", days: 4, case_title: "Pumps" }],
      ready_passed: [], shipments_delayed: [{ kind: "eta_passed", case_id: "c2", shipment_id: "s1", days: 3, case_title: "Valves" }],
      steps_due: [{ step_id: "st", case_id: "c1", label_fa: "ثبت سفارش", label_en: "Registration of order", due_on: "2026-11-06", overdue: false, case_title: "Pumps" }],
      payments_overdue: [], claims_open: [{ claim_id: "cl", case_id: "c2", kind: "shortage", direction: "against_supplier", status: "open", opened_on: "2026-11-01", case_title: "Valves" }],
      deliveries_due: [],
    };
    const html = renderToStaticMarkup(<MemoryRouter><ExecutionSection s={s} /></MemoryRouter>);
    expect(html).toContain('data-testid="cc-execution"');
    expect(html).toContain("POs sent, not confirmed");
    expect(html).toContain('href="/cases/c1?tab=purchase"');
    expect(html).toContain('href="/cases/c2?tab=logistics"');
    expect(html).toContain('href="/cases/c2?tab=delivery"');
    expect(html).toContain("ETA passed without arrival (3 days)");
    expect(html).toContain("Registration of order");
    expect(html.match(/Nothing here/g)?.length).toBe(3);
  });
});
