import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { DataTable, Pagination } from "../../components/DataTable";
import { Button, Card, ErrorNote, Field, Input, Modal, PageHeader, Select } from "../../components/ui";
import { api, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Case, CaseDetail, Party } from "../../lib/types";
import { PartyPicker } from "../parties/QuickLog";
import { PartyName } from "../parties/shared";
import { Money, StatusBadge, useInvalidateSourcing } from "../sourcing/shared";

const PAGE_SIZE = 50;
export const CASE_STATUSES = ["open", "won", "lost", "closed", "cancelled"] as const;

function NewCaseDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const invalidate = useInvalidateSourcing();
  const [title, setTitle] = useState("");
  const [party, setParty] = useState<Party | null>(null);
  const create = useMutation({
    mutationFn: () => api<CaseDetail>("/api/cases", { method: "POST", body: { title, party_id: party?.id ?? null } }),
    onSuccess: (c) => { invalidate(); onClose(); navigate(`/cases/${c.id}`); },
  });
  return (
    <Modal open title={t("sourcing.case.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" type="submit" form="new-case" disabled={!title.trim()} busy={create.isPending}>{t("common.save")}</Button></>}>
      <form id="new-case" className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label={t("sourcing.case.title")} htmlFor="nc-title"><Input id="nc-title" dir="auto" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label={t("sourcing.case.buyer")} htmlFor="ql-party"><PartyPicker value={party} onChange={setParty} /></Field>
        <p className="text-xs text-muted">{t("sourcing.case.withoutInquiry")}</p>
        <ErrorNote error={create.error} />
      </form>
    </Modal>
  );
}

export function CasesPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const q = params.get("q") ?? "";
  const status = params.get("status") ?? "open";
  const page = Number(params.get("page") ?? 1);
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v !== null ? next.set(k, v) : next.delete(k)));
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };
  const list = useQuery({
    queryKey: ["cases", "list", q, status, page],
    queryFn: () => api<Page<Case>>("/api/cases", { query: { q, status: status === "all" ? "" : status, page, page_size: PAGE_SIZE } }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<Case, unknown>[]>(() => [
    { id: "title", header: t("sourcing.case.title"), cell: ({ row }) => <Link to={`/cases/${row.original.id}`} className="font-medium text-accent hover:underline" dir="auto">{row.original.title}</Link> },
    { id: "party", header: t("sourcing.case.buyer"), cell: ({ row }) => row.original.party_id
      ? <PartyName fa={row.original.party_name_fa ?? null} en={row.original.party_name_en ?? null} id={row.original.party_id} className="max-w-56" /> : null },
    { id: "exposure", header: t("sourcing.decision.exposure"), cell: ({ row }) => <Money amount={row.original.exposure_estimate} currency={row.original.exposure_currency} /> },
    { id: "status", header: t("sourcing.status.label"), cell: ({ row }) => <StatusBadge group="case" status={row.original.status} /> },
    { id: "updated", header: t("parties.updated"), cell: ({ row }) => <span className="tabular-nums text-muted">{f.date(row.original.updated_at)}</span> },
  ], [t, f]);
  return (
    <div>
      <PageHeader title={t("nav.cases")} subtitle={t("sourcing.casesSubtitle")}
        actions={<Button variant="primary" icon="plus" onClick={() => setCreating(true)}>{t("sourcing.case.new")}</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input key={q} type="search" className="max-w-xs" placeholder={t("sourcing.searchPlaceholder")} defaultValue={q}
            onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })} />
          <Select className="w-40" aria-label={t("sourcing.status.label")} value={status} onChange={(e) => set({ status: e.target.value })}>
            {CASE_STATUSES.map((s) => <option key={s} value={s}>{t(`sourcing.status.case.${s}`)}</option>)}
            <option value="all">{t("common.all")}</option>
          </Select>
        </div>
        <ErrorNote error={list.error} />
        <DataTable columns={columns} data={list.data?.items ?? []} loading={list.isFetching} rowKey={(r) => r.id} empty={t("sourcing.noCases")} />
        <Pagination page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={(p) => set({ page: String(p) })} />
      </Card>
      {creating && <NewCaseDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
