/** «مالی معاملات» (v0.8.0): receivables with aging, payables, invoices, payments, deals and VAT, with the CSV
 * exports for the accountant and «Export all for period» (zip). No general ledger. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Badge, Card, EmptyState, ErrorNote, Field, Loading, PageHeader, Select } from "../../components/ui";
import { api } from "../../lib/api";
import { AGING_BUCKETS, MOADIAN_TONE, PAYMENT_TONE } from "../../lib/finance";
import { toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import { Money } from "../sourcing/shared";

const TABS = ["receivables", "payables", "invoices", "payments", "deals", "vat"] as const;
type Tab = (typeof TABS)[number];
type Named = { name_fa: string | null; name_en: string | null } | null;
type Row = Record<string, unknown> & { id?: string; case_id?: string; currency?: string };

function useName() {
  const f = useFormat();
  return (p: Named | undefined) => ((f.lang === "fa" ? p?.name_fa || p?.name_en : p?.name_en || p?.name_fa) ?? "—");
}

function Table({ head, rows, testid }: { head: string[]; rows: React.ReactNode[][]; testid: string }) {
  const { t } = useTranslation();
  if (!rows.length) return <EmptyState>{t("finance.none")}</EmptyState>;
  return (
    <div className="max-h-[36rem] overflow-auto">
      <table className="w-full text-sm" data-testid={testid}>
        <thead className="sticky top-0 bg-surface text-xs text-muted"><tr>{head.map((h, i) => <th key={i} className="px-2 py-1.5 text-start">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="px-2 py-1.5">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function CaseLink({ row }: { row: Row }) {
  return row.case_id ? <Link className="text-accent hover:underline" to={`/cases/${row.case_id}?tab=finance`}><Bdi>{String(row.case_title ?? "—")}</Bdi></Link> : <span>—</span>;
}

function Receivables() {
  const { t } = useTranslation();
  const f = useFormat();
  const name = useName();
  const q = useQuery({ queryKey: ["fin", "receivables"], queryFn: () => api<{ invoices: Row[]; by_party: Row[]; advances: Row[] }>("/api/finance/receivables") });
  if (!q.data) return q.error ? <ErrorNote error={q.error} /> : <Loading />;
  return (
    <div className="flex flex-col gap-4">
      <Card padded={false} title={t("finance.ws.byCustomer")}>
        <Table testid="aging-by-party" head={[t("finance.ws.party"), t("finance.ws.currency"), ...AGING_BUCKETS.map((b) => t(`finance.ws.buckets.${b}`)), t("finance.ws.total")]}
          rows={q.data.by_party.map((r) => [name(r.party as Named), String(r.currency), ...AGING_BUCKETS.map((b) => <bdi dir="ltr" key={b} className="tabular-nums">{f.num(String(r[b]))}</bdi>),
            <bdi dir="ltr" key="t" className="tabular-nums font-medium">{f.num(String(r.total))}</bdi>])} />
      </Card>
      <Card padded={false} title={t("finance.ws.byInvoice")}>
        <Table testid="aging-invoices" head={[t("finance.ws.number"), t("finance.ws.party"), t("finance.ws.case"), t("finance.ws.due"), t("finance.ws.balance"), t("finance.ws.bucket")]}
          rows={q.data.invoices.map((r) => [<bdi dir="ltr" key="n">{String(r.number)}</bdi>, name(r.party as Named), <CaseLink key="c" row={r} />, f.day(String(r.due_date)),
            <Money key="b" amount={String(r.balance)} currency={r.currency} />, <Badge key="k" tone={r.overdue ? "danger" : "neutral"}>{t(`finance.ws.buckets.${String(r.bucket)}`)}</Badge>])} />
      </Card>
      <Card padded={false} title={t("finance.ws.advances")}>
        <Table testid="advances" head={[t("finance.ws.party"), t("finance.ws.date"), t("finance.ws.unallocated")]}
          rows={q.data.advances.map((r) => [name(r.party as Named), f.day(String(r.paid_on)), <Money key="u" amount={String(r.unallocated)} currency={r.currency} />])} />
      </Card>
    </div>
  );
}

function Payables() {
  const { t } = useTranslation();
  const f = useFormat();
  const name = useName();
  const q = useQuery({ queryKey: ["fin", "payables"], queryFn: () => api<{ items: Row[]; counts: Record<string, number> }>("/api/finance/payables") });
  if (!q.data) return q.error ? <ErrorNote error={q.error} /> : <Loading />;
  return (
    <Card padded={false} title={<span className="flex flex-wrap gap-2">{t("finance.ws.tabs.payables")}{(["overdue", "due_7", "due_30", "later"] as const).map((w) =>
      <Badge key={w} tone={w === "overdue" && q.data.counts[w] ? "danger" : "neutral"}>{t(`finance.ws.windows.${w}`)} {f.num(q.data.counts[w] ?? 0)}</Badge>)}</span>}>
      <Table testid="payables" head={[t("finance.ws.label"), t("finance.ws.party"), t("finance.ws.case"), t("finance.ws.due"), t("finance.ws.balance"), t("finance.ws.window")]}
        rows={q.data.items.map((r) => [<span key="l" dir="auto">{String(r.label)}</span>, name(r.party as Named), <CaseLink key="c" row={r} />, r.due_date ? f.day(String(r.due_date)) : "—",
          <Money key="b" amount={String(r.balance)} currency={r.currency} />, <Badge key="w" tone={r.window === "overdue" ? "danger" : r.window === "due_7" ? "warning" : "neutral"}>{t(`finance.ws.windows.${String(r.window)}`)}</Badge>])} />
    </Card>
  );
}

function Invoices({ from, to }: { from: string; to: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const name = useName();
  const [kind, setKind] = useState<"sales" | "purchase">("sales");
  const [status, setStatus] = useState("");
  const [moadian, setMoadian] = useState("");
  const q = useQuery({ queryKey: ["fin", "invoices", kind, status, moadian, from, to],
    queryFn: () => api<Row[]>("/api/finance/invoices", { query: { kind, status, moadian_status: kind === "sales" ? moadian : "", date_from: from, date_to: to } }) });
  return (
    <Card padded={false} title={<span className="flex flex-wrap items-center gap-2">
      <Select aria-label={t("finance.ws.kind")} className="w-48" value={kind} onChange={(e) => { setKind(e.target.value as "sales" | "purchase"); setStatus(""); }}>
        <option value="sales">{t("finance.ws.sales")}</option><option value="purchase">{t("finance.ws.purchase")}</option></Select>
      <Select aria-label={t("finance.ws.status")} className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t("finance.ws.allStatuses")}</option>
        {(kind === "sales" ? ["draft", "issued", "cancelled"] : ["received", "approved", "disputed", "cancelled"]).map((s) =>
          <option key={s} value={s}>{t(kind === "sales" ? `finance.invoices.statuses.${s}` : `finance.supplier.statuses.${s}`)}</option>)}</Select>
      {kind === "sales" && <Select aria-label={t("finance.moadian.status")} className="w-52" value={moadian} onChange={(e) => setMoadian(e.target.value)}><option value="">{t("finance.ws.allMoadian")}</option>
        {["not_required", "not_sent", "sent", "accepted", "rejected"].map((s) => <option key={s} value={s}>{t(`finance.moadian.statuses.${s}`)}</option>)}</Select>}
    </span>}>
      {q.data ? <Table testid="invoices-table" head={[t("finance.ws.number"), t("finance.ws.party"), t("finance.ws.case"), t("finance.ws.date"), t("finance.ws.total"), t("finance.ws.balance"), t("finance.ws.status")]}
        rows={q.data.map((r) => [<bdi key="n" dir="ltr">{String(r.number ?? "—")}</bdi>, name(r.party as Named), <CaseLink key="c" row={r} />, r.issue_date ? f.day(String(r.issue_date)) : "—",
          <Money key="t" amount={String(r.total)} currency={r.currency} />, r.balance != null ? <Money key="b" amount={String(r.balance)} currency={r.currency} /> : "—",
          <span key="s" className="flex flex-wrap gap-1"><Badge tone={PAYMENT_TONE[String(r.payment_status)]}>{t(`finance.paymentStatus.${String(r.payment_status)}`)}</Badge>
            {kind === "sales" && r.status === "issued" && <Badge tone={MOADIAN_TONE[String(r.moadian_status)]}>{t(`finance.moadian.statuses.${String(r.moadian_status)}`)}</Badge>}</span>])} />
        : <Loading />}
    </Card>
  );
}

function Payments({ from, to }: { from: string; to: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const name = useName();
  const q = useQuery({ queryKey: ["fin", "payments", from, to], queryFn: () => api<Row[]>("/api/finance/payments", { query: { date_from: from, date_to: to } }) });
  if (!q.data) return <Loading />;
  return (
    <Card padded={false} title={t("finance.ws.tabs.payments")}>
      <Table testid="payments-table" head={[t("finance.ws.date"), t("finance.ws.direction"), t("finance.ws.party"), t("finance.ws.case"), t("finance.amount"), t("finance.ws.base"), t("finance.ws.unallocated")]}
        rows={q.data.map((r) => [f.day(String(r.paid_on)), t(`finance.payments.direction.${String(r.direction)}`), name(r.party as Named), <CaseLink key="c" row={r} />,
          <Money key="a" amount={String(r.amount)} currency={String(r.amount_currency)} />,
          r.rate_missing ? <Badge key="r" tone="danger">{t("finance.payments.rateMissing")}</Badge> : <Money key="b" amount={r.base_amount as string | null} currency="IRR" />,
          Number(r.unallocated) > 0 ? <Money key="u" amount={String(r.unallocated)} currency={String(r.amount_currency)} /> : "—"])} />
    </Card>
  );
}

function Deals({ from, to }: { from: string; to: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [state, setState] = useState("");
  const q = useQuery({ queryKey: ["fin", "deals", state, from, to], queryFn: () => api<Row[]>("/api/finance/deals", { query: { state, date_from: from, date_to: to } }) });
  const pct = (v: unknown) => (v == null ? "—" : `${f.num(String(v))}%`);
  const amt = (b: unknown) => { const x = b as { actual?: { deal: string } } | null; return x?.actual ? f.num(x.actual.deal) : "—"; };
  return (
    <Card padded={false} title={<Select aria-label={t("finance.ws.state")} className="w-40" value={state} onChange={(e) => setState(e.target.value)}>
      <option value="">{t("finance.ws.allDeals")}</option><option value="open">{t("finance.ws.open")}</option><option value="closed">{t("finance.ws.closed")}</option></Select>}>
      {q.data ? <Table testid="deals-table" head={[t("finance.ws.case"), t("finance.ws.status"), t("finance.ws.currency"), t("finance.profit.lines.revenue"), t("finance.profit.lines.cost_total"),
        t("finance.profit.lines.profit"), t("finance.ws.marginPlanned"), t("finance.ws.marginActual")]}
        rows={q.data.map((r) => [<Link key="c" className="text-accent hover:underline" to={`/cases/${r.case_id}?tab=finance`}><Bdi>{String(r.title)}</Bdi></Link>,
          <Badge key="s" tone={r.status === "closed" ? "neutral" : "accent"}>{t(`sourcing.status.case.${String(r.status)}`)}</Badge>, String(r.deal_currency),
          <bdi key="r" dir="ltr">{amt(r.revenue)}</bdi>, <bdi key="k" dir="ltr">{amt(r.cost)}</bdi>, <bdi key="p" dir="ltr">{amt(r.profit)}</bdi>,
          pct((r.margin_percent as { planned: unknown }).planned), pct((r.margin_percent as { actual: unknown }).actual)])} /> : <Loading />}
    </Card>
  );
}

function Vat({ from, to }: { from: string; to: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const q = useQuery({ queryKey: ["fin", "vat", from, to], queryFn: () => api<{ currency: string; periods: Row[] }>("/api/finance/vat", { query: { date_from: from, date_to: to } }) });
  if (!q.data) return <Loading />;
  return (
    <Card padded={false} title={`${t("finance.ws.tabs.vat")} (${q.data.currency}) — ${t("finance.ws.infoOnly")}`}>
      <Table testid="vat-table" head={[t("finance.ws.period"), t("finance.vat.output"), t("finance.vat.input"), t("finance.vat.net")]}
        rows={q.data.periods.map((p) => [<bdi key="p" dir="ltr">{String(p.period)}</bdi>, f.num(String(p.output)), f.num(String(p.input)), f.num(String(p.net))])} />
    </Card>
  );
}

const EXPORTS = ["sales_invoices", "purchase_invoices", "payments", "actual_costs", "deals", "receivables"] as const;

export function FinancePage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "receivables") as Tab;
  const [from, setFrom] = useState<Date | null>(null);
  const [to, setTo] = useState<Date | null>(null);
  const range = { from: from ? toDateString(from) : "", to: to ? toDateString(to) : "" };
  const qs = new URLSearchParams(Object.entries({ date_from: range.from, date_to: range.to }).filter(([, v]) => v)).toString();
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("nav.finance")} subtitle={t("finance.ws.subtitle")} />
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("finance.ws.from")} htmlFor="fin-from"><DateInput id="fin-from" value={from} onChange={setFrom} /></Field>
        <Field label={t("finance.ws.to")} htmlFor="fin-to"><DateInput id="fin-to" value={to} onChange={setTo} /></Field>
        <span className="flex flex-wrap items-center gap-1.5" data-testid="exports">
          {EXPORTS.map((e) => <a key={e} className="inline-flex h-8 items-center rounded-md border border-line-strong px-2.5 text-sm hover:bg-surface-2"
            href={`/api/finance/exports/${e}.csv${qs ? `?${qs}` : ""}`} download>{t(`finance.ws.exports.${e}`)}</a>)}
          <a className="inline-flex h-8 items-center rounded-md bg-accent-bright px-3 text-sm text-accent-fg hover:brightness-105" data-testid="export-all"
            href={`/api/finance/exports/all.zip${qs ? `?${qs}` : ""}`} download>{t("finance.ws.exportAll")}</a>
        </span>
      </div>
      <div className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((key) => (
          <button key={key} type="button" onClick={() => setParams({ tab: key }, { replace: true })} data-testid={`fin-tab-${key}`}
            className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${key === tab ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
            {t(`finance.ws.tabs.${key}`)}</button>))}
      </div>
      {tab === "receivables" && <Receivables />}
      {tab === "payables" && <Payables />}
      {tab === "invoices" && <Invoices {...range} />}
      {tab === "payments" && <Payments {...range} />}
      {tab === "deals" && <Deals {...range} />}
      {tab === "vat" && <Vat {...range} />}
    </div>
  );
}
