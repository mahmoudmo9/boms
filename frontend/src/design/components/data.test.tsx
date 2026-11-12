// @vitest-environment jsdom
/** v0.10.0 data display and feedback: DataTable (sort, keyboard row navigation, selection, the three states, dense),
 * Pagination, DescriptionList, Timeline, Stepper, KPI tile, progress, charts with their text alternatives, the page
 * header pattern, the states. */
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Bars, Button, CashFlow, DataTable, DatedTimeline, DescriptionList, EmptyState, ErrorNote, ErrorState, InlineAlert, KpiTile, Loading, PageHeader, Pagination,
  ProfitBridge, ProgressBar, ProgressRing, RouteLine, Skeleton, type SortState, Sparkline, Stat, Stepper, Timeline } from ".";
import { renderDs } from "./testing";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
afterEach(cleanup);

type Row = { id: string; title: string; buyer: string };
const ROWS: Row[] = [{ id: "a", title: "Pump", buyer: "Pars Oil" }, { id: "b", title: "Valve", buyer: "Maroon" }, { id: "c", title: "Flange", buyer: "Lavan" }];
const COLUMNS: ColumnDef<Row, unknown>[] = [
  { id: "title", header: "Title", cell: ({ row }) => row.original.title, size: 320 },
  { id: "buyer", header: "Buyer", cell: ({ row }) => row.original.buyer },
];

describe("DataTable", () => {
  function Demo({ onOpen }: { onOpen?: (r: Row) => void }) {
    const [sort, setSort] = useState<SortState>({ id: "title", desc: false });
    const [active, setActive] = useState<string | null>(null);
    const [selected, setSelected] = useState(new Set<string>());
    return <DataTable label="Listings" columns={COLUMNS} data={ROWS} rowKey={(r) => r.id} sort={sort} onSortChange={setSort} sortable={["title"]} maxHeight="max-h-96"
      activeKey={active} onRowActivate={(r) => { setActive(r.id); onOpen?.(r); }} selected={selected} onSelectedChange={setSelected} testId="table" />;
  }
  it("is a labelled table with a sticky header that scrolls in its own box, with sized columns", async () => {
    await renderDs(<Demo />);
    const table = screen.getByRole("table", { name: "Listings" });
    expect(screen.getByTestId("table").className).toContain("max-h-96");
    expect(screen.getByTestId("table").className).toContain("overflow-auto");
    expect(table.querySelector("thead")!.className).toContain("sticky");
    expect(screen.getByRole("columnheader", { name: /Title/ }).style.width).toBe("320px");
  });
  it("reports sorting with aria-sort; only sortable columns have a sort button", async () => {
    await renderDs(<Demo />);
    const title = screen.getByRole("columnheader", { name: /Title/ });
    expect(title.getAttribute("aria-sort")).toBe("ascending");
    await userEvent.click(within(title).getByRole("button"));
    expect(title.getAttribute("aria-sort")).toBe("descending");
    expect(within(screen.getByRole("columnheader", { name: "Buyer" })).queryByRole("button")).toBeNull();
  });
  it("rows are walked with the arrow keys, Home and End; Enter opens; Space selects", async () => {
    const onOpen = vi.fn();
    await renderDs(<Demo onOpen={onOpen} />);
    const rows = () => screen.getAllByRole("row").slice(1);
    expect(rows().map((r) => r.tabIndex)).toEqual([0, -1, -1]);              // one tab stop
    rows()[0].focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(rows()[1]);
    await userEvent.keyboard("{End}");
    expect(document.activeElement).toBe(rows()[2]);
    await userEvent.keyboard("{Home}{ArrowDown}{Enter}");
    expect(onOpen).toHaveBeenCalledWith(ROWS[1]);
    expect(rows()[1].getAttribute("aria-selected")).toBe("true");
    expect(rows()[1].getAttribute("data-active")).toBe("true");
    await userEvent.keyboard(" ");
    expect((within(rows()[1]).getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
  });
  it("select all, and a click on a row opens it but a click on its checkbox does not", async () => {
    const onOpen = vi.fn();
    await renderDs(<Demo onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Select every row" }));
    expect(screen.getAllByRole("checkbox", { name: "Select row" }).every((c) => (c as HTMLInputElement).checked)).toBe(true);
    expect(onOpen).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("Flange"));
    expect(onOpen).toHaveBeenCalledWith(ROWS[2]);
  });
  it("has empty, loading and error rows, and a compact density", async () => {
    const view = await renderDs(<DataTable columns={COLUMNS} data={[]} rowKey={(r) => r.id} empty="No listings yet" emptyAction={<Button>Harvest</Button>} />);
    expect(screen.getByTestId("empty-state").textContent).toContain("No listings yet");
    expect(screen.getByRole("button", { name: "Harvest" })).toBeTruthy();
    view.rerender(<DataTable columns={COLUMNS} data={[]} rowKey={(r) => r.id} loading />);
    expect(screen.getAllByTestId("table-skeleton")).toHaveLength(5);
    expect(screen.queryByTestId("empty-state")).toBeNull();
    expect(screen.getByRole("table").getAttribute("aria-busy")).toBe("true");
    const onRetry = vi.fn();
    view.rerender(<DataTable columns={COLUMNS} data={[]} rowKey={(r) => r.id} error={{ code: "nope" }} onRetry={onRetry} />);
    await userEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
    view.rerender(<DataTable columns={COLUMNS} data={ROWS} rowKey={(r) => r.id} dense testId="dense" />);
    expect(screen.getByTestId("dense").getAttribute("data-dense")).toBe("true");
    expect(screen.getAllByRole("cell")[0].className).toContain("h-9");
  });
});

describe("Pagination, DescriptionList, Stat, KPI", () => {
  it("pages forward and back and stops at the ends", async () => {
    const onPage = vi.fn();
    await renderDs(<Pagination page={1} pageSize={50} total={120} onPage={onPage} />);
    expect(screen.getByText("1–50 of 120")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous page" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
  it("lists facts and leaves out empty ones", async () => {
    await renderDs(<><DescriptionList items={[{ label: "Incoterm", value: "CFR" }, { label: "Place", value: "" }, { label: "Notes", value: null }]} /><Stat label="Margin" value="19%" tone="success" />
      <KpiTile label="Profit this quarter" value="1.3" unit="billion" note="+22% on last quarter" estimated testId="kpi" /></>);
    expect(screen.getAllByRole("term").map((t) => t.textContent)).toEqual(["Incoterm"]);
    expect(screen.getByText("19%").className).toContain("text-success");
    expect(screen.getByTestId("kpi").textContent).toContain("estimated");          // an estimated figure says so in words
  });
});

describe("Timeline and Stepper", () => {
  const items = [
    { key: "a", when: "6 Aban", title: "Listing starred", state: "done" as const },
    { key: "b", when: "15 Aban", title: "In transit", state: "current" as const },
    { key: "c", title: "Clearance", state: "upcoming" as const },
  ];
  it("the vertical timeline marks the current step and says what is expected", async () => {
    await renderDs(<Timeline label="Deal story" items={items} />);
    const list = screen.getByRole("list", { name: "Deal story" });
    const steps = within(list).getAllByRole("listitem");
    expect(steps.map((s) => s.getAttribute("data-state"))).toEqual(["done", "current", "upcoming"]);
    expect(steps[1].getAttribute("aria-current")).toBe("step");
    expect(steps[1].textContent).toContain("now");
    expect(steps[2].textContent).toContain("Expected");
  });
  it("the horizontal dated timeline shows dates and the current step", async () => {
    await renderDs(<DatedTimeline label="Tender dates" items={items} />);
    expect(within(screen.getByRole("list", { name: "Tender dates" })).getAllByRole("listitem")[1].getAttribute("aria-current")).toBe("step");
  });
  it("the deal path numbers its steps, ticks the finished ones and names the current one", async () => {
    await renderDs(<Stepper label="Deal path" steps={[{ key: "inquiry", label: "Inquiry", state: "done" }, { key: "quote", label: "Quote", state: "done" },
      { key: "order", label: "Order", state: "current" }, { key: "shipment", label: "Shipment", state: "upcoming" }]} />);
    const steps = within(screen.getByRole("list", { name: "Deal path" })).getAllByRole("listitem");
    expect(steps[2].getAttribute("aria-current")).toBe("step");
    expect(within(steps[0]).getByRole("img", { name: "Done" })).toBeTruthy();
    expect(steps[2].textContent).toBe("3Order");
    expect(steps[3].textContent).toBe("4Shipment");
  });
});

describe("Progress", () => {
  it("bar and ring expose their value; the indeterminate bar has none; segments are described in words", async () => {
    await renderDs(<><ProgressBar label="Download" value={62} /><ProgressBar label="Working" /><ProgressRing label="Time left" value={130}>5:10</ProgressRing>
      <ProgressBar label="Money" segments={[{ value: 30, tone: "success", label: "received" }, { value: 10, tone: "danger", label: "paid" }, { value: 60, tone: "neutral", label: "left" }]} /></>);
    expect(screen.getByRole("progressbar", { name: "Download" }).getAttribute("aria-valuenow")).toBe("62");
    expect(screen.getByRole("progressbar", { name: "Working" }).getAttribute("aria-valuenow")).toBeNull();
    expect(screen.getByRole("progressbar", { name: "Time left" }).getAttribute("aria-valuenow")).toBe("100");       // clamped
    expect(screen.getByRole("img", { name: "Money: received 30%، paid 10%، left 60%" })).toBeTruthy();
  });
});

describe("charts: an accessible name and a text alternative", () => {
  const fmt = (n: number) => `${n} USD`;
  it("Sparkline and Bars", async () => {
    await renderDs(<><Sparkline label="Profit by month" values={[10, 14, 12, 20]} format={fmt} /><Bars label="Win rate" highlight="m3" format={fmt}
      items={[{ key: "m1", label: "Mehr", value: 2 }, { key: "m2", label: "Aban", value: 5 }, { key: "m3", label: "Azar", value: 4 }]} /></>);
    expect(screen.getByRole("img", { name: "Profit by month: from 10 USD to 20 USD" })).toBeTruthy();
    expect(within(screen.getByRole("table", { name: "Profit by month" })).getAllByRole("row")).toHaveLength(5);
    expect(screen.getByRole("img", { name: "Win rate: Mehr 2 USD، Aban 5 USD، Azar 4 USD" })).toBeTruthy();
    expect(within(screen.getByRole("table", { name: "Win rate" })).getByRole("rowheader", { name: "Aban" })).toBeTruthy();
  });
  it("ProfitBridge names every step with its sign and marks estimated parts in words", async () => {
    await renderDs(<ProfitBridge label="Plan to actual" format={fmt} estimated={["costs"]} steps={[{ key: "plan", label: "Plan", value: 1000, kind: "total" },
      { key: "fx", label: "FX effect", value: 200, kind: "delta" }, { key: "costs", label: "Costs", value: -500, kind: "delta" }, { key: "actual", label: "Actual", value: 700, kind: "total" }]} />);
    expect(screen.getByRole("img", { name: "Plan to actual: Plan 1000 USD، FX effect +200 USD، Costs −500 USD، Actual 700 USD" })).toBeTruthy();
    const rows = within(screen.getByRole("table", { name: "Plan to actual" })).getAllByRole("row").map((r) => r.textContent);
    expect(rows).toEqual(["StepAmount", "Plan1000 USD", "FX effect+200 USD", "Costs (estimated)−500 USD", "Actual700 USD"]);
    expect(screen.getByTestId("profit-bridge").querySelectorAll("rect")).toHaveLength(4);
  });
  it("CashFlow names the lowest balance and lists in, out and balance", async () => {
    await renderDs(<CashFlow label="Cash, next 90 days" opening={50} format={fmt} points={[{ key: "w1", label: "W1", cashIn: 100, cashOut: 0 },
      { key: "w2", label: "W2", cashIn: 0, cashOut: 250 }, { key: "w3", label: "W3", cashIn: 300, cashOut: 50 }]} />);
    expect(screen.getByRole("img", { name: "Cash, next 90 days. Lowest balance: W2, -100 USD" })).toBeTruthy();
    expect(screen.getByTestId("cash-lowest").textContent).toContain("Lowest balance");
    const rows = within(screen.getByRole("table", { name: "Cash, next 90 days" })).getAllByRole("row").map((r) => r.textContent);
    expect(rows[2]).toBe("W2 (Lowest balance)0 USD250 USD-100 USD");
  });
  it("RouteLine names the stops in order with their state, and carries its caption", async () => {
    await renderDs(<RouteLine label="Shipment route" caption="From recorded events; not a live vessel position."
      stops={[{ key: "a", name: "Shanghai", code: "CNSHA", when: "20 Aban", state: "done" }, { key: "b", name: "Jebel Ali", code: "AEJEA", state: "last" },
        { key: "c", name: "Bushehr", code: "IRBUZ", state: "upcoming" }]} />);
    expect(screen.getByRole("img", { name: "Shipment route: Shanghai (CNSHA) Passed ← Jebel Ali (AEJEA) Last recorded event ← Bushehr (IRBUZ) Ahead" })).toBeTruthy();
    expect(screen.getByText("From recorded events; not a live vessel position.")).toBeTruthy();
    expect(within(screen.getByRole("table", { name: "Shipment route" })).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByTestId("route-line").querySelector("[data-state=last]")).not.toBeNull();
  });
});

describe("states and the page header", () => {
  it("loading is announced, empty has its one action, error says what happened and retries", async () => {
    const retry = vi.fn();
    const { container } = await renderDs(<><Loading /><Skeleton lines={3} /><EmptyState title="No cases yet" action={<Button>New inquiry</Button>}>Start with an inquiry.</EmptyState>
      <ErrorState error={{ code: "unknown_code_xyz" }} onRetry={retry} /><InlineAlert tone="warning" title="FX rate is old">Update it.</InlineAlert><ErrorNote error={null} /></>);
    expect(screen.getByRole("status", { name: "Loading…" }).getAttribute("aria-busy")).toBe("true");
    expect(container.querySelectorAll("[aria-hidden=true]").length).toBeGreaterThan(3);
    expect(within(screen.getByTestId("empty-state")).getByRole("button", { name: "New inquiry" })).toBeTruthy();
    const error = screen.getByTestId("error-state");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).not.toContain("unknown_code_xyz");            // never the raw error
    await userEvent.click(within(error).getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    expect(screen.getByText("FX rate is old").closest("[role=status]")).not.toBeNull();
  });
  it("the page header has one h1, the breadcrumb, the code chip, the status and a menu of secondary actions", async () => {
    const archive = vi.fn();
    await renderDs(<PageHeader title="Industrial pumps" code="CS-1405-0003" breadcrumb={[{ label: "Cases", to: "/cases" }, { label: "CS-1405-0003" }]}
      status={<span>Open</span>} actions={<Button variant="primary">Record documents</Button>} menu={[{ key: "archive", label: "Archive", onSelect: archive }]} />);
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["Industrial pumps"]);
    expect(screen.getByRole("heading", { level: 1 }).className).toContain("font-display");
    expect(within(screen.getByRole("navigation", { name: "Page path" })).getByRole("link", { name: "Cases" }).getAttribute("href")).toBe("/cases");
    expect(screen.getByTestId("code-chip").textContent).toContain("CS-1405-0003");
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(archive).toHaveBeenCalled();
  });
});
