// @vitest-environment jsdom
/** v0.10.0 shell: the command palette (groups, exact code first, actions, recent items, keyboard) and live updates
 * (a finished job refreshes the open page through the stream; repeated notices are dropped; polling takes over when
 * the stream keeps failing). */
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { setLocale } from "../design/components/testing";
import { CommandPalette } from "./CommandPalette";
import { LiveUpdatesProvider, useJob, useLive } from "./LiveUpdates";

const updatePrefs = vi.fn();
vi.mock("../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user, updatePrefs }) }));
const api = vi.fn();
vi.mock("../lib/api", () => ({ api: (...args: unknown[]) => api(...args) }));

afterEach(() => { cleanup(); vi.useRealTimers(); localStorage.clear(); });
beforeEach(() => { api.mockReset(); updatePrefs.mockReset(); });

const GROUPS = [
  { type: "code", label_key: "search.type.code", items: [{ id: "k1", title: "CS-1405-0003", subtitle: "پمپ صنعتی", link: "/cases/k1", score: 1, title_i18n: null, extra: {}, match: "exact_code" }] },
  { type: "case", label_key: "search.type.case", items: [{ id: "k2", title: "پمپ‌های آتش‌نشانی", subtitle: "SO-1405-0001", link: "/cases/k2", score: 1, title_i18n: null, extra: {}, match: "name_contains" }] },
];

function Where() { return <span data-testid="where">{useLocation().pathname + useLocation().search}</span>; }

async function renderPalette(lang: "fa" | "en" = "en") {
  await setLocale({ lang });
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter initialEntries={["/"]}><QueryClientProvider client={client}><CommandPalette open onClose={onClose} /><Routes><Route path="*" element={<Where />} /></Routes></QueryClientProvider></MemoryRouter>);
  return onClose;
}

describe("command palette", () => {
  it("opens as a named dialog with the field focused; empty, it lists the main actions", async () => {
    await renderPalette();
    expect(screen.getByRole("dialog", { name: "Command or search" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByTestId("palette-input"));
    expect(screen.getAllByTestId("palette-row")[0].textContent).toBe("New inquiryEnter");      // the active row shows its key
    expect(api).not.toHaveBeenCalled();
  });
  it("a code finds the record first; Enter opens it and remembers it as recent", async () => {
    api.mockResolvedValue({ groups: GROUPS });
    const onClose = await renderPalette();
    await userEvent.keyboard("CS-1405-0003");
    await waitFor(() => expect(screen.getAllByTestId("palette-row")[0].getAttribute("data-exact")).toBe("true"));
    expect(api).toHaveBeenLastCalledWith("/api/search", expect.objectContaining({ query: { q: "CS-1405-0003", limit: 5 } }));
    const groups = screen.getAllByRole("group").map((g) => g.getAttribute("data-group"));
    expect(groups).toEqual(["code", "case", "actions"]);
    expect(screen.getAllByRole("option")[0].getAttribute("aria-selected")).toBe("true");
    await userEvent.keyboard("{Enter}");
    expect(onClose).toHaveBeenCalled();
    expect(screen.getByTestId("where").textContent).toBe("/cases/k1");
    expect(JSON.parse(localStorage.getItem("boms.palette.recent")!)[0]).toMatchObject({ id: "k1", link: "/cases/k1" });
  });
  it("arrows move across groups and wrap; the active row is announced", async () => {
    api.mockResolvedValue({ groups: GROUPS });
    await renderPalette();
    await userEvent.keyboard("pump");
    await waitFor(() => expect(screen.getAllByRole("group")[0].getAttribute("data-group")).toBe("code"));
    const input = screen.getByTestId("palette-input");
    await userEvent.keyboard("{ArrowDown}");
    expect(document.getElementById(input.getAttribute("aria-activedescendant")!)!.textContent).toContain("پمپ‌های آتش‌نشانی");
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    const last = screen.getAllByRole("option").at(-1)!;
    expect(last.getAttribute("aria-selected")).toBe("true");
  });
  it("«new inquiry for…» carries the query; a theme action changes the preference", async () => {
    api.mockResolvedValue({ groups: [] });
    await renderPalette();
    await userEvent.keyboard("valve 6");
    await waitFor(() => expect(screen.getByTestId("palette-empty").textContent).toContain("valve 6"));
    await userEvent.keyboard("{Enter}");
    expect(screen.getByTestId("where").textContent).toBe("/sourcing?new=1&subject=valve%206");
  });
  it("runs the theme and language actions", async () => {
    api.mockResolvedValue({ groups: [] });
    await renderPalette();
    await userEvent.keyboard("dark");
    await waitFor(() => expect(screen.getAllByTestId("palette-row").some((r) => r.textContent!.includes("Dark theme"))).toBe(true));
    await userEvent.click(screen.getAllByTestId("palette-row").find((r) => r.textContent!.includes("Dark theme"))!);
    expect(updatePrefs).toHaveBeenCalledWith({ theme: "dark" });
  });
  it("Escape closes; recent items show when the field is empty", async () => {
    localStorage.setItem("boms.palette.recent", JSON.stringify([{ id: "k9", type: "case", title: "Recent case", subtitle: null, link: "/cases/k9" }]));
    const onClose = await renderPalette("fa");
    expect(screen.getAllByRole("group")[0].getAttribute("data-group")).toBe("recent");
    expect(screen.getAllByTestId("palette-row")[0].textContent).toContain("Recent case");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});

class FakeEventSource {
  static last: FakeEventSource | null = null;
  url: string; onopen: (() => void) | null = null; onerror: (() => void) | null = null; closed = false;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(url: string) { this.url = url; FakeEventSource.last = this; }
  addEventListener(name: string, fn: (e: MessageEvent) => void) { (this.listeners[name] ??= []).push(fn); }
  emit(batch: unknown) { this.listeners.change?.forEach((fn) => fn(new MessageEvent("change", { data: JSON.stringify(batch) }))); }
  close() { this.closed = true; }
}

function SystemPageProbe({ fetcher }: { fetcher: () => Promise<number> }) {
  const q = useQuery({ queryKey: ["system", "backups"], queryFn: fetcher });
  const live = useLive();
  const job = useJob("j1");
  return <><span data-testid="value">{q.data}</span><span data-testid="transport">{live.transport}</span><span data-testid="job">{job?.status ?? "-"}</span></>;
}

const doneJob = (status = "done", at = "2026-11-12T10:00:02+00:00") => ({ cursor: "2026-11-12T10:00:03+00:00",
  notices: [{ kind: "job", key: `job:j1:${status}:${at}`, id: "j1", type: "backup.run", status, lane: "default", at }] });

describe("live updates", () => {
  beforeEach(() => { vi.stubGlobal("EventSource", FakeEventSource); FakeEventSource.last = null; });
  afterEach(() => vi.unstubAllGlobals());

  function mount(fetcher: () => Promise<number>) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    render(<QueryClientProvider client={client}><LiveUpdatesProvider><SystemPageProbe fetcher={fetcher} /></LiveUpdatesProvider></QueryClientProvider>);
  }

  it("a finished job reaches the open page through the stream and refreshes it; a repeat is ignored", async () => {
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    mount(fetcher);
    await waitFor(() => expect(screen.getByTestId("value").textContent).toBe("1"));
    const es = FakeEventSource.last!;
    expect(es.url).toBe("/api/live/stream");
    act(() => es.onopen?.());
    expect(screen.getByTestId("transport").textContent).toBe("stream");
    act(() => es.emit(doneJob()));
    await waitFor(() => expect(screen.getByTestId("value").textContent).toBe("2"));
    expect(screen.getByTestId("job").textContent).toBe("done");
    act(() => es.emit(doneJob()));                                  // the same notice again (overlap window)
    await new Promise((r) => setTimeout(r, 30));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("falls back to polling every 2 s after three stream errors, and resumes from the cursor", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.mockResolvedValue(doneJob());
    let n = 0;
    mount(async () => ++n);
    const es = FakeEventSource.last!;
    act(() => { es.onerror?.(); es.onerror?.(); });
    expect(es.closed).toBe(false);
    act(() => es.onerror?.());
    expect(es.closed).toBe(true);
    await waitFor(() => expect(screen.getByTestId("transport").textContent).toBe("polling"));
    expect(api).toHaveBeenCalledWith("/api/live/changes", { query: { since: null }, background: true });
    await waitFor(() => expect(screen.getByTestId("job").textContent).toBe("done"));
    api.mockResolvedValue({ cursor: "2026-11-12T10:00:05+00:00", notices: [] });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(api).toHaveBeenLastCalledWith("/api/live/changes", { query: { since: "2026-11-12T10:00:03+00:00" }, background: true });
  });
});
