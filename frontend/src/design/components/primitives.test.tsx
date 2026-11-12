// @vitest-environment jsdom
/** v0.10.0 primitives: states (disabled, loading), accessible names, keyboard, both directions. */
import { cleanup, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Badge, Button, ButtonLink, Chip, CodeChip, Icon, IconButton, Kbd, Spinner, Status, TextLink, Tooltip } from ".";
import { renderDs } from "./testing";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
afterEach(cleanup);

describe("Button", () => {
  it("runs its action with the mouse and the keyboard", async () => {
    const onClick = vi.fn();
    await renderDs(<Button variant="primary" icon="plus" onClick={onClick}>New inquiry</Button>);
    const button = screen.getByRole("button", { name: "New inquiry" });
    expect(button.getAttribute("type")).toBe("button");
    await userEvent.click(button);
    button.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onClick).toHaveBeenCalledTimes(3);
  });
  it("disabled and loading buttons do nothing; loading is announced", async () => {
    const onClick = vi.fn();
    await renderDs(<><Button disabled onClick={onClick}>Off</Button><Button busy onClick={onClick}>Saving</Button></>);
    await userEvent.click(screen.getByRole("button", { name: "Off" }));
    const busy = screen.getByRole("button", { name: /Saving/ });
    await userEvent.click(busy);
    expect(onClick).not.toHaveBeenCalled();
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(busy.querySelector("[role=status]")).not.toBeNull();
  });
  it("every variant and size has its own style, and a small button keeps a 40 px target", async () => {
    await renderDs(<>{(["primary", "secondary", "ghost", "danger"] as const).map((v) => <Button key={v} variant={v}>{v}</Button>)}
      <Button size="md">md</Button><Button size="lg">lg</Button></>);
    const cls = (name: string) => screen.getByRole("button", { name }).className;
    expect(new Set(["primary", "secondary", "ghost", "danger"].map(cls)).size).toBe(4);
    expect(cls("primary")).toContain("from-accent-fill-from");
    expect(cls("danger")).toContain("text-danger");
    expect(cls("primary")).toContain("h-8");
    expect(cls("primary")).toContain("after:-inset-1");          // 32 px + 2 x 4 px = 40 px target
    expect(cls("md")).toContain("h-10");
    expect(cls("lg")).toContain("h-12");
  });
  it("a link styled as a button opens in a new tab safely", async () => {
    await renderDs(<ButtonLink href="/api/x.pdf" newTab icon="download">PDF</ButtonLink>);
    const a = screen.getByRole("link", { name: "PDF" });
    expect([a.getAttribute("target"), a.getAttribute("rel")]).toEqual(["_blank", "noreferrer"]);
  });
});

describe("IconButton, TextLink, Kbd, Spinner", () => {
  it("an icon-only button is named by its label and can be pressed", async () => {
    await renderDs(<IconButton icon="star" label="Star" active />);
    const b = screen.getByRole("button", { name: "Star" });
    expect(b.getAttribute("aria-pressed")).toBe("true");
    expect(b.getAttribute("title")).toBe("Star");
    expect(b.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
  it("renders a link, a key and a named spinner", async () => {
    await renderDs(<><TextLink href="/cases">Cases</TextLink><Kbd>Ctrl K</Kbd><Spinner /></>);
    expect(screen.getByRole("link", { name: "Cases" })).toBeTruthy();
    expect(screen.getByText("Ctrl K").tagName).toBe("KBD");
    expect(screen.getByRole("status", { name: "Loading…" })).toBeTruthy();
  });
  it("an icon that carries meaning alone has a name; decorative ones are hidden", async () => {
    const { container } = await renderDs(<><Icon name="check" title="Done" /><Icon name="check" /></>);
    expect(screen.getByRole("img", { name: "Done" })).toBeTruthy();
    expect(container.querySelectorAll("svg[aria-hidden=true]")).toHaveLength(1);
  });
});

describe("Badge, Status, Chip", () => {
  it("a status carries an icon and a word, never colour alone", async () => {
    const { container } = await renderDs(<><Status tone="success">Paid</Status><Status tone="danger">Overdue</Status><Badge>Draft</Badge></>);
    expect(screen.getByText("Paid").querySelector("svg")).not.toBeNull();
    expect(screen.getByText("Overdue").querySelector("svg")).not.toBeNull();
    expect(screen.getByText("Draft").querySelector("svg")).toBeNull();
    expect(container.querySelectorAll("svg")).toHaveLength(2);
  });
  it("a filter chip is a toggle; a tag can be removed", async () => {
    const onClick = vi.fn(), onRemove = vi.fn();
    await renderDs(<><Chip selected onClick={onClick}>Starred</Chip><Chip onRemove={onRemove} removeLabel="Remove pump">pump</Chip></>);
    const filter = screen.getByRole("button", { name: "Starred" });
    expect(filter.getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(filter);
    await userEvent.click(screen.getByRole("button", { name: "Remove pump" }));
    expect([onClick.mock.calls.length, onRemove.mock.calls.length]).toEqual([1, 1]);
  });
});

describe("CodeChip", () => {
  it("shows the code left to right in the fixed face and copies it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await renderDs(<CodeChip code="CS-1405-0012" />, { lang: "fa" });
    const chip = screen.getByTestId("code-chip");
    const bdi = chip.querySelector("bdi")!;
    expect([bdi.textContent, bdi.getAttribute("dir"), bdi.className.includes("font-mono")]).toEqual(["CS-1405-0012", "ltr", true]);
    fireEvent.click(chip);
    expect(writeText).toHaveBeenCalledWith("CS-1405-0012");
    expect(chip.getAttribute("title")).toBe("کپی شد");
  });
  it("renders nothing without a code, and plain text without copy", async () => {
    const { container } = await renderDs(<><CodeChip code={null} /><CodeChip code="PO-1" copy={false} /></>);
    expect(container.querySelectorAll("[data-testid=code-chip]")).toHaveLength(1);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Tooltip", () => {
  it("shows on hover and on keyboard focus, describes its child, and Escape hides it", async () => {
    await renderDs(<Tooltip text="Not a live position"><button type="button">Route</button></Tooltip>);
    expect(screen.queryByRole("tooltip")).toBeNull();
    await userEvent.tab();
    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toBe("Not a live position");
    expect(screen.getByRole("button", { name: "Route" }).parentElement!.getAttribute("aria-describedby")).toBe(tip.id);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
    await userEvent.hover(screen.getByRole("button", { name: "Route" }));
    expect(screen.getByRole("tooltip")).toBeTruthy();
    await userEvent.unhover(screen.getByRole("button", { name: "Route" }));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
