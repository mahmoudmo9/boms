/** `/design`: the living catalogue of the design system (v0.10.0 section 2). Every component in its states, the two
 * themes side by side. Shown only in developer mode (Settings → System). Later versions build from this page.
 * The sample texts and numbers here are demonstration data, not application strings. */
import type { ColumnDef } from "@tanstack/react-table";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Bars, Button, Card, CashFlow, Checkbox, Chip, CodeChip, Combobox, ConfirmDialog, DataTable, DatedTimeline, DatePicker, DescriptionList, Drawer, EmptyState,
  ErrorState, Field, FileDrop, Icon, ICON_NAMES, IconButton, InlineAlert, Input, Kbd, KpiTile, Loading, Menu, Modal, MoneyInput, PageHeader, Pagination, Popover, ProfitBridge,
  ProgressBar, ProgressRing, QuantityInput, RadioGroup, RouteLine, Section, Segmented, Select, Skeleton, SourceChip, Sparkline, Spinner, Stat, Status, Stepper, Switch, Tabs,
  Textarea, TextLink, Timeline, Tooltip, useToast, ValidatedInput } from "../../design/components";
import tokensCss from "../../design/tokens.css?raw";
import { contrastTable, readTheme } from "../../design/tokens";

const DEV_KEY = "boms.dev";
export function devMode(): boolean {
  try { return localStorage.getItem(DEV_KEY) === "1"; } catch { return false; }
}
export function setDevMode(on: boolean): void {
  try { if (on) localStorage.setItem(DEV_KEY, "1"); else localStorage.removeItem(DEV_KEY); } catch { /* per-browser convenience only */ }
}

const CURRENCIES = ["USD", "EUR", "AED", "CNY", "IRR"].map((c) => ({ value: c, label: c, code: c }));
const UNITS = [{ value: "pc", label: "عدد / piece", code: "H87" }, { value: "kg", label: "کیلوگرم / kilogram", code: "KGM" }, { value: "set", label: "ست / set", code: "SET" }];
type Row = { id: string; code: string; title: string; buyer: string; left: string };
const ROWS: Row[] = [
  { id: "1", code: "…3972", title: "پمپ گریز از مرکز طبق تقاضای پیوست", buyer: "نفت و گاز پارس", left: "۱ روز ۲۱ ساعت" },
  { id: "2", code: "…4018", title: "شیر توپی فولادی ۴ اینچ", buyer: "پالایش نفت بندرعباس", left: "۹ ساعت" },
  { id: "3", code: "…3990", title: "Spare parts for centrifugal pump", buyer: "Maroon Petrochemical", left: "3 d 4 h" },
];
const COLUMNS: ColumnDef<Row, unknown>[] = [
  { id: "code", header: "شماره", cell: ({ row }) => <bdi dir="ltr" className="font-mono text-xs text-muted">{row.original.code}</bdi>, size: 90 },
  { id: "title", header: "عنوان", cell: ({ row }) => <bdi>{row.original.title}</bdi> },
  { id: "buyer", header: "خریدار", cell: ({ row }) => <bdi>{row.original.buyer}</bdi> },
  { id: "left", header: "مهلت", cell: ({ row }) => <span className="text-accent tabular-nums">{row.original.left}</span> },
];

/** One block of the catalogue, drawn once per theme. */
function Specimen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3" data-testid="specimen" data-title={title}>
      <h2 className="text-sm font-semibold text-title">{title}</h2>
      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
        {(["light", "dark"] as const).map((theme) => (
          <div key={theme} data-theme-pane={theme} className={`theme-${theme} flex min-w-0 flex-col gap-4 rounded-2xl border border-line bg-bg p-5 text-fg`}>{children}</div>
        ))}
      </div>
    </section>
  );
}
const Line = ({ children }: { children: ReactNode }) => <div className="flex flex-wrap items-center gap-3">{children}</div>;

function Overlays() {
  const toast = useToast();
  const [modal, setModal] = useState(false), [drawer, setDrawer] = useState(false), [confirm, setConfirm] = useState(false);
  return (
    <Line>
      <Button onClick={() => setModal(true)}>Modal</Button>
      <Button onClick={() => setDrawer(true)}>Drawer</Button>
      <Button variant="danger" onClick={() => setConfirm(true)}>ConfirmDialog (typed)</Button>
      <Popover label="Filters" trigger={(p) => <Button icon="filter" {...p}>Popover</Button>}><Field label="استان" htmlFor="ds-prov"><Input id="ds-prov" /></Field></Popover>
      <Menu label="Actions" trigger={(p) => <Button iconEnd="chevronDown" {...p}>Menu</Button>}
        items={[{ key: "edit", label: "ویرایش", icon: "edit", onSelect: () => toast("ویرایش", "info") }, { key: "archive", label: "بایگانی", onSelect: () => toast("بایگانی شد", "success") },
          { key: "off", label: "غیرفعال", disabled: true, onSelect: () => undefined }, { key: "delete", label: "حذف", icon: "trash", danger: true, onSelect: () => toast("حذف نشد", "error") }]} />
      <Button onClick={() => toast("ذخیره شد", "success")}>Toast</Button>
      <Modal open={modal} wide title="طرف تجاری جدید" subtitle="Modal" onClose={() => setModal(false)}
        footer={<><Button onClick={() => setModal(false)}>انصراف</Button><Button variant="primary" onClick={() => setModal(false)}>ذخیره</Button></>}>
        <div className="grid gap-4 sm:grid-cols-2"><Field label="نام" htmlFor="ds-m1"><Input id="ds-m1" /></Field><Field label="کشور" htmlFor="ds-m2"><Input id="ds-m2" /></Field></div>
      </Modal>
      <Drawer open={drawer} title="جزئیات" onClose={() => setDrawer(false)}><p className="text-sm">Drawer / side panel</p></Drawer>
      <ConfirmDialog open={confirm} title="حذف پرونده" confirmLabel="حذف" typed="CS-1405-0003" onConfirm={() => setConfirm(false)} onClose={() => setConfirm(false)}>۱۲ رکورد حذف می‌شود.</ConfirmDialog>
    </Line>
  );
}

function Forms() {
  const [seg, setSeg] = useState<"light" | "dark" | "system">("dark");
  const [check, setCheck] = useState(true), [sw, setSw] = useState(true);
  const [radio, setRadio] = useState<"jalali" | "gregorian">("jalali");
  const [cur, setCur] = useState<string | null>("USD");
  const [date, setDate] = useState<Date | null>(new Date(2026, 10, 12));
  const [money, setMoney] = useState<{ amount: string | null; currency: string | null }>({ amount: "6250", currency: "USD" });
  const [qty, setQty] = useState<{ amount: string | null; unit: string | null }>({ amount: "4", unit: "pc" });
  const [iban, setIban] = useState("DE89 3704 0044 0532 0130 00");
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Input" htmlFor="ds-in" hint="راهنما زیر فیلد"><Input id="ds-in" placeholder="placeholder" /></Field>
      <Field label="Input (error)" htmlFor="ds-err" error="این مقدار درست نیست" required><Input id="ds-err" defaultValue="x" /></Field>
      <Field label="Input (disabled)" htmlFor="ds-dis"><Input id="ds-dis" disabled defaultValue="disabled" /></Field>
      <Field label="Select" htmlFor="ds-sel"><Select id="ds-sel" defaultValue="foreign"><option value="domestic">داخلی</option><option value="foreign">خارجی</option></Select></Field>
      <Field label="Combobox" htmlFor="ds-cb" source={<SourceChip>از PO-1405-0007</SourceChip>}><Combobox id="ds-cb" options={CURRENCIES} value={cur} onChange={setCur} dir="ltr" /></Field>
      <Field label="DatePicker" htmlFor="ds-date"><DatePicker id="ds-date" value={date} onChange={setDate} /></Field>
      <Field label="MoneyInput" htmlFor="ds-money"><MoneyInput id="ds-money" amount={money.amount} currency={money.currency} currencies={CURRENCIES} onChange={setMoney} /></Field>
      <Field label="QuantityInput" htmlFor="ds-qty"><QuantityInput id="ds-qty" amount={qty.amount} unit={qty.unit} units={UNITS} onChange={setQty} /></Field>
      <Field label="ValidatedInput (IBAN)" htmlFor="ds-iban"><ValidatedInput id="ds-iban" kind="iban" value={iban} onChange={setIban} /></Field>
      <Field label="Textarea" htmlFor="ds-ta"><Textarea id="ds-ta" rows={2} defaultValue="متن چندخطی" /></Field>
      <div className="flex flex-col gap-1">
        <Checkbox label="Checkbox" checked={check} onChange={setCheck} hint="با توضیح" />
        <Checkbox label="Checkbox (disabled)" checked={false} onChange={() => undefined} disabled />
        <Switch label="Switch · فشرده" checked={sw} onChange={setSw} />
      </div>
      <div className="flex flex-col gap-3">
        <RadioGroup label="Calendar" value={radio} onChange={setRadio} options={[{ value: "jalali", label: "شمسی" }, { value: "gregorian", label: "میلادی" }]} />
        <Segmented label="Theme" value={seg} onChange={setSeg} options={[{ value: "light", label: "روشن", icon: "sun" }, { value: "dark", label: "تیره", icon: "moon" }, { value: "system", label: "سیستم", icon: "monitor" }]} />
      </div>
      <div className="sm:col-span-2"><FileDrop onFiles={() => undefined} hint="PDF، Excel، تصویر" /></div>
    </div>
  );
}

export function DesignPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("items");
  const [page, setPage] = useState(1);
  const [active, setActive] = useState<string | null>("1");
  const [selected, setSelected] = useState(new Set<string>());
  const [dense, setDense] = useState(false);
  const table = contrastTable(tokensCss);
  const light = readTheme(tokensCss, "light"), dark = readTheme(tokensCss, "dark");
  const fmt = (n: number) => n.toLocaleString("en-US");
  return (
    <div className="flex flex-col gap-8" data-testid="design-page">
      <PageHeader title={t("design.title")} subtitle={t("design.subtitle")} breadcrumb={[{ label: t("nav.settings"), to: "/settings" }, { label: t("design.title") }]} code="DS-0.10.0" status={<Status tone="info">{t("design.devOnly")}</Status>} />

      <Specimen title="Colour tokens">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="swatches">
          {["bg", "surface", "surface-2", "surface-3", "sunken", "hover", "line", "line-strong", "control", "title", "fg", "fg-2", "muted", "faint", "accent", "accent-bright", "accent-soft", "accent-line",
            "success", "success-soft", "warning", "warning-soft", "danger", "danger-soft", "info", "info-soft", "chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "chart-6"].map((name) => (
            <div key={name} className="flex items-center gap-2 text-xs">
              <span className="size-7 shrink-0 rounded-md border border-line-strong" style={{ background: `var(--${name})` }} />
              <span className="flex min-w-0 flex-col"><bdi dir="ltr" className="truncate font-mono text-fg">{name}</bdi></span>
            </div>
          ))}
        </div>
      </Specimen>

      <Specimen title="Typography">
        <p className="font-display text-5xl font-semibold text-title">پمپ صنعتی و شیرآلات</p>
        <p className="font-display text-3xl font-semibold text-title">عنوان صفحه · Page title</p>
        <p className="text-4xl font-light text-title tabular-nums">۱٫۳ <span className="text-sm text-muted">میلیارد</span> · 1,875.00</p>
        {(["text-xl", "text-lg", "text-md", "text-base", "text-sm", "text-xs", "text-2xs"] as const).map((c) => <p key={c} className={c}><bdi dir="ltr" className="font-mono text-muted">{c}</bdi> — متن نمونه برای سنجش خوانایی Sample text 0123456789</p>)}
        <Line><CodeChip code="CS-1405-0003" /><CodeChip code="PO-1405-0007" copy={false} /><Kbd>Ctrl K</Kbd><TextLink href="#top">TextLink</TextLink></Line>
      </Specimen>

      <Specimen title="Buttons, badges, chips">
        <Line>{(["primary", "secondary", "ghost", "danger"] as const).map((v) => <Button key={v} variant={v} icon={v === "primary" ? "plus" : undefined}>{v}</Button>)}</Line>
        <Line><Button variant="primary" size="md">md</Button><Button variant="primary" size="lg">lg</Button><Button busy>loading</Button><Button disabled>disabled</Button><Button variant="primary" disabled>disabled</Button></Line>
        <Line><IconButton icon="star" label="Star" /><IconButton icon="star" label="Starred" active /><IconButton icon="edit" label="Edit" size="sm" /><Spinner /><Tooltip text="راهنمای کوتاه"><Button variant="ghost">Tooltip</Button></Tooltip></Line>
        <Line>{(["neutral", "success", "warning", "danger", "accent", "info"] as const).map((tone) => <Badge key={tone} tone={tone}>{tone}</Badge>)}</Line>
        <Line><Status tone="success">پرداخت شد</Status><Status tone="warning">در انتظار</Status><Status tone="danger">معوق</Status><Status tone="info">پیش‌نویس</Status></Line>
        <Line><Chip selected onClick={() => undefined}>کلیدواژه‌های من</Chip><Chip onClick={() => undefined}>ستاره‌دار</Chip><Chip onRemove={() => undefined} removeLabel="حذف">پمپ ۶</Chip></Line>
        <div className="grid grid-cols-8 gap-2 sm:grid-cols-12" data-testid="icons">{ICON_NAMES.map((n) => <span key={n} title={n} className="flex size-9 items-center justify-center rounded-md border border-line text-fg-2"><Icon name={n} /></span>)}</div>
      </Specimen>

      <Specimen title="Forms"><Forms /></Specimen>

      <Specimen title="Cards, tabs, overlays">
        <div className="grid gap-4 sm:grid-cols-3">
          <Card title="Card · plain" actions={<Button>کار</Button>}>متن کارت</Card>
          <Card kind="accent" eyebrow="قدم بعدی" title="ثبت اسناد حمل">Card · accent</Card>
          <Card kind="raised" title="Card · raised"><Section title="Section">گروه درون کارت</Section></Card>
        </div>
        <Tabs label="Case tabs" active={tab} onSelect={setTab} tabs={[{ key: "items", label: "اقلام", count: 3 }, { key: "offers", label: "پیشنهادها" }, { key: "costing", label: "بهای تمام‌شده" },
          { key: "orders", label: "سفارش" }, { key: "logistics", label: "لجستیک" }, { key: "finance", label: "مالی" }, { key: "documents", label: "اسناد" }]} />
        <Overlays />
      </Specimen>

      <Specimen title="DataTable">
        <Line><Switch label={t("ds.table.dense")} checked={dense} onChange={setDense} /></Line>
        <Card padded={false}>
          <DataTable label="Listings" columns={COLUMNS} data={ROWS} rowKey={(r) => r.id} dense={dense} maxHeight="max-h-72" activeKey={active} onRowActivate={(r) => setActive(r.id)}
            selected={selected} onSelectedChange={setSelected} sort={{ id: "title", desc: false }} onSortChange={() => undefined} sortable={["title"]} />
          <Pagination page={page} pageSize={3} total={9} onPage={setPage} />
        </Card>
        <div className="grid gap-4 sm:grid-cols-3">
          <Card padded={false} title="empty"><DataTable columns={COLUMNS} data={[]} rowKey={(r) => r.id} empty="هنوز فراخوانی نیست" emptyAction={<Button icon="refresh">برداشت</Button>} /></Card>
          <Card padded={false} title="loading"><DataTable columns={COLUMNS} data={[]} rowKey={(r) => r.id} loading /></Card>
          <Card padded={false} title="error"><DataTable columns={COLUMNS} data={[]} rowKey={(r) => r.id} error={{ code: "x" }} onRetry={() => undefined} /></Card>
        </div>
      </Specimen>

      <Specimen title="Timeline, stepper, KPI, progress">
        <Stepper label="Deal path" steps={[{ key: "1", label: "استعلام", state: "done" }, { key: "2", label: "پیشنهاد", state: "done" }, { key: "3", label: "سفارش", state: "done" },
          { key: "4", label: "حمل", state: "current", hint: "ETA ۱۹ آذر" }, { key: "5", label: "تحویل", state: "upcoming" }, { key: "6", label: "بستن", state: "upcoming" }]} />
        <div className="grid gap-5 sm:grid-cols-2">
          <Timeline label="Deal story" items={[{ key: "a", when: "۶ آبان", title: "فراخوان ستاد ستاره خورد", detail: "نفت و گاز پارس · ۳ قلم", state: "done" },
            { key: "b", when: "۱۰ آبان", title: "پیش‌فاکتور PI-0005 پذیرفته شد", state: "done" }, { key: "c", when: "۱۵ آبان", title: "محموله در راه", state: "current" },
            { key: "d", title: "ترخیص · حدود ۱۴ بهمن", state: "upcoming" }]} />
          <div className="flex flex-col gap-4">
            <DatedTimeline label="Tender dates" items={[{ key: "a", when: "۱۰ آبان", title: "انتشار", state: "done" }, { key: "b", when: "۱۹ آبان", title: "مهلت پیشنهاد", state: "current" }, { key: "c", when: "۲۵ آبان", title: "بازگشایی", state: "upcoming" }]} />
            <DescriptionList items={[{ label: "اینکوترمز", value: "CFR Bandar Abbas" }, { label: "ارز", value: "USD" }, { label: "یادداشت", value: "تحویل در دو پارت", wide: true }]} />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-4">
          <KpiTile label="سود این فصل" value="۱٫۳" unit="میلیارد" note="+۲۲٪ نسبت به فصل قبل" tone="accent"><Sparkline label="Profit" values={[4, 5, 5, 7, 6, 9, 10, 12]} /></KpiTile>
          <KpiTile label="نرخ برد پیشنهادها" value="۳۴٪" note="۱۱ از ۳۲ در ۶ ماه"><Bars label="Win rate" highlight="6" items={[1, 2, 3, 4, 5, 6].map((i) => ({ key: String(i), label: String(i), value: [3, 4, 2, 5, 4, 7][i - 1] }))} /></KpiTile>
          <KpiTile label="نقدینگی درگیر" value="۷۰٪" note="۴٫۲ از ۶ میلیارد" estimated><ProgressBar label="Exposure" value={70} /></KpiTile>
          <KpiTile label="ستاد امروز" value="۱۴" unit="مطابق کلیدواژه" emphasis><Line><Chip>پمپ ۶</Chip><Chip>شیر ۵</Chip></Line></KpiTile>
        </div>
        <Line>
          <ProgressRing label="Time left" value={78} size={96} stroke={7}><span className="text-xl font-light text-title">۵:۱۰</span><span className="text-2xs text-muted">ساعت مانده</span></ProgressRing>
          <ProgressRing label="Margin" value={19} tone="success"><span className="text-sm text-title">۱۹٪</span></ProgressRing>
          <div className="flex min-w-56 flex-1 flex-col gap-3"><ProgressBar label="Download" value={42} /><ProgressBar label="Working" />
            <ProgressBar label="Money" segments={[{ value: 1875, tone: "success", label: "دریافت" }, { value: 450, tone: "danger", label: "پرداخت" }, { value: 4375, tone: "neutral", label: "مانده" }]} /></div>
          <Stat label="حاشیه سود" value="۱۹٪" tone="success" /><Stat label="مانده" value="4,375 USD" />
        </Line>
      </Specimen>

      <Specimen title="Charts">
        <Card title="ProfitBridge"><ProfitBridge label="از برنامه تا واقعی" format={fmt} estimated={["costs"]} steps={[{ key: "plan", label: "برنامه", value: 1250, kind: "total" }, { key: "fx", label: "اثر نرخ ارز", value: 180, kind: "delta" },
          { key: "freight", label: "حمل", value: -140, kind: "delta" }, { key: "costs", label: "هزینه‌ها", value: -210, kind: "delta" }, { key: "actual", label: "واقعی", value: 1080, kind: "total" }]} /></Card>
        <Card title="CashFlow"><CashFlow label="جریان نقدی ۹۰ روز آینده" opening={900} format={fmt} points={[{ key: "1", label: "هفتهٔ ۱", cashIn: 400, cashOut: 0 }, { key: "2", label: "۲", cashIn: 0, cashOut: 700 },
          { key: "3", label: "۳", cashIn: 900, cashOut: 0 }, { key: "4", label: "۴", cashIn: 0, cashOut: 1200 }, { key: "5", label: "۵", cashIn: 0, cashOut: 500 }, { key: "6", label: "۶", cashIn: 1500, cashOut: 0 }, { key: "7", label: "۷", cashIn: 0, cashOut: 300 }, { key: "8", label: "۸", cashIn: 600, cashOut: 0 }]} /></Card>
        <Card title="RouteLine"><RouteLine label="مسیر محموله" rtl caption="از رویدادهای ثبت‌شده؛ موقعیت زندهٔ کشتی نیست."
          stops={[{ key: "a", name: "شانگهای", code: "CNSHA", when: "۲۰ آبان", state: "done" }, { key: "b", name: "کلمبو", code: "LKCMB", state: "done" }, { key: "c", name: "جبل‌علی", code: "AEJEA", when: "۴ آذر", state: "last" }, { key: "d", name: "بندرعباس", code: "IRBND", when: "۱۹ آذر", state: "upcoming" }]} /></Card>
      </Specimen>

      <Specimen title="States">
        <div className="grid gap-4 sm:grid-cols-3">
          <Card padded={false} title="loading"><Loading rows={3} /></Card>
          <Card padded={false} title="empty"><EmptyState compact title="هنوز پرونده‌ای نیست" action={<Button variant="primary" icon="plus">استعلام جدید</Button>}>با ثبت یک استعلام شروع کنید.</EmptyState></Card>
          <Card padded={false} title="error"><ErrorState compact error={{ code: "x" }} onRetry={() => undefined} /></Card>
        </div>
        <Skeleton lines={2} />
        {(["info", "success", "warning", "danger", "accent"] as const).map((tone) => <InlineAlert key={tone} tone={tone} title={`InlineAlert · ${tone}`}>یک یادداشت درون فرم یا کارت.</InlineAlert>)}
      </Specimen>

      <Card title={t("design.contrast")} subtitle={t("design.contrastHint")} padded={false}>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-xs" data-testid="contrast-table">
            <thead className="sticky top-0 bg-surface-2 text-muted"><tr>{["theme", "foreground", "background", "use", "ratio", "minimum", ""].map((h) => <th key={h} scope="col" className="px-3.5 py-2 text-start font-medium">{h}</th>)}</tr></thead>
            <tbody>{table.map((r) => (
              <tr key={`${r.theme}${r.fg}${r.bg}${r.kind}`} className="border-t border-line" data-pass={r.pass}>
                <td className="px-3.5 py-1.5">{r.theme}</td>
                <td className="px-3.5 py-1.5 font-mono" dir="ltr">{r.fg} {(r.theme === "dark" ? dark : light)[r.fg]}</td>
                <td className="px-3.5 py-1.5 font-mono" dir="ltr">{r.bg} {(r.theme === "dark" ? dark : light)[r.bg]}</td>
                <td className="px-3.5 py-1.5">{r.kind}</td><td className="px-3.5 py-1.5 tabular-nums">{r.ratio.toFixed(2)}</td><td className="px-3.5 py-1.5 tabular-nums">{r.min}</td>
                <td className="px-3.5 py-1.5">{r.pass ? <Status tone="success">AA</Status> : <Status tone="danger">fail</Status>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
