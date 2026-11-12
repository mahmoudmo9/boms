/** The party page's finance block (v0.8.0): receivable / payable balances and overdue, the invoices, and the ratings
 * (average per criterion, count, the last 5 with links). */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Bdi, Card, EmptyState, ErrorState, Loading, Stat } from "../../design/components";
import { api } from "../../lib/api";
import { PAYMENT_TONE } from "../../lib/finance";
import { useFormat } from "../../lib/prefs";
import { Money } from "../sourcing/shared";

interface InvoiceRow { id: string; number: string | null; status: string; currency: string; total: string; payment_status: string; case_id: string; case_title: string | null; issue_date: string | null }
interface PartyFinanceData {
  receivable: Record<string, string>; receivable_overdue: Record<string, string>; payable: Record<string, string>; payable_overdue: Record<string, string>;
  sales_invoices: InvoiceRow[]; purchase_invoices: InvoiceRow[];
  ratings: { count: number; average: Record<string, number | null>; last: { id: string; case_id: string; case_title: string; role: string; note: string | null; [k: string]: unknown }[] };
}

function Balances({ label, values, tone }: { label: string; values: Record<string, string>; tone?: "danger" }) {
  const entries = Object.entries(values);
  return <Stat label={label} tone={tone && entries.length ? tone : undefined}
    value={entries.length ? <span className="flex flex-col">{entries.map(([cur, v]) => <Money key={cur} amount={v} currency={cur} />)}</span> : "—"} />;
}

export function PartyFinance({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const q = useQuery({ queryKey: ["party-finance", partyId], queryFn: () => api<PartyFinanceData>(`/api/parties/${partyId}/finance`) });
  if (q.isLoading) return <Loading />;
  if (!q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;
  const list = (rows: InvoiceRow[]) => rows.length === 0 ? <EmptyState>{t("finance.none")}</EmptyState> : (
    <ul className="max-h-72 divide-y divide-line overflow-y-auto">{rows.map((r) => (
      <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
        <bdi dir="ltr" className="font-mono">{r.number ?? "—"}</bdi>
        <Link className="text-accent hover:underline" to={`/cases/${r.case_id}?tab=finance`}><Bdi>{r.case_title ?? ""}</Bdi></Link>
        <Badge tone={PAYMENT_TONE[r.payment_status]}>{t(`finance.paymentStatus.${r.payment_status}`)}</Badge>
        <span className="ms-auto"><Money amount={r.total} currency={r.currency} /></span>
      </li>))}</ul>);
  return (
    <div className="flex flex-col gap-4" data-testid="party-finance">
      <Card><div className="grid gap-3 sm:grid-cols-4">
        <Balances label={t("finance.party.receivable")} values={d.receivable} />
        <Balances label={t("finance.party.receivableOverdue")} values={d.receivable_overdue} tone="danger" />
        <Balances label={t("finance.party.payable")} values={d.payable} />
        <Balances label={t("finance.party.payableOverdue")} values={d.payable_overdue} tone="danger" />
      </div></Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card padded={false} title={t("finance.ws.sales")}>{list(d.sales_invoices)}</Card>
        <Card padded={false} title={t("finance.ws.purchase")}>{list(d.purchase_invoices)}</Card>
      </div>
      <Card title={<span className="flex items-center gap-2">{t("finance.ratings.title")} <Badge>{f.num(d.ratings.count)}</Badge></span>}>
        <div className="flex flex-col gap-3" data-testid="party-ratings">
          <div className="flex flex-wrap gap-4 text-sm">{Object.entries(d.ratings.average).filter(([, v]) => v !== null).map(([k, v]) =>
            <span key={k}>{t(`finance.ratings.criteria.${k}`)}: <b className="tabular-nums">{f.num(String(v), 1)}</b></span>)}</div>
          <ul className="flex flex-col gap-1 text-sm">{d.ratings.last.map((r) => (
            <li key={r.id} className="flex flex-wrap gap-2"><Link className="text-accent hover:underline" to={`/cases/${r.case_id}?tab=finance`}><Bdi>{r.case_title}</Bdi></Link>
              <Badge>{t(`finance.ratings.roles.${r.role}`)}</Badge>{r.note && <span dir="auto" className="text-muted">{r.note}</span>}</li>))}</ul>
        </div>
      </Card>
    </div>
  );
}
