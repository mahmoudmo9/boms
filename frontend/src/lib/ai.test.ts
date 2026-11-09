/** v0.9.0 review screen decisions: grouping per item, «ثبت» only with an accepted or edited field, «پذیرش همهٔ موارد
 * مطمئن» counts, values shown after a decision, edits keep their type, the cap tone and polling. */
import { describe, expect, it } from "vitest";

import { capTone, draftPoll, fromText, groupFields, inputDescription, reviewSummary, shownValue, toText, type DraftField } from "./ai";

const field = (path: string, confidence: DraftField["confidence"], decision: DraftField["decision"] = null, proposed: unknown = "x", final: unknown = null): DraftField =>
  ({ id: path, path, label: path, proposed, confidence, source: {}, decision, final });

describe("review screen", () => {
  const fields = [field("items[0].name", "high"), field("items[0].quantity", "high", null, 2), field("items[1].name", "low"), field("terms.currency", "medium")];
  it("groups fields per item, terms last", () => {
    const g = groupFields(fields);
    expect([...g.keys()]).toEqual([0, 1, -1]);
    expect(g.get(0)!.map((f) => f.path)).toEqual(["items[0].name", "items[0].quantity"]);
  });
  it("needs an accepted or edited field before «ثبت»", () => {
    expect(reviewSummary({ status: "ready", fields }).canCommit).toBe(false);
    expect(reviewSummary({ status: "ready", fields }).confidentOpen).toBe(2);
    const decided = [field("items[0].name", "high", "accepted", "Pump", "Pump"), field("items[1].name", "low", "rejected")];
    expect(reviewSummary({ status: "ready", fields: decided })).toMatchObject({ accepted: 1, rejected: 1, canCommit: true });
    expect(reviewSummary({ status: "accepted", fields: decided }).canCommit).toBe(false);
  });
  it("shows the final value once decided", () => {
    expect(shownValue(field("a", "high", "edited", "pcs", "set"))).toBe("set");
    expect(shownValue(field("a", "high", null, "pcs"))).toBe("pcs");
  });
  it("keeps the type of an edited value", () => {
    expect(fromText("3", 2)).toBe(3);
    expect(fromText('{"flow":"120"}', { flow: "100" })).toEqual({ flow: "120" });
    expect(fromText("set", "pcs")).toBe("set");
    expect(toText([{ key: "Seal", value: "53B" }])).toBe('[{"key":"Seal","value":"53B"}]');
  });
});

describe("AI settings", () => {
  it("cap tone at 50 % and 80 %, danger when reached", () => {
    expect(capTone({ percent: 10, reached: false })).toBe("neutral");
    expect(capTone({ percent: 80, reached: false })).toBe("warning");
    expect(capTone({ percent: 100, reached: true })).toBe("danger");
  });
  it("privacy log describes inputs without content", () => {
    expect(inputDescription({ files: ["a.pdf", "b.xlsx"], pages: 3, characters: 4200, images: 1 })).toEqual({ files: 2, pages: 3, characters: 4200, images: 1 });
  });
  it("polls only while the job runs", () => {
    expect(draftPoll("pending")).toBe(1500);
    expect(draftPoll("ready")).toBe(false);
  });
});
