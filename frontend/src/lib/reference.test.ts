import { describe, expect, it } from "vitest";

import { percentDone, reasonKey, secondsLeft } from "./reference";

describe("reference import progress", () => {
  const started = "2026-11-14T10:00:00Z";
  it("estimates the time left from the rate so far", () => {
    expect(secondsLeft({ rows_read: 50_000, rows_total: 116_000, started_at: started }, Date.parse(started) + 10_000)).toBe(13);
    expect(secondsLeft({ rows_read: 0, rows_total: 116_000, started_at: started }, Date.parse(started) + 10_000)).toBeNull();
    expect(secondsLeft({ rows_read: 10, rows_total: null, started_at: started }, Date.parse(started) + 1_000)).toBeNull();
  });
  it("gives the share done and names the reasons", () => {
    expect(percentDone({ rows_read: 58_000, rows_total: 116_000 })).toBe(50);
    expect(reasonKey("column ELF Code not found")).toEqual({ key: "reference.reasons.column", value: "ELF Code" });
    expect(reasonKey("bad ELF code")).toEqual({ key: "reference.reasons.badElf" });
    expect(reasonKey("something new")).toEqual({ key: "", value: "something new" });
  });
});
