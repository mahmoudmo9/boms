/** v0.10.0 live updates: what a notice refreshes, repeated notices dropped, job states, falling back to polling. */
import { describe, expect, it } from "vitest";

import { afterStreamError, jobStates, matches, type Notice, rootsFor, Seen } from "./live";

const job = (id: string, status: "queued" | "running" | "done" | "failed", type = "backup.run", at = "2026-11-12T10:00:00+00:00"): Notice =>
  ({ kind: "job", key: `job:${id}:${status}:${at}`, id, type, status, lane: "default", at });
const record = (entity_type: string, id = "x", at = "2026-11-12T10:00:00+00:00"): Notice =>
  ({ kind: "record", key: `event:${entity_type}:${id}:${at}`, entity_type, entity_id: id, action: "update", at });

describe("what a notice refreshes", () => {
  it("a finished job refreshes its own pages; a queued or running one only the system page", () => {
    expect([...rootsFor([job("1", "done", "documents.extract_text")])].sort()).toEqual(["case", "document", "document-text", "documents", "system"]);
    expect([...rootsFor([job("1", "running", "documents.extract_text")])]).toEqual(["system"]);
    expect(rootsFor([job("1", "failed", "something.new")]).has("*")).toBe(true);
  });
  it("a Setad listing change or download refreshes the listings and their detail", () => {
    const roots = rootsFor([record("listing"), { kind: "agent", key: "a", command: "download", listing_id: "l", files_done: 1, files_total: 3, pages_done: null, pages_total: null, connected: true, at: "t" }]);
    expect(roots.has("listings") && roots.has("listing") && roots.has("setad-agent")).toBe(true);
    expect(roots.has("*")).toBe(false);
  });
  it("an unknown record type refreshes every active query, except lookups and amounts in words", () => {
    const roots = rootsFor([record("brand_new_thing")]);
    expect(matches(["parties", "list"], roots)).toBe(true);
    expect(matches(["lookup", "location", "sha"], roots)).toBe(false);
    expect(matches(["words", "12", "USD"], roots)).toBe(false);
  });
  it("matches a query by the root of its key", () => {
    const roots = rootsFor([record("party")]);
    expect(matches(["parties", "list", 1], roots)).toBe(true);
    expect(matches(["listings", "list"], roots)).toBe(false);
  });
});

describe("repeated notices", () => {
  it("are dropped by key, and the memory stays bounded", () => {
    const seen = new Seen(3);
    const a = record("party", "a"), b = record("party", "b");
    expect(seen.fresh([a, b])).toEqual([a, b]);
    expect(seen.fresh([a, b, record("party", "c")]).map((n) => n.key)).toEqual([record("party", "c").key]);
    seen.fresh([record("party", "d")]);                         // a is forgotten (max 3)
    expect(seen.fresh([a])).toEqual([a]);
  });
});

describe("job states", () => {
  it("keeps the latest state of each job and ignores an older notice", () => {
    let s = jobStates({}, [job("1", "queued", "backup.run", "2026-11-12T10:00:00+00:00")]);
    s = jobStates(s, [job("1", "done", "backup.run", "2026-11-12T10:00:05+00:00"), job("2", "running")]);
    s = jobStates(s, [job("1", "running", "backup.run", "2026-11-12T10:00:03+00:00")]);
    expect([s["1"].status, s["2"].status]).toEqual(["done", "running"]);
    expect(jobStates(s, [record("party")])).toBe(s);            // nothing new: the same object
  });
});

describe("transport", () => {
  it("falls back to polling after three stream errors", () => {
    expect([1, 2, 3].map(afterStreamError)).toEqual(["stream", "stream", "polling"]);
  });
});
