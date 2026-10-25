import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, errorMessage, Field, IconButton, Input, Loading, Select, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, ApiError, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Contact, DocumentDetail, EventItem, Followup, Interaction, PartyDetail } from "../../lib/types";
import { EventList } from "../events/EventLogPage";
import { CountrySelect } from "./PartiesPage";
import { useQuickLog } from "./QuickLog";
import { CancelFollowupButton, FollowupActions, METHOD_TYPES, PartyName, ROLES, StageSelect, stageLabel } from "./shared";

const TABS = ["overview", "contacts", "interactions", "documents", "history"] as const;
type Tab = (typeof TABS)[number];

function useParty(id: string) {
  return useQuery({ queryKey: ["party", id], queryFn: () => api<PartyDetail>(`/api/parties/${id}`) });
}

function useRefresh(id: string) {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [["party", id], ["parties"], ["command-center"], ["interactions", id], ["events", "party", id]]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  };
}

// ---- overview ----------------------------------------------------------------------------

function Overview({ party }: { party: PartyDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const refresh = useRefresh(party.id);
  const [form, setForm] = useState({
    name_fa: party.name_fa ?? "", name_en: party.name_en ?? "", kind: party.kind, country_iso2: party.country_iso2 ?? "",
    website: party.website ?? "", notes: party.notes ?? "",
  });
  const [dnc, setDnc] = useState(party.do_not_contact);
  const [dncReason, setDncReason] = useState(party.do_not_contact_reason ?? "");
  const [newRole, setNewRole] = useState("");

  const save = useMutation({
    mutationFn: () => api(`/api/parties/${party.id}`, {
      method: "PATCH",
      body: { ...form, name_fa: form.name_fa || null, name_en: form.name_en || null, country_iso2: form.country_iso2 || null,
        website: form.website || null, notes: form.notes || null, do_not_contact: dnc, do_not_contact_reason: dnc ? dncReason : null },
    }),
    onSuccess: () => { toast(t("common.saved"), "success"); refresh(); },
  });
  const addRole = useMutation({
    mutationFn: (role: string) => api(`/api/parties/${party.id}/roles`, { method: "POST", body: { role } }),
    onSuccess: () => { setNewRole(""); refresh(); },
  });
  const removeRole = useMutation({
    mutationFn: (role: string) => api(`/api/parties/${party.id}/roles/${role}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const archive = useMutation({
    mutationFn: () => api(`/api/parties/${party.id}/${party.status === "active" ? "archive" : "unarchive"}`, { method: "POST" }),
    onSuccess: refresh,
  });
  const free = ROLES.filter((r) => !party.roles.some((x) => x.role === r));

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div className="flex flex-col gap-4">
        <Card title={t("parties.rolesAndStages")}>
          {party.roles.length === 0 && <p className="mb-3 text-sm text-muted">{t("parties.noRoles")}</p>}
          <ul className="flex flex-col gap-2">
            {party.roles.map((r) => (
              <li key={r.role} className="flex flex-wrap items-center gap-2">
                <span className="w-32 text-sm font-medium">{t(`parties.roles.${r.role}`)}</span>
                <StageSelect partyId={party.id} role={r.role} stage={r.stage} onChanged={refresh} />
                <span className="text-xs text-muted tabular-nums">{t("parties.since", { date: f.date(r.stage_changed_at) })}</span>
                <IconButton icon="x" label={t("parties.removeRole")} className="ms-auto" onClick={() => removeRole.mutate(r.role)} />
              </li>
            ))}
          </ul>
          {free.length > 0 && (
            <div className="mt-3 flex gap-2 border-t border-line pt-3">
              <Select className="w-44" aria-label={t("parties.addRole")} value={newRole} onChange={(e) => setNewRole(e.target.value)}>
                <option value="">{t("parties.addRole")}</option>
                {free.map((r) => <option key={r} value={r}>{t(`parties.roles.${r}`)}</option>)}
              </Select>
              <Button icon="plus" disabled={!newRole} busy={addRole.isPending} onClick={() => addRole.mutate(newRole)}>{t("common.add")}</Button>
            </div>
          )}
          <ErrorNote error={addRole.error || removeRole.error} />
        </Card>
        <Card title={t("parties.openFollowups")} padded={false}>
          <FollowupRows rows={party.open_followups} />
        </Card>
      </div>
      <Card title={t("parties.details")}>
        <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          <Field label={t("parties.nameFa")} htmlFor="pd-fa"><Input id="pd-fa" value={form.name_fa} onChange={(e) => setForm({ ...form, name_fa: e.target.value })} /></Field>
          <Field label={t("parties.nameEn")} htmlFor="pd-en"><Input id="pd-en" dir="ltr" value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} /></Field>
          <Field label={t("parties.kind")} htmlFor="pd-kind">
            <Select id="pd-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as "company" | "person" })}>
              <option value="company">{t("parties.kinds.company")}</option>
              <option value="person">{t("parties.kinds.person")}</option>
            </Select>
          </Field>
          <Field label={t("parties.country")} htmlFor="pd-country"><CountrySelect id="pd-country" value={form.country_iso2} onChange={(v) => setForm({ ...form, country_iso2: v })} /></Field>
          <div className="sm:col-span-2"><Field label={t("parties.website")} htmlFor="pd-web"><Input id="pd-web" dir="ltr" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} /></Field></div>
          <div className="sm:col-span-2"><Field label={t("parties.notes")} htmlFor="pd-notes"><Textarea id="pd-notes" dir="auto" rows={4} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field></div>
          <div className="rounded-md border border-line p-3 sm:col-span-2">
            <Checkbox label={t("parties.dncSwitch")} checked={dnc} onChange={setDnc} />
            {dnc && <Input className="mt-2" aria-label={t("parties.dncReason")} placeholder={t("parties.dncReason")} value={dncReason} onChange={(e) => setDncReason(e.target.value)} />}
          </div>
          <div className="flex items-center gap-2 sm:col-span-2">
            <Button type="submit" variant="primary" busy={save.isPending} disabled={dnc && !dncReason.trim()}>{t("common.save")}</Button>
            <Button className="ms-auto" variant={party.status === "active" ? "danger" : "secondary"} busy={archive.isPending} onClick={() => archive.mutate()}>
              {party.status === "active" ? t("parties.archive") : t("parties.unarchive")}
            </Button>
          </div>
          <div className="sm:col-span-2"><ErrorNote error={save.error || archive.error} /></div>
        </form>
      </Card>
    </div>
  );
}

function FollowupRows({ rows }: { rows: Followup[] }) {
  const { t } = useTranslation();
  const f = useFormat();
  if (rows.length === 0) return <EmptyState>{t("parties.noOpenFollowups")}</EmptyState>;
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => (
        <li key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
          <span className="w-24 tabular-nums text-muted">{f.day(row.due_on)}</span>
          <span className="min-w-0 flex-1 truncate" dir="auto">{row.action}</span>
          <FollowupActions followup={row} extra={<CancelFollowupButton followup={row} />} />
        </li>
      ))}
    </ul>
  );
}

// ---- contacts ----------------------------------------------------------------------------

function MethodForm({ contactId, onDone }: { contactId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [type, setType] = useState("whatsapp");
  const [value, setValue] = useState("");
  const add = useMutation({
    mutationFn: () => api(`/api/contacts/${contactId}/methods`, { method: "POST", body: { type, value } }),
    onSuccess: () => { setValue(""); onDone(); },
  });
  return (
    <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
      <Select className="w-32" aria-label={t("contacts.methodType")} value={type} onChange={(e) => setType(e.target.value)}>
        {METHOD_TYPES.map((m) => <option key={m} value={m}>{t(`contacts.methods.${m}`)}</option>)}
      </Select>
      <Input className="w-56" dir="ltr" aria-label={t("contacts.value")} placeholder={t("contacts.value")} value={value} required onChange={(e) => setValue(e.target.value)} />
      <Button type="submit" icon="plus" busy={add.isPending}>{t("common.add")}</Button>
      {add.error ? <DuplicateMethodError error={add.error} /> : null}
    </form>
  );
}

function DuplicateMethodError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error instanceof ApiError && error.code === "duplicate_contact_method") {
    const d = error.details as { party_id: string; party_name: string; contact_name: string };
    return (
      <p className="w-full text-sm text-danger">
        {t("contacts.duplicateMethod")} <Link className="underline" to={`/parties/${d.party_id}?tab=contacts`}><Bdi>{d.party_name}</Bdi></Link> (<Bdi>{d.contact_name}</Bdi>)
      </p>
    );
  }
  return <p className="w-full text-sm text-danger">{errorMessage(t, error)}</p>;
}

function ContactCard({ contact, partyId }: { contact: Contact; partyId: string }) {
  const { t } = useTranslation();
  const refresh = useRefresh(partyId);
  const toggle = useMutation({
    mutationFn: () => api(`/api/contacts/${contact.id}/${contact.status === "active" ? "archive" : "unarchive"}`, { method: "POST" }),
    onSuccess: refresh,
  });
  const toggleMethod = useMutation({
    mutationFn: (m: { id: string; status: string }) => api(`/api/contacts/methods/${m.id}/${m.status === "active" ? "archive" : "unarchive"}`, { method: "POST" }),
    onSuccess: refresh,
  });
  const makePrimary = useMutation({
    mutationFn: () => api(`/api/contacts/${contact.id}`, { method: "PATCH", body: { is_primary: true } }),
    onSuccess: refresh,
  });
  return (
    <li className={`rounded-md border border-line p-3 ${contact.status === "archived" ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium"><Bdi>{contact.name_fa || contact.name_en}</Bdi></span>
        {contact.name_fa && contact.name_en && <Bdi className="text-sm text-muted">{contact.name_en}</Bdi>}
        {contact.job_title && <span className="text-sm text-muted">· {contact.job_title}</span>}
        {contact.is_primary && <Badge tone="accent">{t("contacts.primary")}</Badge>}
        {contact.status === "archived" && <Badge>{t("parties.archived")}</Badge>}
        <span className="ms-auto flex gap-1">
          {!contact.is_primary && contact.status === "active" && <Button variant="ghost" onClick={() => makePrimary.mutate()}>{t("contacts.makePrimary")}</Button>}
          <Button variant="ghost" onClick={() => toggle.mutate()}>{contact.status === "active" ? t("parties.archive") : t("parties.unarchive")}</Button>
        </span>
      </div>
      <ul className="mt-2 flex flex-col gap-1">
        {contact.methods.map((m) => (
          <li key={m.id} className={`flex items-center gap-2 text-sm ${m.status === "archived" ? "line-through opacity-60" : ""}`}>
            <Badge>{t(`contacts.methods.${m.type}`)}</Badge>
            <Bdi ltr className="font-mono">{m.value}</Bdi>
            <button type="button" className="ms-auto text-xs text-muted hover:text-fg" onClick={() => toggleMethod.mutate(m)}>
              {m.status === "active" ? t("parties.archive") : t("parties.unarchive")}
            </button>
          </li>
        ))}
      </ul>
      {contact.status === "active" && <MethodForm contactId={contact.id} onDone={refresh} />}
    </li>
  );
}

function Contacts({ party }: { party: PartyDetail }) {
  const { t } = useTranslation();
  const refresh = useRefresh(party.id);
  const [form, setForm] = useState({ name_fa: "", name_en: "", job_title: "", type: "whatsapp", value: "" });
  const create = useMutation({
    mutationFn: () => api("/api/contacts", {
      method: "POST",
      body: {
        party_id: party.id, name_fa: form.name_fa || null, name_en: form.name_en || null, job_title: form.job_title || null,
        methods: form.value.trim() ? [{ type: form.type, value: form.value }] : [],
      },
    }),
    onSuccess: () => { setForm({ name_fa: "", name_en: "", job_title: "", type: "whatsapp", value: "" }); refresh(); },
  });
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Card title={t("contacts.title")}>
        {party.contacts.length === 0 ? <EmptyState>{t("contacts.empty")}</EmptyState> : (
          <ul className="flex flex-col gap-2">{party.contacts.map((c) => <ContactCard key={c.id} contact={c} partyId={party.id} />)}</ul>
        )}
      </Card>
      <Card title={t("contacts.add")}>
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label={t("parties.nameFa")} htmlFor="ct-fa"><Input id="ct-fa" value={form.name_fa} onChange={(e) => setForm({ ...form, name_fa: e.target.value })} /></Field>
          <Field label={t("parties.nameEn")} htmlFor="ct-en"><Input id="ct-en" dir="ltr" value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} /></Field>
          <Field label={t("contacts.jobTitle")} htmlFor="ct-job"><Input id="ct-job" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /></Field>
          <div className="flex gap-2">
            <Select className="w-32" aria-label={t("contacts.methodType")} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {METHOD_TYPES.map((m) => <option key={m} value={m}>{t(`contacts.methods.${m}`)}</option>)}
            </Select>
            <Input dir="ltr" aria-label={t("contacts.value")} placeholder={t("contacts.value")} value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          </div>
          {create.error ? <DuplicateMethodError error={create.error} /> : null}
          <div><Button type="submit" variant="primary" disabled={!form.name_fa.trim() && !form.name_en.trim()} busy={create.isPending}>{t("common.add")}</Button></div>
        </form>
      </Card>
    </div>
  );
}

// ---- interactions -------------------------------------------------------------------------

function InteractionItem({ row, contacts, highlight }: { row: Interaction; contacts: Contact[]; highlight: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ref = useRef<HTMLLIElement>(null);
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(row.subject ?? "");
  const [body, setBody] = useState(row.body ?? "");
  const detail = useQuery({ queryKey: ["interaction", row.id], queryFn: () => api<{ documents: { link_id: string; document_id: string; title: string }[] }>(`/api/interactions/${row.id}`) });
  useEffect(() => { if (highlight) ref.current?.scrollIntoView({ block: "center" }); }, [highlight]);
  const save = useMutation({
    mutationFn: () => api(`/api/interactions/${row.id}`, { method: "PATCH", body: { subject: subject || null, body: body || null } }),
    onSuccess: () => { setEditing(false); void queryClient.invalidateQueries({ queryKey: ["interactions"] }); },
  });
  const contact = contacts.find((c) => c.id === row.contact_id);
  return (
    <li ref={ref} className={`px-4 py-3 ${highlight ? "bg-accent-soft" : ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone="accent">{t(`interactions.channels.${row.channel}`)}</Badge>
        <Badge>{t(`interactions.directions.${row.direction}`)}</Badge>
        <span className="tabular-nums text-muted">{f.date(row.occurred_at, true)}</span>
        {contact && <Bdi className="text-muted">{contact.name_fa || contact.name_en}</Bdi>}
        <button type="button" className="ms-auto text-xs text-accent hover:underline" onClick={() => setEditing(!editing)}>{t("interactions.correct")}</button>
      </div>
      {editing ? (
        <form className="mt-2 flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Input aria-label={t("interactions.subject")} value={subject} onChange={(e) => setSubject(e.target.value)} />
          <Textarea aria-label={t("interactions.body")} dir="auto" rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
          <p className="text-xs text-muted">{t("interactions.correctHint")}</p>
          <div><Button type="submit" variant="primary" busy={save.isPending}>{t("common.save")}</Button></div>
          <ErrorNote error={save.error} />
        </form>
      ) : (
        <>
          {row.subject && <p className="mt-1.5 font-medium" dir="auto">{row.subject}</p>}
          {row.body && <pre className="mt-1 font-sans text-sm whitespace-pre-wrap break-words" dir="auto">{row.body}</pre>}
        </>
      )}
      {row.no_followup_reason && <p className="mt-1.5 text-xs text-muted">{t("interactions.noFollowup")}: {row.no_followup_reason}</p>}
      {(detail.data?.documents ?? []).length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {detail.data!.documents.map((d) => (
            <li key={d.link_id}><Link to={`/documents/${d.document_id}`} className="inline-flex items-center gap-1 text-sm text-accent hover:underline"><Icon name="file" size={14} /><Bdi>{d.title}</Bdi></Link></li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Interactions({ party, highlight }: { party: PartyDetail; highlight: string | null }) {
  const { t } = useTranslation();
  const quickLog = useQuickLog();
  const [q, setQ] = useState("");
  const list = useQuery({
    queryKey: ["interactions", party.id, q],
    queryFn: () => api<Page<Interaction>>("/api/interactions", { query: { party_id: party.id, q, page_size: 200 } }),
  });
  return (
    <Card padded={false} title={t("interactions.title")} actions={<Button variant="primary" icon="plus" onClick={() => quickLog.open(party.id)}>{t("quicklog.button")}</Button>}>
      <div className="border-b border-line p-3">
        <Input type="search" className="max-w-xs" placeholder={t("interactions.searchPlaceholder")} defaultValue={q}
          onKeyDown={(e) => e.key === "Enter" && setQ((e.target as HTMLInputElement).value)} />
      </div>
      {(list.data?.items ?? []).length === 0 ? <EmptyState>{t("interactions.empty")}</EmptyState> : (
        <ol className="divide-y divide-line">
          {list.data!.items.map((row) => <InteractionItem key={row.id} row={row} contacts={party.contacts} highlight={row.id === highlight} />)}
        </ol>
      )}
    </Card>
  );
}

// ---- documents and history ------------------------------------------------------------------

function Documents({ party }: { party: PartyDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const refresh = useRefresh(party.id);
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<unknown>(null);
  const attach = async (files: File[]) => {
    setError(null);
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      let id: string;
      try {
        id = (await api<DocumentDetail>("/api/documents", { method: "POST", form })).id;
      } catch (err) {
        if (err instanceof ApiError && err.code === "duplicate_document") id = String(err.details.id);
        else { setError(err); continue; }
      }
      await api(`/api/parties/${party.id}/documents`, { method: "POST", body: { document_id: id } }).catch(setError);
    }
    refresh();
  };
  const unlink = useMutation({
    mutationFn: (d: { link_id: string; entity_type: string; entity_id: string }) =>
      api(d.entity_type === "party" ? `/api/parties/${party.id}/documents/${d.link_id}` : `/api/interactions/${d.entity_id}/documents/${d.link_id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return (
    <Card padded={false} title={t("parties.documents")} actions={<>
      <input ref={input} type="file" multiple hidden onChange={(e) => { if (e.target.files) void attach(Array.from(e.target.files)); e.target.value = ""; }} />
      <Button icon="upload" onClick={() => input.current?.click()}>{t("parties.attach")}</Button>
    </>}>
      <ErrorNote error={error || unlink.error} />
      {party.documents.length === 0 ? <EmptyState>{t("parties.noDocuments")}</EmptyState> : (
        <ul className="divide-y divide-line">
          {party.documents.map((d) => (
            <li key={d.link_id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
              <Link to={`/documents/${d.document_id}`} className="font-medium text-accent hover:underline"><Bdi>{d.title}</Bdi></Link>
              <Bdi className="text-muted">{d.original_filename}</Bdi>
              <Badge>{d.entity_type === "party" ? t("parties.attachedToParty") : t("parties.attachedToInteraction")}</Badge>
              <span className="tabular-nums text-muted">{f.bytes(d.size_bytes)}</span>
              <IconButton icon="x" label={t("documents.unlink")} className="ms-auto" onClick={() => unlink.mutate(d)} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function History({ partyId }: { partyId: string }) {
  const events = useQuery({
    queryKey: ["events", "party", partyId],
    queryFn: () => api<Page<EventItem>>("/api/events", { query: { entity_type: "party", entity_id: partyId, page_size: 200 } }),
  });
  return <Card padded={false}><EventList items={events.data?.items ?? []} compact /></Card>;
}

export function PartyDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const f = useFormat();
  const quickLog = useQuickLog();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "overview") as Tab;
  const party = useParty(id);
  if (party.isLoading) return <Loading />;
  if (party.error || !party.data) return <ErrorNote error={party.error} />;
  const p = party.data;
  // the other-language name, only when both exist (PartyName already shows whichever one exists)
  const subtitle: ReactNode = p.name_fa && p.name_en ? (f.lang === "fa" ? p.name_en : p.name_fa) : null;
  return (
    <div className="flex flex-col gap-4">
      <Link to="/parties" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><Icon name="chevronStart" size={15} /> {t("nav.parties")}</Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold"><PartyName fa={p.name_fa} en={p.name_en} dnc={p.do_not_contact} /></h1>
            {p.status === "archived" && <Badge>{t("parties.archived")}</Badge>}
            {p.roles.map((r) => <Badge key={r.role} tone="accent">{t(`parties.roles.${r.role}`)} · {stageLabel(t, r.role, r.stage)}</Badge>)}
          </div>
          {subtitle && <p className="mt-0.5 text-sm text-muted"><Bdi>{subtitle}</Bdi></p>}
          {p.do_not_contact && <p className="mt-1 text-sm text-danger">{t("parties.dncWarning")} {p.do_not_contact_reason}</p>}
        </div>
        <Button variant="primary" icon="plus" onClick={() => quickLog.open(p.id)}>{t("quicklog.button")}</Button>
      </div>
      <div className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((key) => (
          <button key={key} type="button" onClick={() => setParams({ tab: key }, { replace: true })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${key === tab ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
            {t(`parties.tabs.${key}`)}
            {key === "contacts" && ` (${f.num(p.contacts.filter((c) => c.status === "active").length)})`}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview key={p.updated_at} party={p} />}
      {tab === "contacts" && <Contacts party={p} />}
      {tab === "interactions" && <Interactions party={p} highlight={params.get("interaction")} />}
      {tab === "documents" && <Documents party={p} />}
      {tab === "history" && <History partyId={p.id} />}
    </div>
  );
}
