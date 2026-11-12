/** v0.10.0 command center: the most important thing now, the time left, today's timeline. */
import { describe, expect, it } from "vitest";

import { endOfDay, focus, type Moment, moments, timeLeftPercent, todayLine } from "./today";
import type { CommandCenter } from "./types";

const now = new Date(2026, 10, 12, 14, 0, 0);       // 12 Nov 2026 14:00 local
const at = (d: number, h: number, m = 0) => new Date(2026, 10, d, h, m).toISOString();
const m = (key: string, when: string, priority = 2, kind: Moment["kind"] = "task"): Moment => ({ key, kind, at: when, title: key, link: "/", allDay: false, priority });

describe("most important now", () => {
  it("is the soonest deadline ahead within 72 h", () => {
    expect(focus([m("later", at(13, 9)), m("soon", at(12, 19)), m("far", at(20, 9))], now)?.key).toBe("soon");
  });
  it("breaks a tie in the same hour by priority (a tender date before a task)", () => {
    expect(focus([m("task", at(12, 19, 40), 2), m("tender", at(12, 19, 10), 0, "tender")], now)?.key).toBe("tender");
  });
  it("with nothing ahead, the most recently passed one", () => {
    expect(focus([m("old", at(10, 9)), m("recent", at(12, 9))], now)?.key).toBe("recent");
    expect(focus([], now)).toBeNull();
  });
  it("the time left is the share of the 72-hour window", () => {
    expect(timeLeftPercent(m("x", at(13, 8)), now)).toBeCloseTo(25, 5);      // 18 h of 72
    expect(timeLeftPercent(m("x", at(11, 8)), now)).toBe(0);
    expect(timeLeftPercent(m("x", at(30, 8)), now)).toBe(100);
  });
});

describe("today's timeline", () => {
  it("keeps today only, in time order, marks passed, next and later", () => {
    const line = todayLine([m("b", at(12, 18)), m("a", at(12, 9)), m("c", at(12, 20)), m("tomorrow", at(13, 9))], now);
    expect(line.map((x) => [x.key, x.state])).toEqual([["a", "done"], ["b", "current"], ["c", "upcoming"]]);
  });
});

describe("moments from the command center", () => {
  const cc = {
    today_date: "2026-11-12", overdue: [], today: [{ id: "f1", party_id: "p", party_name_fa: "پارس", party_name_en: "Pars", do_not_contact: false, party_status: "active", action: "Call", due_on: "2026-11-12", interaction_id: null }],
    upcoming_7_days: [], stale_leads: [], stale_lead_days: 14, funnel_counts: {},
    sourcing: { quotes_expiring: [{ quote_id: "q", number: "PI-1405-0007", case_id: "c", case_title: "Pumps", valid_until: "2026-11-13", currency: "USD", total: "1", party_name_fa: null, party_name_en: null, days_left: 1 }] },
    tenders: { dates_soon: [{ tender_id: "t", case_id: "c", case_title: "Lavan refinery", tender_no: null, kind: "proposal", label: "", at: at(12, 19, 10) }] },
    setad: { due: [{ id: "l", source: "eproc", external_no: "1", title: "Pump", organization: "NIOC", status: "starred", inquiry_id: null, deadline: at(13, 9), passed: false }], deadline_changed: [], warn_new: [], runs: [], stale_days: 3 },
    tasks: { overdue: [], today: [{ id: "k", title: "Customs", due_on: "2026-11-12", due_at: null, status: "open", priority: "high", case_id: null }], tomorrow: [] },
    execution: { steps_due: [{ step_id: "s", case_id: "c", label_fa: "ثبت سفارش", label_en: "Order registration", due_on: "2026-11-12", overdue: false, case_title: "Pumps" }] },
  } as unknown as CommandCenter;
  it("collects tender dates, Setad deadlines, tasks, follow-ups, process steps and quotes, with links", () => {
    const all = moments(cc, "en");
    expect(all.map((x) => x.kind).sort()).toEqual(["followup", "quote", "setad", "step", "task", "tender"]);
    expect(all.find((x) => x.kind === "setad")!.link).toBe("/tenders?source=eproc&include_old=1&listing=l");
    expect(all.find((x) => x.kind === "task")).toMatchObject({ allDay: true, at: endOfDay("2026-11-12").toISOString(), priority: 0 });
    expect(all.find((x) => x.kind === "followup")!.detail).toBe("Pars");
    expect(moments(cc, "fa").find((x) => x.kind === "step")!.title).toBe("ثبت سفارش");
    expect(focus(all, now)?.kind).toBe("tender");
  });
});
