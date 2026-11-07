import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import i18n from "../../../i18n";
import { agingBucket, profitLines, signed, unexplained, varianceTone, type Checklist, type Profit } from "../../../lib/finance";
import { groupTasks, type TaskRow } from "../../../lib/tasks";

vi.mock("../../../lib/prefs", () => ({
  useFormat: () => ({ lang: i18n.language, calendar: "gregorian", digits: "latin", num: (v: unknown) => String(Number(v)), day: (v: string) => `day:${v}`,
    date: (v: string) => `date:${v}`, bytes: (v: number) => String(v) }),
}));

const { ProfitTable } = await import("./ProfitCard");
const { ChecklistView } = await import("./CloseCard");
const { TaskList } = await import("../../tasks/TaskList");

const pair = (deal: string, base: string) => ({ deal, base });

function profit(deal: string, base: string): Profit {
  return {
    case_id: "c", status: "open", frozen: false, deal_currency: deal, base_currency: base, plan: { sheet_id: "s", version: 1, currency: base },
    rows: [{ kind: "purchase", planned: pair("1000", "500000000"), actual: pair("1010", "505000000"), variance: pair("10", "5000000"),
      variance_percent: "1.00", estimated: false, unrealized: true },
    { kind: "freight_international", planned: pair("40", "20000000"), actual: pair("38", "19000000"), variance: pair("-2", "-1000000"),
      variance_percent: "-5.00", estimated: true, unrealized: false }],
    revenue: { planned: pair("1375", "687500000"), actual: pair("1375", "687500000"), variance: pair("0", "0") },
    cost: { planned: pair("1040", "520000000"), actual: pair("1048", "524000000"), variance: pair("8", "4000000") },
    profit: { planned: pair("335", "167500000"), actual: pair("327", "163500000"), variance: pair("-8", "-4000000") },
    margin_percent: { planned: "24.36", actual: "23.78" }, markup_percent: { planned: "32.21", actual: "31.20" },
    fx_effect: pair("-1", "-31200000"), unrealized: { revenue: "0", cost: "0" },
    vat: { output: pair("0", "0"), input: pair("0", "0"), net: pair("0", "0") },
    cost_of_money: { planned: pair("0", "0"), actual: pair("0", "0"), days: 0, annual_percent: "0" }, expected: null, missing_rates: [],
  };
}

describe("aging helper", () => {
  it("buckets by days past the due date, not yet due counts as 0-30", () => {
    expect(agingBucket("2026-11-20", "2026-11-07")).toBe("0-30");
    expect(agingBucket("2026-10-08", "2026-11-07")).toBe("0-30");     // 30 days
    expect(agingBucket("2026-10-07", "2026-11-07")).toBe("31-60");
    expect(agingBucket("2026-09-08", "2026-11-07")).toBe("31-60");    // 60
    expect(agingBucket("2026-08-09", "2026-11-07")).toBe("61-90");    // 90
    expect(agingBucket("2026-08-08", "2026-11-07")).toBe("90+");
  });
});

describe("profit table", () => {
  it("variance signs and tones: cost above plan is bad, below plan good", () => {
    expect(signed("10", String)).toBe("+10");
    expect(signed("-2", String)).toBe("−2");
    expect(signed("0", String)).toBe("0");
    expect(varianceTone("10", "cost")).toBe("danger");
    expect(varianceTone("-2", "cost")).toBe("success");
    expect(varianceTone("-8", "revenue")).toBe("danger");
    expect(profitLines(profit("USD", "IRR")).map((l) => l.key)).toEqual(["revenue", "purchase", "freight_international", "cost_total", "profit"]);
  });

  it("renders both currencies when the deal is not in rials, and one when it is", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<ProfitTable profit={profit("USD", "IRR")} />);
    expect(html).toContain("Planned (USD)") ;
    expect(html).toContain("Actual (IRR)");
    expect(html).toMatch(/data-testid="profit-row-purchase".*data-tone="danger".*\+10/);
    expect(html).toMatch(/data-testid="profit-row-freight_international".*data-tone="success".*−2/);
    expect(html).toContain("estimated");
    expect(html).toContain("505000000");
    const rial = renderToStaticMarkup(<ProfitTable profit={profit("IRR", "IRR")} />);
    expect(rial.match(/<th[ >]/g)).toHaveLength(5);                                  // no second currency column
    expect(html.match(/<th[ >]/g)).toHaveLength(6);
  });
});

describe("close checklist rendering", () => {
  it("lists every problem with a reason field, and the passing state", async () => {
    await i18n.changeLanguage("fa");
    const check: Checklist = { passes: false, notes: [], to_cancel: { tasks: [], followups: [] },
      problems: [{ code: "invoices_unpaid" }, { code: "claims_open" }, { code: "moadian_pending" }] };
    const html = renderToStaticMarkup(<ChecklistView check={check} reasons={{ claims_open: "x" }} onReason={() => undefined} />);
    expect(html.match(/data-problem=/g)).toHaveLength(3);
    expect(html).toContain("فاکتورهای فروش تسویه‌نشده");
    expect(html).toContain("ادعاهای باز");
    expect(unexplained(check.problems, { claims_open: "x", moadian_pending: "  " })).toEqual(["invoices_unpaid", "moadian_pending"]);
    const ok = renderToStaticMarkup(<ChecklistView check={{ ...check, problems: [], passes: true }} reasons={{}} />);
    expect(ok).toContain("checklist-passes");
  });
});

describe("task list grouping", () => {
  const task = (id: string, due_on: string, status: TaskRow["status"] = "open"): TaskRow => ({ id, title: id, due_on, due_at: null, status,
    done_at: null, done_note: null, priority: "normal", case_id: "c1", case_title: "Case", party_id: null, source: "execution",
    source_kind: "process_step", source_id: null, remind_of_due: "2026-11-20", remind_days_before: 3, notes: null });

  it("overdue / today / this week / later / done", () => {
    const g = groupTasks([task("a", "2026-11-01"), task("b", "2026-11-07"), task("c", "2026-11-14"), task("d", "2026-11-15"),
      task("e", "2026-11-01", "done"), task("f", "2026-12-01", "cancelled")], "2026-11-07");
    expect(Object.fromEntries(Object.entries(g).map(([k, v]) => [k, v.map((x) => x.id)]))).toEqual(
      { overdue: ["a"], today: ["b"], week: ["c"], later: ["d"], done: ["e", "f"] });
  });

  it("renders the kind, the case link and the inline actions", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}><MemoryRouter><TaskList rows={[task("a", "2026-11-01"), task("e", "2026-11-01", "done")]} /></MemoryRouter></QueryClientProvider>);
    expect(html.match(/data-testid="task-row"/g)).toHaveLength(2);
    expect(html).toContain("Checklist step");
    expect(html).toContain("/cases/c1?tab=order");
    expect(html).toContain("Move");
    expect(html).toContain("Reopen");
  });
});
