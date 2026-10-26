import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { Icon } from "../../components/Icon";
import { Badge, Button, Card, Checkbox, ErrorNote, Field, Input, Loading, Modal, PageHeader, Segmented, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Check, CaseDetail, Decision, InquiryDetail } from "../../lib/types";
import { PartyName } from "../parties/shared";
import { ItemsCard } from "./ItemsEditor";
import { AttachedDocuments, CascadeDeleteCard, CurrencySelect, HistoryCard, StatusBadge, useInvalidateSourcing, usePaymentTerms } from "./shared";

const CHECKS = ["feasible_sourcing", "exposure_acceptable", "requirements_ok"] as const;
const LIGHT_TONE = { green: "success", yellow: "warning", red: "danger" } as const;

type DecisionForm = Omit<Decision, "id" | "updated_at">;

function DecisionPanel({ inquiry, onSaved }: { inquiry: InquiryDetail; onSaved: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const terms = usePaymentTerms();
  const d = inquiry.decision;
  const [form, setForm] = useState<DecisionForm>({
    light: d?.light ?? "green", reason: d?.reason ?? "",
    feasible_sourcing: d?.feasible_sourcing ?? "unknown", feasible_sourcing_note: d?.feasible_sourcing_note ?? null,
    exposure_acceptable: d?.exposure_acceptable ?? "unknown", exposure_acceptable_note: d?.exposure_acceptable_note ?? null,
    requirements_ok: d?.requirements_ok ?? "unknown", requirements_ok_note: d?.requirements_ok_note ?? null,
    exposure_estimate: d?.exposure_estimate ?? null, exposure_currency: d?.exposure_currency ?? null,
    payment_term: d?.payment_term ?? null, ordering_before_payment_reason: d?.ordering_before_payment_reason ?? null,
    confirmed: d?.confirmed ?? false,
  });
  const set = (patch: Partial<DecisionForm>) => setForm((x) => ({ ...x, ...patch }));
  const term = terms.data?.find((x) => x.code === form.payment_term);
  const save = useMutation({
    mutationFn: () => api(`/api/inquiries/${inquiry.id}/decision`, { method: "PUT", body: form }),
    onSuccess: onSaved,
  });
  const closed = inquiry.status === "converted";
  const valid = form.reason.trim() && (!term?.requires_reason || (form.ordering_before_payment_reason ?? "").trim())
    && (!form.exposure_estimate || form.exposure_currency);
  return (
    <Card title={<span className="flex items-center gap-2">{t("sourcing.decision.title")}
      {d && <Badge tone={LIGHT_TONE[d.light]}>{t(`sourcing.decision.lights.${d.light}`)}</Badge>}</span>}>
      <fieldset disabled={closed} className="flex flex-col gap-3">
        <Field label={t("sourcing.decision.light")}>
          <Segmented value={form.light} label={t("sourcing.decision.light")} onChange={(v) => set({ light: v })}
            options={(["green", "yellow", "red"] as const).map((l) => ({ value: l, label: t(`sourcing.decision.lights.${l}`) }))} />
        </Field>
        <Field label={t("sourcing.decision.reason")} htmlFor="dc-reason"><Input id="dc-reason" dir="auto" value={form.reason} maxLength={2000} onChange={(e) => set({ reason: e.target.value })} /></Field>
        {CHECKS.map((c) => (
          <div key={c} className="rounded-md border border-line p-2.5">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{t(`sourcing.decision.checks.${c}`)}</span>
              <span className="ms-auto">
                <Segmented value={form[c]} label={t(`sourcing.decision.checks.${c}`)} onChange={(v: Check) => set({ [c]: v } as Partial<DecisionForm>)}
                  options={(["yes", "no", "unknown"] as const).map((v) => ({ value: v, label: t(`sourcing.decision.answers.${v}`) }))} />
              </span>
            </div>
            <p className="mb-1.5 text-xs text-muted">{t(`sourcing.decision.checkHints.${c}`)}</p>
            <Input dir="auto" aria-label={t("sourcing.decision.note")} placeholder={t("sourcing.decision.note")} value={form[`${c}_note`] ?? ""}
              onChange={(e) => set({ [`${c}_note`]: e.target.value || null } as Partial<DecisionForm>)} />
          </div>
        ))}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("sourcing.decision.exposure")} htmlFor="dc-exp" hint={t("sourcing.decision.exposureHint")}>
            <div className="flex gap-1.5"><Input id="dc-exp" dir="ltr" inputMode="decimal" value={form.exposure_estimate ?? ""} onChange={(e) => set({ exposure_estimate: e.target.value || null })} />
              <CurrencySelect value={form.exposure_currency} onChange={(v) => set({ exposure_currency: v })} /></div>
          </Field>
          <Field label={t("sourcing.decision.paymentTerm")} htmlFor="dc-term">
            <Select id="dc-term" value={form.payment_term ?? ""} onChange={(e) => set({ payment_term: e.target.value || null })}>
              <option value="">—</option>
              {(terms.data ?? []).map((x) => <option key={x.code} value={x.code}>{f.lang === "fa" ? x.label_fa : x.label_en}</option>)}
            </Select>
          </Field>
        </div>
        {term?.requires_reason && (
          <Field label={t("sourcing.decision.obpReason")} htmlFor="dc-obp" hint={t("sourcing.decision.obpHint")}>
            <Input id="dc-obp" dir="auto" value={form.ordering_before_payment_reason ?? ""} onChange={(e) => set({ ordering_before_payment_reason: e.target.value || null })} />
          </Field>
        )}
        {form.light === "yellow" && <Checkbox label={t("sourcing.decision.confirmYellow")} checked={form.confirmed} onChange={(v) => set({ confirmed: v })} />}
        {form.light === "red" && <p className="text-sm text-danger">{t("sourcing.decision.redHint")}</p>}
        <div><Button variant="primary" busy={save.isPending} disabled={!valid} onClick={() => save.mutate()}>{t("sourcing.decision.save")}</Button></div>
        <ErrorNote error={save.error} />
      </fieldset>
    </Card>
  );
}

function ConvertCard({ inquiry, onDone }: { inquiry: InquiryDetail; onDone: (caseId: string) => void }) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(inquiry.subject ?? "");
  const convert = useMutation({
    mutationFn: () => api<CaseDetail>(`/api/inquiries/${inquiry.id}/convert`, { method: "POST", body: { title: title.trim() || null } }),
    onSuccess: (c) => onDone(c.id),
  });
  if (inquiry.case_id) {
    return (
      <Card title={t("sourcing.convert.title")}>
        <Link to={`/cases/${inquiry.case_id}`} className="inline-flex items-center gap-1 text-accent hover:underline"><Icon name="folder" size={15} />{t("sourcing.convert.openCase")}</Link>
      </Card>
    );
  }
  const gate = inquiry.gate;
  return (
    <Card title={t("sourcing.convert.title")}>
      {gate.ok ? (
        <div className="flex flex-col gap-2">
          <Field label={t("sourcing.case.title")} htmlFor="cv-title"><Input id="cv-title" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <div><Button variant="primary" icon="folder" busy={convert.isPending} onClick={() => convert.mutate()}>{t("sourcing.convert.button")}</Button></div>
        </div>
      ) : (
        <p className="text-sm text-warning">
          {t(`sourcing.gate.${gate.code}`)}
          {gate.details.checks && ` ${gate.details.checks.map((c) => t(`sourcing.decision.checks.${c}`)).join("، ")}`}
        </p>
      )}
      <ErrorNote error={convert.error} />
    </Card>
  );
}

export function InquiryDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const f = useFormat();
  const navigate = useNavigate();
  const invalidate = useInvalidateSourcing();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const inquiry = useQuery({ queryKey: ["inquiry", id], queryFn: () => api<InquiryDetail>(`/api/inquiries/${id}`) });
  const refresh = () => { void inquiry.refetch(); invalidate(); };
  const patch = useMutation({ mutationFn: (status: string) => api(`/api/inquiries/${id}`, { method: "PATCH", body: { status } }), onSuccess: refresh });
  const reject = useMutation({
    mutationFn: () => api(`/api/inquiries/${id}/reject`, { method: "POST", body: { reason } }),
    onSuccess: () => { setRejecting(false); refresh(); },
  });
  const remove = useMutation({ mutationFn: () => api(`/api/inquiries/${id}`, { method: "DELETE" }), onSuccess: () => { invalidate(); navigate("/sourcing"); } });
  if (inquiry.isLoading) return <Loading />;
  if (inquiry.error || !inquiry.data) return <ErrorNote error={inquiry.error} />;
  const inq = inquiry.data;
  const open = !["converted", "rejected"].includes(inq.status);
  return (
    <div className="flex flex-col gap-4">
      <Link to="/sourcing" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><Icon name="chevronStart" size={15} /> {t("sourcing.inquiries")}</Link>
      <PageHeader title={<span dir="auto">{inq.subject || t("sourcing.inquiry.untitled")}</span>}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          <StatusBadge group="inquiry" status={inq.status} />
          {inq.party_id && <PartyName fa={inq.party_name_fa ?? null} en={inq.party_name_en ?? null} id={inq.party_id} />}
          <span>{t(`sourcing.channels.${inq.source_channel}`)} · {t(`sourcing.inquiry.kinds.${inq.kind}`)}</span>
          <span className="tabular-nums">{f.date(inq.received_at, true)}</span>
          {inq.response_due_on && <span>{t("sourcing.inquiry.responseDue")}: <span className="tabular-nums">{f.day(inq.response_due_on)}</span></span>}
        </span>}
        actions={<>
          {open && (
            <Select className="w-48" aria-label={t("sourcing.status.label")} value={inq.status} onChange={(e) => patch.mutate(e.target.value)}>
              {(["new", "needs_info", "ready_for_screening", "no_reply"] as const).map((s) => <option key={s} value={s}>{t(`sourcing.status.inquiry.${s}`)}</option>)}
            </Select>
          )}
          {open && <Button variant="danger" onClick={() => setRejecting(true)}>{t("sourcing.inquiry.reject")}</Button>}
          {!inq.case_id && <Button variant="ghost" busy={remove.isPending} onClick={() => remove.mutate()}>{t("delete.button")}</Button>}
        </>} />
      <ErrorNote error={patch.error || remove.error} />
      {inq.reject_reason && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" dir="auto">{t("sourcing.inquiry.rejected")}: {inq.reject_reason}</p>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          {inq.raw_text && (
            <Card title={t("sourcing.inquiry.rawText")}>
              <pre className="max-h-72 overflow-y-auto font-sans text-sm whitespace-pre-wrap break-words" dir="auto">{inq.raw_text}</pre>
            </Card>
          )}
          <ItemsCard owner={{ inquiry_id: inq.id }} items={inq.items} warnings={inq.warnings} ownerDocuments={inq.documents} onChanged={refresh} />
          <AttachedDocuments documents={inq.documents} linkPath={`/api/inquiries/${inq.id}/documents`} onChanged={refresh} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <ConvertCard inquiry={inq} onDone={(caseId) => { invalidate(); navigate(`/cases/${caseId}`); }} />
          <DecisionPanel key={inq.decision?.updated_at ?? "new"} inquiry={inq} onSaved={refresh} />
          <HistoryCard title={t("parties.tabs.history")} entityType="inquiry" entityId={inq.id} />
          {!inq.case_id && <CascadeDeleteCard url={`/api/inquiries/${inq.id}`} confirmKey="confirm_subject" expected={inq.subject?.trim() || "DELETE"}
            hint={t("sourcing.inquiry.cascadeHint")} typeLabel={t(inq.subject?.trim() ? "sourcing.inquiry.typeSubject" : "sourcing.inquiry.typeDelete")}
            button={t("sourcing.inquiry.cascadeButton")} onDeleted={() => { invalidate(); navigate("/sourcing"); }} />}
        </div>
      </div>
      {rejecting && (
        <Modal open title={t("sourcing.inquiry.reject")} onClose={() => setRejecting(false)}
          footer={<><Button onClick={() => setRejecting(false)}>{t("common.cancel")}</Button>
            <Button variant="danger" disabled={!reason.trim()} busy={reject.isPending} onClick={() => reject.mutate()}>{t("sourcing.inquiry.reject")}</Button></>}>
          <Field label={t("sourcing.reason")} htmlFor="rj-reason"><Textarea id="rj-reason" dir="auto" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <ErrorNote error={reject.error} />
        </Modal>
      )}
    </div>
  );
}
