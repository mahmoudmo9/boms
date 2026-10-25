import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DataTable, Pagination, type SortState } from "../../components/DataTable";
import { Badge, Button, Card, Checkbox, ErrorNote, Field, Input, Modal, PageHeader, Select, Textarea } from "../../components/ui";
import { api, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Country, Party, PartyDetail, PossibleDuplicate } from "../../lib/types";
import { useQuickLog } from "./QuickLog";
import { PartyName, ROLES, stageLabel, useStages } from "./shared";

const PAGE_SIZE = 50;

export function useCountries() {
  return useQuery({
    queryKey: ["basedata", "countries", "all-active"],
    queryFn: () => api<Page<Country>>("/api/basedata/countries", { query: { active: true, page_size: 500 } }),
    staleTime: 5 * 60_000,
  });
}

export function CountrySelect({ value, onChange, id, allowEmpty = true, emptyLabel }: { value: string; onChange: (v: string) => void; id?: string; allowEmpty?: boolean; emptyLabel?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const countries = useCountries();
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-label={t("parties.country")}>
      {allowEmpty && <option value="">{emptyLabel ?? t("common.all")}</option>}
      {(countries.data?.items ?? []).map((c) => (
        <option key={c.iso2} value={c.iso2}>{f.lang === "fa" ? c.name_fa : c.name_en}</option>
      ))}
    </Select>
  );
}

/** "Handles HS 3907 / ISIC C20 / tag X" (capability tags of the sourcing module). */
function CapabilityFilter({ value, onChange }: { value: string; onChange: (v: string | null) => void }) {
  const { t } = useTranslation();
  const [kind, text] = value.includes(":") ? [value.split(":")[0], value.slice(value.indexOf(":") + 1)] : ["hs", ""];
  const [draftKind, setDraftKind] = useState(kind);
  const apply = (k: string, v: string) => onChange(v.trim() ? `${k}:${v.trim()}` : null);
  return (
    <div className="flex gap-1">
      <Select className="w-24" aria-label={t("sourcing.capabilities.filterKind")} value={draftKind} onChange={(e) => { setDraftKind(e.target.value); if (text) apply(e.target.value, text); }}>
        {(["hs", "isic", "tag"] as const).map((k) => <option key={k} value={k}>{t(`sourcing.capabilities.kinds.${k}`)}</option>)}
      </Select>
      <Input key={value} className="w-36" dir="auto" placeholder={t("sourcing.capabilities.filterPlaceholder")} defaultValue={text}
        onKeyDown={(e) => e.key === "Enter" && apply(draftKind, (e.target as HTMLInputElement).value)}
        onBlur={(e) => e.target.value !== text && apply(draftKind, e.target.value)} />
    </div>
  );
}

function useDebounced<T>(value: T, ms: number) {
  const [d, setD] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setD(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return d;
}

/** "New party" with a live duplicate warning; creating over a warning needs an explicit confirmation. */
function NewPartyDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name_fa: "", name_en: "", kind: "company", country_iso2: "", website: "", notes: "" });
  const [roles, setRoles] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const names = useDebounced({ fa: form.name_fa.trim(), en: form.name_en.trim() }, 300);
  const dups = useQuery({
    queryKey: ["parties", "duplicates", names.fa, names.en],
    queryFn: () => api<{ possible_duplicates: PossibleDuplicate[] }>("/api/parties/duplicates", { query: { name_fa: names.fa, name_en: names.en } }),
    enabled: !!(names.fa || names.en),
  });
  const duplicates = names.fa || names.en ? dups.data?.possible_duplicates ?? [] : [];
  useEffect(() => setConfirmed(false), [names.fa, names.en]);

  const create = useMutation({
    mutationFn: () =>
      api<{ created: boolean; party?: PartyDetail; possible_duplicates: PossibleDuplicate[] }>("/api/parties", {
        method: "POST",
        body: {
          name_fa: form.name_fa || null, name_en: form.name_en || null, kind: form.kind,
          country_iso2: form.country_iso2 || null, website: form.website || null, notes: form.notes || null,
          roles, confirm_duplicate: confirmed,
        },
      }),
    onSuccess: (res) => {
      if (res.created && res.party) {
        void queryClient.invalidateQueries({ queryKey: ["parties"] });
        onClose();
        navigate(`/parties/${res.party.id}`);
      }
    },
  });
  const needsConfirm = duplicates.length > 0 && !confirmed;
  const set = (k: keyof typeof form, v: string) => setForm({ ...form, [k]: v });

  return (
    <Modal open wide title={t("parties.new")} onClose={onClose}
      footer={<>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" type="submit" form="new-party" busy={create.isPending} disabled={(!form.name_fa.trim() && !form.name_en.trim()) || needsConfirm}>{t("common.save")}</Button>
      </>}>
      <form id="new-party" className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label={t("parties.nameFa")} htmlFor="np-fa"><Input id="np-fa" autoFocus value={form.name_fa} maxLength={300} onChange={(e) => set("name_fa", e.target.value)} /></Field>
        <Field label={t("parties.nameEn")} htmlFor="np-en"><Input id="np-en" dir="ltr" value={form.name_en} maxLength={300} onChange={(e) => set("name_en", e.target.value)} /></Field>
        {duplicates.length > 0 && (
          <div className="rounded-md bg-warning-soft p-2.5 text-sm sm:col-span-2">
            <p className="mb-1.5 font-medium text-warning">{t("parties.possibleDuplicates")}</p>
            <ul className="mb-2 flex flex-col gap-1">
              {duplicates.map((d) => (
                <li key={d.id} className="flex items-center gap-2">
                  <PartyName fa={d.name_fa} en={d.name_en} dnc={d.do_not_contact} id={d.id} />
                  {d.status === "archived" && <Badge>{t("parties.archived")}</Badge>}
                </li>
              ))}
            </ul>
            <Checkbox label={t("parties.confirmDuplicate")} checked={confirmed} onChange={setConfirmed} />
          </div>
        )}
        <Field label={t("parties.kind")} htmlFor="np-kind">
          <Select id="np-kind" value={form.kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="company">{t("parties.kinds.company")}</option>
            <option value="person">{t("parties.kinds.person")}</option>
          </Select>
        </Field>
        <Field label={t("parties.country")} htmlFor="np-country"><CountrySelect id="np-country" value={form.country_iso2} onChange={(v) => set("country_iso2", v)} /></Field>
        <Field label={t("parties.website")} htmlFor="np-web"><Input id="np-web" dir="ltr" value={form.website} onChange={(e) => set("website", e.target.value)} /></Field>
        <Field label={t("parties.roles.label")}>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {ROLES.map((r) => (
              <Checkbox key={r} label={t(`parties.roles.${r}`)} checked={roles.includes(r)}
                onChange={(on) => setRoles(on ? [...roles, r] : roles.filter((x) => x !== r))} />
            ))}
          </div>
        </Field>
        <div className="sm:col-span-2"><Field label={t("parties.notes")} htmlFor="np-notes"><Textarea id="np-notes" rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><ErrorNote error={create.error} /></div>
      </form>
    </Modal>
  );
}

export function PartiesPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const quickLog = useQuickLog();
  const stages = useStages();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const q = params.get("q") ?? "";
  const role = params.get("role") ?? "";
  const stage = params.get("stage") ?? "";
  const country = params.get("country") ?? "";
  const status = params.get("status") ?? "active";
  const capability = params.get("capability") ?? "";
  const page = Number(params.get("page") ?? 1);
  const sort: SortState = { id: params.get("sort") ?? "updated_at", desc: params.get("order") !== "asc" };
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };

  const list = useQuery({
    queryKey: ["parties", "list", q, role, stage, country, status, capability, page, sort.id, sort.desc],
    queryFn: () => api<Page<Party>>("/api/parties", {
      query: { q, role, stage, country, status, capability, page, page_size: PAGE_SIZE, sort: sort.id, order: sort.desc ? "desc" : "asc" },
    }),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<Party, unknown>[]>(() => [
    { id: "name", header: t("parties.name"), cell: ({ row }) => <PartyName fa={row.original.name_fa} en={row.original.name_en} dnc={row.original.do_not_contact} id={row.original.id} className="max-w-72" /> },
    {
      id: "roles", header: t("parties.roles.label"),
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          {row.original.roles.map((r) => <Badge key={r.role} tone="accent">{t(`parties.roles.${r.role}`)} · {stageLabel(t, r.role, r.stage)}</Badge>)}
        </div>
      ),
    },
    { id: "country", header: t("parties.country"), cell: ({ row }) => <Bdi ltr className="font-mono text-xs">{row.original.country_iso2 ?? ""}</Bdi> },
    { id: "last", header: t("parties.lastInteraction"), cell: ({ row }) => <span className="tabular-nums text-muted">{f.date(row.original.last_interaction_at)}</span> },
    {
      id: "next", header: t("parties.nextFollowup"),
      cell: ({ row }) => row.original.next_followup ? (
        <span className="flex items-center gap-2 text-sm"><span className="tabular-nums text-muted">{f.day(row.original.next_followup.due_on)}</span><span className="max-w-48 truncate" dir="auto">{row.original.next_followup.action}</span></span>
      ) : null,
    },
    { id: "updated_at", header: t("parties.updated"), cell: ({ row }) => <span className="tabular-nums text-muted">{f.date(row.original.updated_at)}</span> },
  ], [t, f]);

  return (
    <div>
      <PageHeader title={t("nav.parties")} subtitle={t("parties.subtitle")}
        actions={<>
          <Button icon="plus" onClick={() => quickLog.open()}>{t("quicklog.button")}</Button>
          <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>{t("parties.new")}</Button>
        </>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input key={q} type="search" className="max-w-xs" placeholder={t("parties.searchPlaceholder")} defaultValue={q}
            onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })}
            onBlur={(e) => e.target.value !== q && set({ q: e.target.value })} />
          <Select className="w-40" aria-label={t("parties.roles.label")} value={role} onChange={(e) => set({ role: e.target.value, stage: null })}>
            <option value="">{t("parties.allRoles")}</option>
            {ROLES.map((r) => <option key={r} value={r}>{t(`parties.roles.${r}`)}</option>)}
          </Select>
          <Select className="w-44" aria-label={t("parties.stage")} value={stage} disabled={!role} onChange={(e) => set({ stage: e.target.value })}>
            <option value="">{t("parties.allStages")}</option>
            {(stages.data ?? []).filter((s) => s.role === role).map((s) => <option key={s.code} value={s.code}>{stageLabel(t, role, s.code)}</option>)}
          </Select>
          <div className="w-48"><CountrySelect value={country} onChange={(v) => set({ country: v })} /></div>
          <CapabilityFilter value={capability} onChange={(v) => set({ capability: v })} />
          <Select className="w-36" aria-label={t("parties.status")} value={status} onChange={(e) => set({ status: e.target.value })}>
            <option value="active">{t("parties.statuses.active")}</option>
            <option value="archived">{t("parties.statuses.archived")}</option>
            <option value="all">{t("common.all")}</option>
          </Select>
        </div>
        <ErrorNote error={list.error} />
        <DataTable columns={columns} data={list.data?.items ?? []} loading={list.isFetching} rowKey={(p) => p.id}
          sortable={["name", "updated_at"]} sort={sort} onSortChange={(s) => set({ sort: s.id, order: s.desc ? "desc" : "asc" })}
          empty={t("parties.empty")} />
        <Pagination page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={(p) => set({ page: String(p) })} />
      </Card>
      {creating && <NewPartyDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
