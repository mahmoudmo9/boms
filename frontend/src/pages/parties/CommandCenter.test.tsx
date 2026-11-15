/** v0.10.1 section 1.2: dashboard lists are capped at 8 rows with «همه (n)»; a task's title has its own line; the
 * timeline count names what it counts. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import { lineCounts } from "../../lib/today";
import type { TaskRow } from "../../lib/tasks";
import type { ExecutionSummary } from "../../lib/types";

vi.mock("../../lib/prefs", () => ({
  useFormat: () => ({ lang: i18n.language, calendar: "gregorian", digits: "latin", num: (v: unknown) => String(Number(v)), money: (v: unknown) => String(Number(v)), compact: (v: unknown) => String(Number(v)),
    compactMoney: (v: unknown, c?: string) => ({ text: `${c} ${Number(v)}`, full: `${c} ${Number(v)}`, figure: String(Number(v)), unit: c ?? "" }), day: (v: string) => `day:${v}`,
    date: (v: string) => `date:${v}`, bytes: (v: number) => String(v) }),
}));

const { ExecutionSection } = await import("./CommandCenterPage");
const { TaskList } = await import("../tasks/TaskList");

const task = (i: number): TaskRow => ({ id: `t${i}`, title: `A long task title number ${i} that must keep its width`, due_on: "2026-11-14", due_at: null,
  status: "open", done_at: null, done_note: null, priority: "normal", case_id: "c1", case_title: "Pumps for Arak", party_id: null, source: "manual",
  source_kind: "manual", source_id: null, remind_of_due: null, remind_days_before: null, notes: null });

describe("command center lists", () => {
  it("shows at most 8 rows and links «All (n)» to the full list", async () => {
    await i18n.changeLanguage("en");
    const rows = Array.from({ length: 42 }, (_, i) => ({ purchase_order_id: `po${i}`, case_id: "c1", number: `PO-1405-${i}`, sent_at: "", days: 2, case_title: `Case ${i}` }));
    const s: ExecutionSummary = { pos_unconfirmed: rows, ready_passed: [], shipments_delayed: [], steps_due: [], payments_overdue: [], claims_open: [], deliveries_due: [] };
    const html = renderToStaticMarkup(<MemoryRouter><ExecutionSection s={s} /></MemoryRouter>);
    expect(html.match(/href="\/cases\/c1\?tab=purchase"/g)?.length).toBe(8);
    expect(html).toContain("All (42)");
    expect(html).toContain('href="/execution"');
    expect(html).toContain(">42<");   // the card's count is the full number, the same as the link
  });

  it("gives a task's title its own line, with case and due as secondary text", async () => {
    await i18n.changeLanguage("en");
    const html = renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><MemoryRouter><TaskList rows={[task(1)]} /></MemoryRouter></QueryClientProvider>);
    const title = html.indexOf('data-testid="task-title"');
    const meta = html.indexOf("Pumps for Arak");
    expect(title).toBeGreaterThan(-1);
    expect(meta).toBeGreaterThan(title);
    expect(html).toMatch(/data-testid="task-title"[^>]*><bdi>A long task title number 1/);
  });

  it("counts today's line per kind, never as one «deadlines» number", async () => {
    await i18n.changeLanguage("fa");
    const counts = lineCounts([{ kind: "setad" }, { kind: "setad" }, { kind: "task" }, { kind: "followup" }]);
    expect(counts).toEqual([{ kind: "task", n: 1 }, { kind: "followup", n: 1 }, { kind: "setad", n: 2 }]);
    const kind = "followup";
    expect(i18n.t(`cc.line.kinds.${kind}`, { count: 0, n: "۰" })).toBe("۰ پیگیری");
    expect(i18n.exists("cc.line.count")).toBe(false);
    expect(i18n.t("cc.today")).toBe("پیگیری‌های امروز");
    expect(i18n.t("cc.tasks.today")).toBe("کارهای امروز");
  });
});
