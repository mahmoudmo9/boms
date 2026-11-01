import { describe, expect, it } from "vitest";

import { finishedJobs, groupTechnical, listingJobState, siteDate, technicalLabel, valueLabel } from "./setadFields";

describe("technical fields", () => {
  it("site titles first, then known keys, else none (the raw key is shown)", () => {
    expect(technicalLabel("need_no", null, "fa")).toBe("شماره نیاز");
    expect(technicalLabel("need_no", null, "en")).toBe("Need number");
    expect(technicalLabel("detail_url", "آدرس در سایت", "fa")).toBe("آدرس در سایت");
    expect(technicalLabel("lastTenderEdition.guarantyPrice", null, "fa")).toBe("مبلغ تضمین");
    expect(technicalLabel("someUnknownKey", null, "fa")).toBeNull();
  });
  it("value labels", () => {
    expect(valueLabel("TRUE", "fa")).toBe("بله");
    expect(valueLabel("false", "en")).toBe("No");
    expect(valueLabel("ONE_STAGE_TENDER", "fa")).toBe("مناقصه یک مرحله‌ای");
    expect(valueLabel("متن", "fa")).toBe("متن");
  });
  it("groups as group_pairs, sorted, with a filter", () => {
    const rows = [{ key: "response_deadline", label: "مهلت پاسخ", value: "۳ روز" }, { key: "need_no", label: "شماره نیاز", value: "110" },
      { key: "guarantyPrice", label: "مبلغ تضمین", value: "5" }, { key: "category", label: "طبقه‌بندی", value: "کالا" }];
    const g = groupTechnical(rows);
    expect(g.map((x) => x.group)).toEqual(["general", "schedule", "money"]);
    expect(g[0].rows.map((r) => r.key)).toEqual(["need_no", "category"]);
    expect(groupTechnical(rows, "110").flatMap((x) => x.rows.map((r) => r.key))).toEqual(["need_no"]);
  });
});

describe("site dates", () => {
  it("parses the site's Jalali date and time without the remark", () => {
    const d = siteDate("1405/08/06 - 10:03 (باقی‌مانده هنگام دریافت: 14 روز و 1 ساعت)")!;
    expect(d.time).toBe(true);
    expect(new Date(d.iso).getFullYear()).toBe(2026);
    expect(siteDate("۱۴۰۵/۰۸/۱۲ ساعت ۱۴:۰۰")!.time).toBe(true);
    expect(siteDate("1405/08/12")!.time).toBe(false);
    expect(siteDate("پمپ ۱۲")).toBeNull();
  });
});

describe("agent work per listing (mocked job lifecycle)", () => {
  it("queued -> running with attachment n of m -> finished once; its listings are refreshed", () => {
    const a = "L1", b = "L2";
    let seen = new Map();
    // queued
    let agent = { jobs: [{ id: "J", command: "download_files", status: "queued", listing_ids: [a, b] }] };
    expect(listingJobState(agent, a, "download_files")).toMatchObject({ state: "queued" });
    let [done, next] = finishedJobs(seen, agent.jobs); seen = next;
    expect(done).toEqual([]);
    // running, on listing a, attachment 2 of 3; b waits in the same job
    const running = { jobs: [{ id: "J", command: "download_files", status: "running", listing_ids: [a, b] }], job_id: "J", listing_id: a, files_done: 2, files_total: 3 };
    expect(listingJobState(running, a, "download_files")).toEqual({ jobId: "J", state: "running", done: 2, total: 3 });
    expect(listingJobState(running, b, "download_files")).toMatchObject({ state: "queued" });
    expect(listingJobState(running, a, "fetch_detail")).toBeNull();
    [done, next] = finishedJobs(seen, running.jobs); seen = next;
    expect(done).toEqual([]);
    // finished: reported once with both listings
    agent = { jobs: [] };
    [done, next] = finishedJobs(seen, agent.jobs); seen = next;
    expect(done).toEqual([{ id: "J", job: { command: "download_files", listing_ids: [a, b] } }]);
    expect(finishedJobs(seen, [])[0]).toEqual([]);
    expect(listingJobState(agent, a, "download_files")).toBeNull();
  });
});
