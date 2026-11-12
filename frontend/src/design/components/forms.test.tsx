// @vitest-environment jsdom
/** v0.10.0 form controls: labels and errors wired for screen readers, keyboard behaviour, both calendars and both
 * directions, money and quantity as pairs, the file drop. */
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox, Combobox, DatePicker, Field, FileDrop, Input, MoneyInput, QuantityInput, RadioGroup, Segmented, Select, SourceChip, Switch, Textarea } from ".";
import { renderDs } from "./testing";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
afterEach(cleanup);

describe("Field", () => {
  it("names the control, wires the hint, and shows the source chip", async () => {
    await renderDs(<Field label="Currency" htmlFor="cur" hint="ISO 4217" source={<SourceChip>from PO-1405-0007</SourceChip>}><Input id="cur" /></Field>);
    const input = screen.getByLabelText("Currency");
    expect(document.getElementById(input.getAttribute("aria-describedby")!)!.textContent).toBe("ISO 4217");
    expect(screen.getByText("from PO-1405-0007")).toBeTruthy();
    expect(input.getAttribute("aria-invalid")).toBeNull();
  });
  it("an error replaces the hint, is announced and marks the control invalid and required", async () => {
    await renderDs(<Field label="IBAN" htmlFor="iban" hint="26 characters" error="Check digit is wrong" required><Input id="iban" /></Field>);
    const input = screen.getByLabelText(/IBAN/);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-required")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Check digit is wrong");
    expect(document.getElementById(input.getAttribute("aria-describedby")!)).toBe(screen.getByRole("alert"));
    expect(screen.queryByText("26 characters")).toBeNull();
  });
});

describe("Input, Textarea, Select", () => {
  it("fill the row unless a width is given; disabled controls cannot be typed in", async () => {
    await renderDs(<><Input aria-label="a" /><Input aria-label="b" className="w-36" /><Textarea aria-label="c" disabled /></>);
    expect(screen.getByLabelText("a").className).toContain("w-full");
    expect(screen.getByLabelText("b").className).not.toContain("w-full");
    await userEvent.type(screen.getByLabelText("c"), "x");
    expect((screen.getByLabelText("c") as HTMLTextAreaElement).value).toBe("");
  });
  it("Select is the native control with the chosen width on its frame", async () => {
    const onChange = vi.fn();
    await renderDs(<Select aria-label="Route" className="w-44" defaultValue="foreign" onChange={(e) => onChange(e.target.value)}><option value="domestic">Domestic</option><option value="foreign">Foreign</option></Select>);
    const select = screen.getByRole("combobox", { name: "Route" });
    expect(select.parentElement!.className).toContain("w-44");
    await userEvent.selectOptions(select, "domestic");
    expect(onChange).toHaveBeenCalledWith("domestic");
  });
});

describe("Checkbox, RadioGroup, Switch, Segmented", () => {
  it("Checkbox and Switch toggle with the mouse and the keyboard", async () => {
    function Demo() {
      const [a, setA] = useState(false); const [b, setB] = useState(false);
      return <><Checkbox label="Local only" checked={a} onChange={setA} /><Switch label="Compact" checked={b} onChange={setB} /></>;
    }
    await renderDs(<Demo />);
    const box = screen.getByRole("checkbox", { name: "Local only" }), sw = screen.getByRole("switch", { name: "Compact" });
    await userEvent.click(box);
    expect((box as HTMLInputElement).checked).toBe(true);
    sw.focus();
    await userEvent.keyboard(" ");
    expect(sw.getAttribute("aria-checked")).toBe("true");
    await userEvent.keyboard("{Enter}");
    expect(sw.getAttribute("aria-checked")).toBe("false");
  });
  it("RadioGroup is a named group with one choice", async () => {
    const onChange = vi.fn();
    await renderDs(<RadioGroup label="Calendar" value="jalali" onChange={onChange} options={[{ value: "jalali", label: "Jalali" }, { value: "gregorian", label: "Gregorian" }]} />);
    expect(within(screen.getByRole("radiogroup", { name: "Calendar" })).getAllByRole("radio")).toHaveLength(2);
    await userEvent.click(screen.getByRole("radio", { name: "Gregorian" }));
    expect(onChange).toHaveBeenCalledWith("gregorian");
  });
  function Seg() {
    const [v, setV] = useState<"light" | "dark" | "system">("light");
    return <Segmented label="Theme" value={v} onChange={setV} options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "system", label: "System" }]} />;
  }
  it("Segmented: one tab stop, the arrow keys move the choice and wrap (LTR)", async () => {
    await renderDs(<Seg />, { lang: "en" });
    const radios = () => screen.getAllByRole("radio").map((r) => [r.getAttribute("aria-checked"), r.tabIndex]);
    expect(radios()).toEqual([["true", 0], ["false", -1], ["false", -1]]);
    screen.getByRole("radio", { name: "Light" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Dark" }).getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Dark" }));
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "System" }).getAttribute("aria-checked")).toBe("true");
  });
  it("Segmented: in RTL the next choice is ArrowLeft", async () => {
    await renderDs(<Seg />, { lang: "fa" });
    screen.getByRole("radio", { name: "Light" }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "Dark" }).getAttribute("aria-checked")).toBe("true");
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Light" }).getAttribute("aria-checked")).toBe("true");
  });
});

const CURRENCIES = [{ value: "USD", label: "US dollar", code: "USD" }, { value: "EUR", label: "Euro", code: "EUR" }, { value: "AED", label: "UAE dirham", code: "AED" }, { value: "IRR", label: "Iranian rial", code: "IRR" }];

describe("Combobox", () => {
  function Demo({ onPicked }: { onPicked?: (v: string | null) => void }) {
    const [v, setV] = useState<string | null>("USD");
    return <Combobox ariaLabel="Currency" options={CURRENCIES} value={v} onChange={(x) => { setV(x); onPicked?.(x); }} />;
  }
  it("shows the chosen option as «name (code)» and filters by name or code, exact code first", async () => {
    await renderDs(<Demo />);
    const input = screen.getByRole("combobox", { name: "Currency" }) as HTMLInputElement;
    expect(input.value).toBe("US dollar (USD)");
    await userEvent.click(input);
    await userEvent.keyboard("ir");
    const options = () => screen.getAllByRole("option").map((o) => o.textContent);
    expect(options()[0]).toContain("Iranian rial");                  // name prefix and code prefix
    expect(options().some((o) => o!.includes("UAE dirham"))).toBe(true);          // contains «ir»
    expect(options().some((o) => o!.includes("Euro"))).toBe(false);
  });
  it("keyboard: arrows move the active option, Enter chooses, Escape closes and keeps the value", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} />);
    const input = screen.getByRole("combobox", { name: "Currency" }) as HTMLInputElement;
    input.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(input.getAttribute("aria-expanded")).toBe("true");
    await userEvent.keyboard("{ArrowDown}");
    expect(document.getElementById(input.getAttribute("aria-activedescendant")!)!.textContent).toContain("Euro");
    await userEvent.keyboard("{Enter}");
    expect(picked).toHaveBeenCalledWith("EUR");
    expect(input.value).toBe("Euro (EUR)");
    expect(input.getAttribute("aria-expanded")).toBe("false");
    await userEvent.keyboard("xyz{Escape}");
    expect(input.value).toBe("Euro (EUR)");
    expect(screen.queryByRole("listbox")).toBeNull();
  });
  it("says when nothing matches and can be cleared", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} />);
    const input = screen.getByRole("combobox", { name: "Currency" });
    await userEvent.click(input);
    await userEvent.keyboard("zzz");
    expect(screen.getByRole("listbox").textContent).toBe("No match");
    fireEvent.mouseDown(screen.getByRole("button", { name: "Clear" }));
    expect(picked).toHaveBeenCalledWith(null);
  });
});

describe("DatePicker", () => {
  function Demo({ onPicked, initial = null }: { onPicked?: (d: Date | null) => void; initial?: Date | null }) {
    const [d, setD] = useState<Date | null>(initial);
    return <DatePicker ariaLabel="Due" value={d} onChange={(x) => { setD(x); onPicked?.(x); }} />;
  }
  const ymd = (d: Date | null) => (d ? [d.getFullYear(), d.getMonth() + 1, d.getDate()] : null);
  it("Gregorian: a typed date is parsed on blur; a wrong one is marked invalid", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} />, { lang: "en", calendar: "gregorian" });
    const input = screen.getByRole("textbox", { name: "Due" });
    expect(input.getAttribute("placeholder")).toBe("e.g. 2026/10/24");
    await userEvent.type(input, "2026-11-12");
    await userEvent.tab();
    expect(ymd(picked.mock.calls[0][0])).toEqual([2026, 11, 12]);
    await userEvent.clear(input);
    await userEvent.type(input, "2026/13/40");
    await userEvent.tab();
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(picked).toHaveBeenCalledTimes(1);
  });
  it("Jalali: typed in Persian digits, shown in the Jalali calendar, the grid starts on Saturday", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} />, { lang: "fa", calendar: "jalali" });
    const input = screen.getByRole("textbox", { name: "Due" }) as HTMLInputElement;
    await userEvent.type(input, "۱۴۰۵/۸/۲۱");
    await userEvent.tab();
    expect(ymd(picked.mock.calls[0][0])).toEqual([2026, 11, 12]);
    expect(input.value).toBe("۱۴۰۵/۰۸/۲۱");
    await userEvent.click(screen.getByRole("button", { name: "باز کردن تقویم" }));
    const dialog = screen.getByRole("dialog", { name: "انتخاب تاریخ" });
    expect(dialog.getAttribute("data-calendar")).toBe("jalali");
    expect(screen.getByTestId("date-month").textContent).toBe("آبان ۱۴۰۵");
    expect(within(dialog).getAllByRole("columnheader")[0].getAttribute("aria-label")).toBe("شنبه");
    expect(within(dialog).getByRole("gridcell", { selected: true }).textContent).toBe("۲۱");
  });
  it("the grid is walked with the arrow keys (logical in RTL) and Enter chooses; Escape closes", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} initial={new Date(2026, 10, 12)} />, { lang: "fa", calendar: "jalali" });
    await userEvent.click(screen.getByRole("button", { name: "باز کردن تقویم" }));
    const focused = () => (document.activeElement as HTMLElement).textContent;
    expect(focused()).toBe("۲۱");
    await userEvent.keyboard("{ArrowLeft}");                      // next day in RTL
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    expect(focused()).toBe("۲۲");
    await userEvent.keyboard("{ArrowDown}");
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    expect(focused()).toBe("۲۹");
    await userEvent.keyboard("{Enter}");
    expect(ymd(picked.mock.calls[0][0])).toEqual([2026, 11, 20]);
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "باز کردن تقویم" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Due" }));
  });
  it("Gregorian grid: month names, Monday first, next month, today and clear", async () => {
    const picked = vi.fn();
    await renderDs(<Demo onPicked={picked} initial={new Date(2026, 10, 12)} />, { lang: "en", calendar: "gregorian" });
    await userEvent.click(screen.getByRole("button", { name: "Open the calendar" }));
    expect(screen.getByTestId("date-month").textContent).toBe("November 2026");
    expect(screen.getAllByRole("columnheader")[0].getAttribute("aria-label")).toBe("Monday");
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByTestId("date-month").textContent).toBe("December 2026");
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(picked).toHaveBeenLastCalledWith(null);
  });
});

describe("MoneyInput and QuantityInput", () => {
  it("money is an amount with its ISO currency, written left to right", async () => {
    const onChange = vi.fn();
    function Demo() {
      const [v, setV] = useState<{ amount: string | null; currency: string | null }>({ amount: null, currency: "USD" });
      return <MoneyInput amount={v.amount} currency={v.currency} currencies={CURRENCIES} onChange={(x) => { setV(x); onChange(x); }} />;
    }
    await renderDs(<Demo />, { lang: "fa" });
    const amount = screen.getByRole("textbox", { name: "مبلغ" });
    expect(amount.getAttribute("dir")).toBe("ltr");
    expect(amount.parentElement!.getAttribute("dir")).toBe("ltr");
    await userEvent.type(amount, "1250.5");
    expect(onChange).toHaveBeenLastCalledWith({ amount: "1250.5", currency: "USD" });
    const currency = screen.getByRole("combobox", { name: "ارز" });
    await userEvent.click(currency);
    await userEvent.keyboard("eur{Enter}");
    expect(onChange).toHaveBeenLastCalledWith({ amount: "1250.5", currency: "EUR" });
  });
  it("a quantity is an amount with its unit", async () => {
    const onChange = vi.fn();
    await renderDs(<QuantityInput amount="4" unit={null} units={[{ value: "pc", label: "piece", code: "H87" }, { value: "kg", label: "kilogram", code: "KGM" }]} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Unit" }));
    await userEvent.keyboard("KGM{Enter}");
    expect(onChange).toHaveBeenCalledWith({ amount: "4", unit: "kg" });
  });
});

describe("FileDrop", () => {
  const file = new File(["x"], "rfq.pdf", { type: "application/pdf" });
  it("takes dropped files and chosen files, and shows the dragging state", async () => {
    const onFiles = vi.fn();
    await renderDs(<FileDrop onFiles={onFiles} testId="drop" hint="PDF, Excel" />);
    const zone = screen.getByTestId("drop");
    fireEvent.dragOver(zone);
    expect(zone.getAttribute("data-over")).toBe("true");
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onFiles).toHaveBeenCalledWith([file]);
    expect(zone.getAttribute("data-over")).toBeNull();
    await userEvent.upload(zone.querySelector("input[type=file]") as HTMLInputElement, file);
    expect(onFiles).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Drop files here/ })).toBeTruthy();
  });
  it("takes nothing while busy or disabled", async () => {
    const onFiles = vi.fn();
    await renderDs(<FileDrop onFiles={onFiles} testId="drop" busy />);
    fireEvent.drop(screen.getByTestId("drop"), { dataTransfer: { files: [file] } });
    expect(onFiles).not.toHaveBeenCalled();
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
  });
});
