import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { Icon } from "../../components/Icon";
import { Button, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { CaseDetail } from "../../lib/types";
import { PartyName } from "../parties/shared";
import { ItemsCard } from "../sourcing/ItemsEditor";
import { AttachedDocuments, CascadeDeleteCard, CurrencySelect, HistoryCard, Money, StatusBadge, useInvalidateSourcing, usePaymentTerms } from "../sourcing/shared";
import { CASE_STATUSES } from "./CasesPage";
import { ComparisonTab, CoverageCard, OffersTab } from "./Offers";
import { RfqsTab } from "./Rfqs";

const TABS = ["items", "rfqs", "offers", "comparison", "documents", "history"] as const;
type Tab = (typeof TABS)[number];

function EditCaseDialog({ c, onClose, onSaved }: { c: CaseDetail; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const terms = usePaymentTerms();
  const [form, setForm] = useState({ title: c.title, payment_term: c.payment_term, ordering_before_payment_reason: c.ordering_before_payment_reason,
    exposure_estimate: c.exposure_estimate, exposure_currency: c.exposure_currency, notes: c.notes });
  const term = terms.data?.find((x) => x.code === form.payment_term);
  const save = useMutation({ mutationFn: () => api(`/api/cases/${c.id}`, { method: "PATCH", body: form }), onSuccess: () => { onSaved(); onClose(); } });
  return (
    <Modal open title={t("sourcing.case.edit")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label={t("sourcing.case.title")} htmlFor="ec-title"><Input id="ec-title" dir="auto" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label={t("sourcing.decision.paymentTerm")} htmlFor="ec-term">
          <Select id="ec-term" value={form.payment_term ?? ""} onChange={(e) => setForm({ ...form, payment_term: e.target.value || null })}>
            <option value="">—</option>
            {(terms.data ?? []).map((x) => <option key={x.code} value={x.code}>{f.lang === "fa" ? x.label_fa : x.label_en}</option>)}
          </Select>
        </Field>
        {term?.requires_reason && <Field label={t("sourcing.decision.obpReason")} htmlFor="ec-obp"><Input id="ec-obp" dir="auto" value={form.ordering_before_payment_reason ?? ""} onChange={(e) => setForm({ ...form, ordering_before_payment_reason: e.target.value || null })} /></Field>}
        <Field label={t("sourcing.decision.exposure")} htmlFor="ec-exp" hint={t("sourcing.decision.exposureHint")}>
          <div className="flex gap-1.5"><Input id="ec-exp" dir="ltr" inputMode="decimal" value={form.exposure_estimate ?? ""} onChange={(e) => setForm({ ...form, exposure_estimate: e.target.value || null })} />
            <CurrencySelect value={form.exposure_currency} onChange={(v) => setForm({ ...form, exposure_currency: v })} /></div>
        </Field>
        <Field label={t("parties.notes")} htmlFor="ec-notes"><Textarea id="ec-notes" dir="auto" rows={3} value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value || null })} /></Field>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

export function CaseDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const f = useFormat();
  const invalidate = useInvalidateSourcing();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "items") as Tab;
  const caseQuery = useQuery({ queryKey: ["case", id], queryFn: () => api<CaseDetail>(`/api/cases/${id}`) });
  const refresh = () => { void caseQuery.refetch(); invalidate(); };
  const setStatus = useMutation({ mutationFn: (status: string) => api(`/api/cases/${id}`, { method: "PATCH", body: { status } }), onSuccess: refresh });
  const highlightItem = params.get("item");
  useEffect(() => {
    if (tab === "items" && highlightItem) document.getElementById(`item-${highlightItem}`)?.scrollIntoView({ block: "center" });
  }, [tab, highlightItem, caseQuery.data]);
  if (caseQuery.isLoading) return <Loading />;
  if (caseQuery.error || !caseQuery.data) return <ErrorNote error={caseQuery.error} />;
  const c = caseQuery.data;
  return (
    <div className="flex flex-col gap-4">
      <Link to="/cases" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><Icon name="chevronStart" size={15} /> {t("nav.cases")}</Link>
      <PageHeader title={<span dir="auto">{c.title}</span>}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          <StatusBadge group="case" status={c.status} />
          {c.party_id && <PartyName fa={c.party_name_fa ?? null} en={c.party_name_en ?? null} id={c.party_id} />}
          {c.inquiry_id && <Link to={`/sourcing/inquiries/${c.inquiry_id}`} className="text-accent hover:underline">{t("sourcing.case.fromInquiry")}</Link>}
          {c.payment_term && <span>{t(`sourcing.paymentTerms.${c.payment_term}`)}</span>}
          {c.exposure_estimate && <span>{t("sourcing.decision.exposure")}: <Money amount={c.exposure_estimate} currency={c.exposure_currency} /></span>}
          <span className="tabular-nums">{f.date(c.created_at)}</span>
        </span>}
        actions={<>
          <Select className="w-36" aria-label={t("sourcing.status.label")} value={c.status} onChange={(e) => setStatus.mutate(e.target.value)}>
            {CASE_STATUSES.map((s) => <option key={s} value={s}>{t(`sourcing.status.case.${s}`)}</option>)}
          </Select>
          <Button icon="edit" onClick={() => setEditing(true)}>{t("common.edit")}</Button>
        </>} />
      <ErrorNote error={setStatus.error} />
      <div className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((key) => (
          <button key={key} type="button" onClick={() => setParams({ tab: key }, { replace: true })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${key === tab ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
            {t(`sourcing.case.tabs.${key}`)}
            {key === "items" && ` (${f.num(c.items.filter((i) => i.status !== "cancelled").length)})`}
          </button>
        ))}
      </div>
      {tab === "items" && (
        <div className="flex flex-col gap-4">
          <CoverageCard key={c.updated_at + c.items.map((i) => i.status).join()} caseId={c.id} onChanged={refresh} />
          <ItemsCard owner={{ case_id: c.id }} items={c.items} warnings={c.warnings} ownerDocuments={c.documents} onChanged={refresh} inCase />
        </div>
      )}
      {tab === "rfqs" && <RfqsTab caseData={c} highlight={params.get("rfq")} />}
      {tab === "offers" && <OffersTab caseData={c} highlight={params.get("offer")} />}
      {tab === "comparison" && <ComparisonTab caseData={c} />}
      {tab === "documents" && <AttachedDocuments documents={c.documents} linkPath={`/api/cases/${c.id}/documents`} onChanged={refresh} />}
      {tab === "history" && <>
        <HistoryCard entityType="case" entityId={c.id} />
        <CascadeDeleteCard url={`/api/cases/${c.id}`} confirmKey="confirm_title" expected={c.title}
          hint={t("sourcing.case.cascadeHint")} typeLabel={t("sourcing.case.typeTitle")} button={t("sourcing.case.cascadeButton")}
          onDeleted={() => { invalidate(); navigate("/cases"); }} />
      </>}
      {editing && <EditCaseDialog c={c} onClose={() => setEditing(false)} onSaved={refresh} />}
    </div>
  );
}
