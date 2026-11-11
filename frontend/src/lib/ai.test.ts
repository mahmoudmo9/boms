/** v0.9.0 review screen decisions: grouping per item, «ثبت» only with an accepted or edited field, «پذیرش همهٔ موارد
 * مطمئن» counts, values shown after a decision, edits keep their type, the cap tone and polling. */
import { describe, expect, it } from "vitest";

import { capTone, draftPoll, rectStyle, signInView, sourceFocus, splitSpan, type ClaudeStatus, type FieldSource, fromText, groupFields, inputDescription, reviewSummary, shownValue, toText, type DraftField } from "./ai";

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


describe("Claude sign-in block (v0.10.0)", () => {
  const base: ClaudeStatus = { state: "signed_out", sdk: true, sdk_version: "0.2.179", cli: "C:\\BOMS\\app\\venv\\claude.exe", account: "Owner",
    config_dir: "C:\\Users\\Owner\\.claude", logged_in: false, auth_method: null, email: null, other_accounts: [], can_open_console: true, detail: null };
  it("offers sign-in with its steps when signed out on the PC", () => {
    expect(signInView(base)).toEqual({ tone: "neutral", canLogin: true, canLogout: false, showSteps: true, otherAccounts: [] });
  });
  it("offers sign-out when signed in", () => {
    expect(signInView({ ...base, state: "signed_in", logged_in: true, email: "o@example.com" })).toMatchObject({ tone: "success", canLogin: false, canLogout: true, showSteps: false });
  });
  it("names the other Windows account that holds the sign-in", () => {
    expect(signInView({ ...base, state: "other_account", other_accounts: ["Admin"] })).toMatchObject({ tone: "warning", canLogin: true, otherAccounts: ["Admin"] });
  });
  it("cannot open a console away from the PC, and offers nothing without the CLI", () => {
    expect(signInView({ ...base, can_open_console: false })).toMatchObject({ canLogin: false, showSteps: true });
    expect(signInView({ ...base, state: "no_cli", cli: null })).toEqual({ tone: "danger", canLogin: false, canLogout: false, showSteps: false, otherAccounts: [] });
    expect(signInView({ ...base, state: "no_sdk", sdk: false })).toMatchObject({ tone: "danger", canLogin: false });
  });
});

describe("source of the field in focus (v0.10.0)", () => {
  it("places a region as percentages of the page, padded and kept inside it", () => {
    expect(rectStyle({ x: 0.1, y: 0.5, w: 0.3, h: 0.02 }, 0.01)).toEqual({ left: "9.000%", top: "49.000%", width: "32.000%", height: "4.000%" });
    expect(rectStyle({ x: 0, y: 0.99, w: 1, h: 0.02 }, 0.01)).toEqual({ left: "0.000%", top: "98.000%", width: "100.000%", height: "2.000%" });
  });
  it("cuts pasted text around the span", () => {
    expect(splitSpan("we need 10 valves now", 8, 17)).toEqual(["we need ", "10 valves", " now"]);
    expect(splitSpan("abc", undefined, undefined)).toEqual(["abc", "", ""]);
    expect(splitSpan("abc", 2, 99)).toEqual(["ab", "c", ""]);
  });
  it("highlights only the panel of the field's source", () => {
    const sheet: FieldSource = { field_id: "f", kind: "sheet", source_index: 1, found: true, original: "x", rows: [2, 3] };
    expect(sourceFocus(sheet, 1)).toEqual({ active: true, rows: new Set([2, 3]) });
    expect(sourceFocus(sheet, 0)).toEqual({ active: false, rows: new Set() });
    expect(sourceFocus({ field_id: "f", kind: "pdf", source_index: 0, found: false, original: "x", page: 2 }, 0).active).toBe(true);   // the page is shown
    expect(sourceFocus(null, 0).active).toBe(false);
  });
});
