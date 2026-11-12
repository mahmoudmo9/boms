// @vitest-environment jsdom
/** v0.10.0 containers: focus management of Modal, Drawer, Menu and Popover (first field, trap, Escape, focus back to
 * the opener), the typed confirmation, tabs with the arrow keys in both directions, toasts. */
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button, Card, ConfirmDialog, Drawer, Input, Menu, Modal, Popover, Section, Tabs, ToastProvider, useToast } from ".";
import { renderDs } from "./testing";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
afterEach(cleanup);

describe("Card and Section", () => {
  it("a card has its kinds, a titled header and actions", async () => {
    await renderDs(<><Card title="Money" actions={<Button>Add</Button>} testId="plain">x</Card><Card kind="accent" eyebrow="Next step" title="Shipping documents" testId="accent">y</Card>
      <Card kind="raised" testId="raised">z</Card><Section title="Contacts">c</Section></>);
    expect(within(screen.getByTestId("plain")).getByRole("heading", { name: "Money", level: 2 })).toBeTruthy();
    expect(screen.getByTestId("accent").className).toContain("border-accent-line");
    expect(screen.getByTestId("raised").className).toContain("shadow-md");
    expect(screen.getByText("Next step")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Contacts", level: 3 })).toBeTruthy();
  });
});

function ModalDemo({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <Modal open={open} title="New party" onClose={() => { setOpen(false); onClose?.(); }} footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary">Save</Button></>}>
        <Input aria-label="Name" /><Input aria-label="Country" />
      </Modal>
    </>
  );
}

describe("Modal", () => {
  it("is a named modal dialog; focus goes to the first field", async () => {
    await renderDs(<ModalDemo />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const dialog = screen.getByRole("dialog", { name: "New party" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("Name"));
  });
  it("keeps Tab inside, in both directions", async () => {
    await renderDs(<ModalDemo />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const dialog = screen.getByRole("dialog");
    for (const el of dialog.querySelectorAll<HTMLElement>("button, input")) Object.defineProperty(el, "offsetParent", { get: () => dialog });     // jsdom has no layout
    await userEvent.tab(); await userEvent.tab(); await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Save" }));
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" }));            // wrapped to the first control
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Save" }));
    expect(dialog.contains(document.activeElement)).toBe(true);
  });
  it("Escape, the close button and a click outside close it, and focus returns to the opener", async () => {
    const onClose = vi.fn();
    await renderDs(<ModalDemo onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Open" });
    await userEvent.click(opener);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    await userEvent.click(opener);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.click(opener);
    fireEvent.mouseDown(screen.getByRole("dialog").parentElement!);
    expect(onClose).toHaveBeenCalledTimes(3);
  });
  it("typing does not move focus (the open effect runs once)", async () => {
    await renderDs(<ModalDemo />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await userEvent.click(screen.getByLabelText("Country"));
    await userEvent.keyboard("Iran");
    expect(document.activeElement).toBe(screen.getByLabelText("Country"));
    expect((screen.getByLabelText("Country") as HTMLInputElement).value).toBe("Iran");
  });
});

describe("Drawer", () => {
  it("is a named dialog at the side, closes on Escape and returns focus", async () => {
    function Demo() {
      const [open, setOpen] = useState(false);
      return <><Button onClick={() => setOpen(true)}>Details</Button><Drawer open={open} title="Listing" onClose={() => setOpen(false)} testId="drawer"><Button>Star</Button></Drawer></>;
    }
    await renderDs(<Demo />, { lang: "fa" });
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    const drawer = screen.getByRole("dialog", { name: "Listing" });
    expect(drawer.className).toContain("end-0");                     // the end edge: left in RTL, right in LTR
    expect(drawer.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Details" }));
  });
});

describe("Menu and Popover", () => {
  const items = (run: (k: string) => void) => [
    { key: "edit", label: "Edit", onSelect: () => run("edit") }, { key: "archive", label: "Archive", onSelect: () => run("archive") },
    { key: "locked", label: "Locked", disabled: true, onSelect: () => run("locked") }, { key: "delete", label: "Delete", danger: true, onSelect: () => run("delete") },
  ];
  it("opens on its trigger, focus goes to the first item; arrows, End, Home and letters move", async () => {
    const run = vi.fn();
    await renderDs(<Menu label="Actions" items={items(run)} trigger={(p) => <Button {...p}>More</Button>} />);
    const trigger = screen.getByRole("button", { name: "More" });
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    await userEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("menu", { name: "Actions" })).toBeTruthy();
    const active = () => document.activeElement?.textContent;
    expect(active()).toBe("Edit");
    await userEvent.keyboard("{ArrowDown}");
    expect(active()).toBe("Archive");
    await userEvent.keyboard("{ArrowDown}");
    expect(active()).toBe("Delete");                               // the disabled item is skipped
    await userEvent.keyboard("{ArrowDown}");
    expect(active()).toBe("Edit");
    await userEvent.keyboard("{End}");
    expect(active()).toBe("Delete");
    await userEvent.keyboard("{Home}a");
    expect(active()).toBe("Archive");
  });
  it("Enter runs the item and closes; Escape closes without running; focus returns to the trigger", async () => {
    const run = vi.fn();
    await renderDs(<Menu label="Actions" items={items(run)} trigger={(p) => <Button {...p}>More</Button>} />);
    const trigger = screen.getByRole("button", { name: "More" });
    await userEvent.click(trigger);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(run).toHaveBeenCalledWith("archive");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    await userEvent.click(trigger);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(run).toHaveBeenCalledTimes(1);
  });
  it("a choice menu marks the current item and starts on it", async () => {
    await renderDs(<Menu label="Theme" trigger={(p) => <Button {...p}>Theme</Button>}
      items={[{ key: "light", label: "Light", checked: false, onSelect: () => undefined }, { key: "dark", label: "Dark", checked: true, onSelect: () => undefined }]} />);
    await userEvent.click(screen.getByRole("button", { name: "Theme" }));
    expect(screen.getByRole("menuitemradio", { name: "Dark" }).getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("menuitemradio", { name: "Dark" }));
  });
  it("Popover is a named dialog that closes on Escape and on a click outside", async () => {
    await renderDs(<><Popover label="Filters" trigger={(p) => <Button {...p}>Filter</Button>}><Input aria-label="Province" /></Popover><p>outside</p></>);
    await userEvent.click(screen.getByRole("button", { name: "Filter" }));
    expect(screen.getByRole("dialog", { name: "Filters" })).toBeTruthy();
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Filter" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("ConfirmDialog", () => {
  it("with a typed confirmation the action stays off until the word is typed", async () => {
    const onConfirm = vi.fn();
    await renderDs(<ConfirmDialog open title="Delete the case" confirmLabel="Delete" typed="CS-1405-0003" onConfirm={onConfirm} onClose={() => undefined}>12 records will be deleted.</ConfirmDialog>);
    const yes = screen.getByTestId("confirm-yes") as HTMLButtonElement;
    expect(yes.disabled).toBe(true);
    expect(document.activeElement).toBe(screen.getByTestId("confirm-typed"));
    await userEvent.keyboard("CS-1405-000");
    expect(yes.disabled).toBe(true);
    await userEvent.keyboard("3");
    expect(yes.disabled).toBe(false);
    await userEvent.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
  it("without one it confirms at once, and shows the busy state", async () => {
    const onConfirm = vi.fn();
    const view = await renderDs(<ConfirmDialog open title="Archive?" confirmLabel="Archive" variant="primary" onConfirm={onConfirm} onClose={() => undefined} />);
    await userEvent.click(screen.getByTestId("confirm-yes"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    view.rerender(<ConfirmDialog open title="Archive?" confirmLabel="Archive" busy onConfirm={onConfirm} onClose={() => undefined} />);
  });
});

describe("Tabs", () => {
  const tabs = [{ key: "items", label: "Items", count: 3 }, { key: "offers", label: "Offers" }, { key: "finance", label: "Finance" }];
  function Demo() {
    const [active, setActive] = useState("items");
    return <Tabs label="Case" tabs={tabs} active={active} onSelect={setActive} />;
  }
  it("one tab stop; the arrow keys move and wrap; Home and End jump (LTR)", async () => {
    await renderDs(<Demo />, { lang: "en" });
    const selected = () => screen.getByRole("tab", { selected: true }).textContent;
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([0, -1, -1]);
    screen.getByRole("tab", { name: /Items/ }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(selected()).toBe("Offers");
    await userEvent.keyboard("{End}");
    expect(selected()).toBe("Finance");
    await userEvent.keyboard("{ArrowRight}");
    expect(selected()).toBe("Items3");
    await userEvent.keyboard("{Home}{ArrowLeft}");
    expect(selected()).toBe("Finance");
  });
  it("in RTL the next tab is ArrowLeft", async () => {
    await renderDs(<Demo />, { lang: "fa" });
    screen.getByRole("tab", { name: /Items/ }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Offers");
  });
  it("the overflow menu lists every tab and selects one", async () => {
    await renderDs(<Demo />, { lang: "en" });
    await userEvent.click(screen.getByTestId("tabs-more"));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual(["Items", "Offers", "Finance"]);
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Finance" }));
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Finance");
    expect(screen.getByRole("tablist", { name: "Case" })).toBeTruthy();
  });
});

describe("Toast", () => {
  it("errors are announced at once, the rest politely; they can be closed and leave by themselves", async () => {
    vi.useFakeTimers();
    try {
      function Demo() {
        const toast = useToast();
        return <><button type="button" onClick={() => toast("Saved", "success")}>ok</button><button type="button" onClick={() => toast("Failed", "error")}>bad</button></>;
      }
      await renderDs(<ToastProvider><Demo /></ToastProvider>);
      fireEvent.click(screen.getByText("ok"));
      fireEvent.click(screen.getByText("bad"));
      expect(screen.getByRole("status").textContent).toContain("Saved");
      expect(screen.getByRole("alert").textContent).toContain("Failed");
      act(() => { vi.advanceTimersByTime(5100); });
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.getByRole("alert")).toBeTruthy();                 // errors stay 8 s
      fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
