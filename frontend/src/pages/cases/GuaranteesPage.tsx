/** Guarantees across cases (v0.6.0): filters on status, purpose and "expiring within N days". */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { Badge, Bdi, Card, EmptyState, ErrorNote, Input, Loading, PageHeader, Select } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { GuaranteeRow } from "../../lib/types";
import { Money } from "../sourcing/shared";

const STATUSES = ["to_request", "requested", "issued", "ready_to_upload", "submitted", "extended", "released", "claimed", "cancelled"];
const PURPOSES = ["bid", "performance", "advance_payment", "retention", "other"];

export function GuaranteesPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const purpose = params.get("purpose") ?? "";
  const within = params.get("within") ?? "";
  const query: Record<string, string> = {};
  if (status) query.status = status;
  if (purpose) query.purpose = purpose;
  if (within) query.expiring_within = within;
  const list = useQuery({ queryKey: ["guarantees", query], queryFn: () => api<GuaranteeRow[]>("/api/guarantees", { query }) });
  const set = (key: string, value: string) => { const p = new URLSearchParams(params); if (value) p.set(key, value); else p.delete(key); setParams(p, { replace: true }); };
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("nav.sub.guarantees")} subtitle={t("tenders.guarantee.listSubtitle")} />
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label={t("tenders.guarantee.status")} className="w-auto" value={status} onChange={(e) => set("status", e.target.value)}>
          <option value="">{t("tenders.guarantee.allStatuses")}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`tenders.guarantee.statuses.${s}`)}</option>)}</Select>
        <Select aria-label={t("tenders.guarantee.purpose")} className="w-auto" value={purpose} onChange={(e) => set("purpose", e.target.value)}>
          <option value="">{t("tenders.guarantee.allPurposes")}</option>{PURPOSES.map((s) => <option key={s} value={s}>{t(`tenders.guarantee.purposes.${s}`)}</option>)}</Select>
        <Input dir="ltr" inputMode="numeric" className="w-48" aria-label={t("tenders.guarantee.expiringWithin")} placeholder={t("tenders.guarantee.expiringWithin")}
          value={within} onChange={(e) => set("within", e.target.value.replace(/\D/g, ""))} />
      </div>
      <Card padded={false}>
        {list.isLoading ? <Loading /> : <ErrorNote error={list.error} />}
        {list.data && (list.data.length === 0 ? <EmptyState>{t("tenders.guarantee.none")}</EmptyState> : (
          <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="guarantee-list">
            <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
              {["case", "purpose", "status", "amount", "bank", "number", "validUntil", "beneficiary"].map((h) => <th key={h} className="p-2 text-start whitespace-nowrap">{t(`tenders.guarantee.cols.${h}`)}</th>)}</tr></thead>
            <tbody>{list.data.map((g) => (
              <tr key={g.id} className="border-b border-line">
                <td className="p-2"><Link className="text-accent hover:underline" to={`/cases/${g.case_id}?tab=tender`} dir="auto">{g.case_title}</Link>{g.tender_no && <Bdi ltr className="ms-1 text-xs text-muted">{g.tender_no}</Bdi>}</td>
                <td className="p-2 whitespace-nowrap">{t(`tenders.guarantee.purposes.${g.purpose}`)}</td>
                <td className="p-2"><Badge>{t(`tenders.guarantee.statuses.${g.status}`)}</Badge></td>
                <td className="p-2"><Money amount={g.amount} currency={g.amount_currency} /></td>
                <td className="p-2" dir="auto">{g.bank_name}</td><td className="p-2"><Bdi ltr className="font-mono text-xs">{g.number}</Bdi></td>
                <td className="p-2 whitespace-nowrap tabular-nums">{g.valid_until ? f.day(g.valid_until) : "—"}</td><td className="min-w-40 p-2" dir="auto">{g.beneficiary_name}</td>
              </tr>))}</tbody></table></div>
        ))}
      </Card>
    </div>
  );
}
