import { describe, expect, it } from "vitest";

import { remindsOf, taskLink } from "./tasks";

describe("tasks", () => {
  it("links a task to the case tab of its source", () => {
    expect(taskLink({ case_id: "c1", source_kind: "process_step" })).toBe("/cases/c1?tab=order");
    expect(taskLink({ case_id: "c1", source_kind: "tender_date" })).toBe("/cases/c1?tab=tender");
    expect(taskLink({ case_id: "c1", source_kind: "manual" })).toBe("/cases/c1?tab=tasks");
    expect(taskLink({ case_id: null, source_kind: "manual" })).toBeNull();
  });
  it("shows the reminded date only when it differs", () => {
    expect(remindsOf({ remind_of_due: "2026-12-10", due_on: "2026-12-07", due_at: null })).toBe("2026-12-10T23:59:00");
    expect(remindsOf({ remind_of_due: "2026-12-07", due_on: "2026-12-07", due_at: null })).toBeNull();
    expect(remindsOf({ remind_of_due: "2026-12-10", due_on: "2026-12-07", due_at: "2026-12-10T10:00:00Z" })).toBe("2026-12-10T10:00:00Z");
  });
});
