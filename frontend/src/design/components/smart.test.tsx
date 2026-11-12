// @vitest-environment jsdom
/** v0.10.0 smart fields in the library: LookupField (keyboard, exact code first as the backend ranks, clear),
 * SuggestedValue (Tab accepts while empty, source chip), ValidatedInput (state in words and an icon). */
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LookupItem } from "../../lib/smart";
import { Input, LookupField, SuggestedValue, ValidatedInput } from ".";
import { renderDs } from "./testing";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
const api = vi.fn();
vi.mock("../../lib/api", () => ({ api: (...args: unknown[]) => api(...args) }));

const PLACES: LookupItem[] = [
  { kind: "location", id: "1", code: "CNSHA", name_fa: "شانگهای", name_en: "Shanghai", subtitle: "CN · port" },
  { kind: "location", id: "2", code: "CNSZX", name_fa: "شنژن", name_en: "Shenzhen", subtitle: "CN · port" },
];
beforeEach(() => { api.mockReset(); api.mockImplementation(async (_p: string, o: { query: { q: string } }) => PLACES.filter((p) => !o.query.q || `${p.code}${p.name_en}`.toLowerCase().includes(o.query.q.toLowerCase()))); });
afterEach(cleanup);

describe("LookupField", () => {
  function Demo({ onPicked }: { onPicked?: (i: LookupItem | null) => void }) {
    const [v, setV] = useState<LookupItem | null>(null);
    return <LookupField kind="location" ariaLabel="Origin" value={v} onChange={(i) => { setV(i); onPicked?.(i); }} filters={{ mode: "sea" }} testId="origin" />;
  }
  it("asks the backend for what is typed and lists name, code and subtitle", async () => {
    await renderDs(<Demo />);
    const input = screen.getByRole("combobox", { name: "Origin" });
    await userEvent.click(input);
    await userEvent.keyboard("sha");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(1));
    expect(api).toHaveBeenLastCalledWith("/api/lookup", { query: { kind: "location", q: "sha", mode: "sea" }, background: true });
    expect(screen.getByRole("option").textContent).toBe("ShanghaiCN · portCNSHA");
  });
  it("arrows and Enter choose; the chosen row is shown as «name (code)» and can be cleared", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} />);
    const input = screen.getByRole("combobox", { name: "Origin" });
    await userEvent.click(input);
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(document.getElementById(input.getAttribute("aria-activedescendant")!)!.textContent).toContain("Shenzhen");
    await userEvent.keyboard("{Enter}");
    expect(picked).toHaveBeenCalledWith(PLACES[1]);
    await waitFor(() => expect(screen.getByTestId("origin").textContent).toBe("Shenzhen (CNSZX)"));
    await userEvent.click(screen.getByRole("button", { name: "Clear: Shenzhen (CNSZX)" }));
    expect(picked).toHaveBeenLastCalledWith(null);
  });
  it("Tab chooses the active row; Escape closes; a list being replaced is never acted on", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} />);
    const input = screen.getByRole("combobox", { name: "Origin" });
    await userEvent.click(input);
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    await userEvent.keyboard("s{Enter}");                          // typed just now: the old list is not used
    expect(picked).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowDown}");                       // Enter closed the list; it opens again
    await userEvent.click(input);
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    await userEvent.keyboard("{ArrowDown}{Tab}");
    expect(picked).toHaveBeenCalledWith(PLACES[0]);
  });
  it("shows the Persian name in Persian", async () => {
    await renderDs(<Demo />, { lang: "fa" });
    await userEvent.click(screen.getByRole("combobox", { name: "Origin" }));
    await waitFor(() => expect(screen.getAllByRole("option")[0].textContent).toContain("شانگهای"));
  });
});

describe("SuggestedValue", () => {
  function Demo({ onAccept }: { onAccept: (v: string) => void }) {
    const [v, setV] = useState("");
    return (
      <SuggestedValue current={v} suggestion={{ value: "FOB", source: "PO-1405-0007" }} onAccept={(x) => { setV(x); onAccept(x); }}>
        <Input aria-label="Incoterm" value={v} onChange={(e) => setV(e.target.value)} />
      </SuggestedValue>
    );
  }
  it("shows the proposal with its source chip; Tab accepts it while the field is empty", async () => {
    const onAccept = vi.fn();
    await renderDs(<Demo onAccept={onAccept} />);
    expect(screen.getByTestId("suggested-value").textContent).toContain("from PO-1405-0007");
    screen.getByLabelText("Incoterm").focus();
    await userEvent.keyboard("{Tab}");
    expect(onAccept).toHaveBeenCalledWith("FOB");
    expect((screen.getByLabelText("Incoterm") as HTMLInputElement).value).toBe("FOB");
    expect(screen.queryByTestId("suggested-value")).toBeNull();
  });
  it("a click accepts too; once the field has a value nothing is proposed", async () => {
    const onAccept = vi.fn();
    await renderDs(<Demo onAccept={onAccept} />);
    await userEvent.type(screen.getByLabelText("Incoterm"), "CIF");
    expect(screen.queryByTestId("suggested-value")).toBeNull();
    await userEvent.clear(screen.getByLabelText("Incoterm"));
    await userEvent.click(screen.getByTestId("suggested-value"));
    expect(onAccept).toHaveBeenCalledWith("FOB");
  });
});

describe("ValidatedInput", () => {
  function Demo() {
    const [v, setV] = useState("");
    return <ValidatedInput kind="iban" ariaLabel="IBAN" value={v} onChange={setV} testId="iban" />;
  }
  it("says valid or invalid in words with an icon, and tidies a valid value on blur", async () => {
    await renderDs(<Demo />);
    const input = screen.getByLabelText("IBAN");
    await userEvent.type(input, "DE89 3704 0044 0532 0130 01");
    expect(screen.getByTestId("iban").getAttribute("data-state")).toBe("invalid");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(input.getAttribute("aria-describedby")!)!.textContent).toBeTruthy();
    await userEvent.clear(input);
    await userEvent.type(input, "de89 3704 0044 0532 0130 00");
    expect(screen.getByTestId("iban").getAttribute("data-state")).toBe("valid");
    expect(screen.getByText("Valid")).toBeTruthy();
    expect(screen.getByTestId("iban").querySelector("svg")).not.toBeNull();
    await userEvent.tab();
    expect((input as HTMLInputElement).value).toBe("DE89 3704 0044 0532 0130 00");
  });
});
