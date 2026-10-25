import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { DataTable, Pagination } from "../../components/DataTable";
import { DateInput } from "../../components/DateInput";
import { Button, Card, ErrorNote, Field, Input, Modal, PageHeader, Select, Textarea } from "../../components/ui";
import { api, type Page } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import type { Inquiry, InquiryDetail, Party, PartyDetail } from "../../lib/types";
import { PartyPicker } from "../parties/QuickLog";
import { PartyName } from "../parties/shared";
import { INQUIRY_KINDS, SOURCE_CHANNELS, StatusBadge, useInvalidateSourcing } from "./shared";

const PAGE_SIZE = 50;
const STATUSES = ["new", "needs_info", "ready_for_screening", "rejected", "no_reply", "converted"] as const;

interface Prefill {
  party_id: string | null;
  source_channel: string;
  received_at: string;
  subject: string | null;
  raw_text: string | null;
  source_interaction_id: string;
}

/** New inquiry; "Create inquiry from this interaction" opens it pre-filled (?from_interaction=). */
export function NewInquiryDialog({ interactionId, onClose }: { interactionId?: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const invalidate = useInvalidateSourcing();
  const [party, setParty] = useState<Party | null>(null);
  const [form, setForm] = useState({ source_channel: "whatsapp", kind: "rfq", subject: "", raw_text: "", response_due_on: null as string | null,
    received_at: null as string | null, source_interaction_id: null as string | null });
  useEffect(() => {
    if (!interactionId) return;
    void api<Prefill>("/api/inquiries/prefill", { query: { interaction_id: interactionId } }).then(async (p) => {
      setForm((f) => ({ ...f, source_channel: p.source_channel, subject: p.subject ?? "", raw_text: p.raw_text ?? "", received_at: p.received_at,
        source_interaction_id: p.source_interaction_id }));
      if (p.party_id) setParty(await api<PartyDetail>(`/api/parties/${p.party_id}`));
    });
  }, [interactionId]);
  const create = useMutation({
    mutationFn: () => api<InquiryDetail>("/api/inquiries", {
      method: "POST",
      body: { ...form, party_id: party?.id ?? null, subject: form.subject.trim() || null, raw_text: form.raw_text || null },
    }),
    onSuccess: (row) => { invalidate(); onClose(); navigate(`/sourcing/inquiries/${row.id}`); },
  });
  return (
    <Modal open wide title={t("sourcing.inquiry.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" type="submit" form="new-inquiry" busy={create.isPending}>{t("common.save")}</Button></>}>
      <form id="new-inquiry" className="grid max-h-[65vh] grid-cols-1 gap-3 overflow-y-auto pe-1 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <div className="sm:col-span-2"><Field label={t("sourcing.inquiry.party")} htmlFor="ql-party"><PartyPicker value={party} onChange={setParty} /></Field></div>
        <Field label={t("sourcing.inquiry.channel")} htmlFor="ni-channel">
          <Select id="ni-channel" value={form.source_channel} onChange={(e) => setForm({ ...form, source_channel: e.target.value })}>
            {SOURCE_CHANNELS.map((c) => <option key={c} value={c}>{t(`sourcing.channels.${c}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("sourcing.inquiry.kind")} htmlFor="ni-kind">
          <Select id="ni-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {INQUIRY_KINDS.map((k) => <option key={k} value={k}>{t(`sourcing.inquiry.kinds.${k}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("sourcing.inquiry.responseDue")} htmlFor="ni-due">
          <DateInput id="ni-due" value={form.response_due_on ? fromDateString(form.response_due_on) : null} onChange={(d) => setForm({ ...form, response_due_on: d ? toDateString(d) : null })} />
        </Field>
        <Field label={t("sourcing.inquiry.subject")} htmlFor="ni-subject"><Input id="ni-subject" dir="auto" maxLength={500} value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} /></Field>
        <div className="sm:col-span-2">
          <Field label={t("sourcing.inquiry.rawText")} htmlFor="ni-raw" hint={t("sourcing.inquiry.rawTextHint")}>
            <Textarea id="ni-raw" dir="auto" rows={8} value={form.raw_text} onChange={(e) => setForm({ ...form, raw_text: e.target.value })} />
          </Field>
        </div>
        {form.source_interaction_id && <p className="text-xs text-muted sm:col-span-2">{t("sourcing.inquiry.fromInteraction")}</p>}
        <div className="sm:col-span-2"><ErrorNote error={create.error} /></div>
      </form>
    </Modal>
  );
}

export function InquiriesPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const status = params.get("status") ?? "";
  const page = Number(params.get("page") ?? 1);
  const fromInteraction = params.get("from_interaction");
  const [creating, setCreating] = useState(!!fromInteraction);
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };
  const list = useQuery({
    queryKey: ["inquiries", "list", q, status, page],
    queryFn: () => api<Page<Inquiry>>("/api/inquiries", { query: { q, status, page, page_size: PAGE_SIZE } }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<Inquiry, unknown>[]>(() => [
    { id: "received_at", header: t("sourcing.inquiry.received"), cell: ({ row }) => <span className="tabular-nums text-muted">{f.date(row.original.received_at)}</span> },
    { id: "subject", header: t("sourcing.inquiry.subject"), cell: ({ row }) => (
      <Link to={`/sourcing/inquiries/${row.original.id}`} className="font-medium text-accent hover:underline" dir="auto">
        {row.original.subject || (row.original.raw_text ?? "").slice(0, 80) || "—"}
      </Link>
    ) },
    { id: "party", header: t("sourcing.inquiry.party"), cell: ({ row }) => row.original.party_id
      ? <PartyName fa={row.original.party_name_fa ?? null} en={row.original.party_name_en ?? null} id={row.original.party_id} className="max-w-56" /> : null },
    { id: "channel", header: t("sourcing.inquiry.channel"), cell: ({ row }) => t(`sourcing.channels.${row.original.source_channel}`) },
    { id: "due", header: t("sourcing.inquiry.responseDue"), cell: ({ row }) => <span className="tabular-nums text-muted">{f.day(row.original.response_due_on ?? "")}</span> },
    { id: "status", header: t("sourcing.status.label"), cell: ({ row }) => <StatusBadge group="inquiry" status={row.original.status} /> },
  ], [t, f]);
  return (
    <div>
      <PageHeader title={t("sourcing.inquiries")} subtitle={t("sourcing.inquiriesSubtitle")}
        actions={<Button variant="primary" icon="plus" onClick={() => setCreating(true)}>{t("sourcing.inquiry.new")}</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input key={q} type="search" className="max-w-xs" placeholder={t("sourcing.searchPlaceholder")} defaultValue={q}
            onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })} />
          <Select className="w-48" aria-label={t("sourcing.status.label")} value={status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">{t("common.all")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`sourcing.status.inquiry.${s}`)}</option>)}
          </Select>
        </div>
        <ErrorNote error={list.error} />
        <DataTable columns={columns} data={list.data?.items ?? []} loading={list.isFetching} rowKey={(r) => r.id} empty={t("sourcing.noInquiries")} />
        <Pagination page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={(p) => set({ page: String(p) })} />
      </Card>
      {creating && <NewInquiryDialog interactionId={fromInteraction} onClose={() => { setCreating(false); if (fromInteraction) set({ from_interaction: null }); }} />}
    </div>
  );
}
