import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Icon } from "../../components/Icon";
import { PhoneInput, usePhoneRegions } from "../../components/PhoneInput";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, errorMessage, Field, IconButton, Input, Loading, Modal, Segmented, Select, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, ApiError, type Page } from "../../lib/api";
import { defaultPhoneRegion, isPhoneType } from "../../lib/phone";
import { useFormat } from "../../lib/prefs";
import type { Contact, ContactMethod, DocumentDetail, EventItem, Followup, Interaction, Party, PartyDetail, SharedResult, SharedWith } from "../../lib/types";
import { EventList } from "../events/EventLogPage";
import { CapabilitiesCard } from "../sourcing/Capabilities";
import { CountrySelect } from "./PartiesPage";
import { PartyPicker, useQuickLog } from "./QuickLog";
import { CancelFollowupButton, CHANNELS, DeleteButton, FollowupActions, METHOD_TYPES, PartyName, ROLES, SharedNumberPrompt, StageSelect, stageLabel } from "./shared";

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
  const navigate = useNavigate();
  const [archiveAsk, setArchiveAsk] = useState(false);
  const archive = useMutation({
    mutationFn: (openFollowups: "cancel" | "keep") => party.status === "active"
      ? api(`/api/parties/${party.id}/archive`, { method: "POST", body: { open_followups: openFollowups } })
      : api(`/api/parties/${party.id}/unarchive`, { method: "POST" }),
    onSuccess: () => { setArchiveAsk(false); refresh(); },
  });
  const startArchive = () => (party.status === "active" && party.open_followups.length > 0 ? setArchiveAsk(true) : archive.mutate("cancel"));
  const queryClient = useQueryClient();
  const deleted = () => {
    toast(t("delete.done"), "success");
    navigate("/parties");
    // the party is gone: drop its queries instead of refetching them (404)
    for (const key of [["party", party.id], ["interactions", party.id], ["events", "party", party.id]]) queryClient.removeQueries({ queryKey: key });
    for (const key of [["parties"], ["command-center"]]) void queryClient.invalidateQueries({ queryKey: key });
  };
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
        <CapabilitiesCard partyId={party.id} />
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
            <span className="ms-auto flex flex-wrap items-center justify-end gap-2">
              <Button variant={party.status === "active" ? "danger" : "secondary"} busy={archive.isPending && !archiveAsk} onClick={startArchive}>
                {party.status === "active" ? t("parties.archive") : t("parties.unarchive")}
              </Button>
              <DeleteButton onDelete={() => api(`/api/parties/${party.id}`, { method: "DELETE" }).then(deleted)}
                onArchive={party.status === "active" ? startArchive : undefined} />
            </span>
          </div>
          <div className="sm:col-span-2"><ErrorNote error={save.error || archive.error} /></div>
        </form>
      </Card>
      <DangerZone party={party} onDeleted={deleted} />
      {archiveAsk && (
        <ArchiveDialog count={party.open_followups.length} busy={archive.isPending} error={archive.error}
          onArchive={(mode) => archive.mutate(mode)} onClose={() => setArchiveAsk(false)} />
      )}
    </div>
  );
}

/** Archive a party that still has open follow-ups: cancel them (default) or keep them in the command center. */
function ArchiveDialog({ count, busy, error, onArchive, onClose }: {
  count: number;
  busy: boolean;
  error: unknown;
  onArchive: (mode: "cancel" | "keep") => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const [mode, setMode] = useState<"cancel" | "keep">("cancel");
  return (
    <Modal open title={t("parties.archiveTitle")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="danger" busy={busy} onClick={() => onArchive(mode)}>{t("parties.archive")}</Button>
    </>}>
      <div className="flex flex-col gap-3 text-sm">
        <p>{t("parties.archiveOpenFollowups", { count: f.num(count) })}</p>
        <Segmented label={t("parties.archiveTitle")} value={mode} onChange={setMode}
          options={[{ value: "cancel", label: t("parties.archiveCancel") }, { value: "keep", label: t("parties.archiveKeep") }]} />
        <p className="text-xs text-muted">{mode === "cancel" ? t("parties.archiveCancelHint") : t("parties.archiveKeepHint")}</p>
        <ErrorNote error={error} />
      </div>
    </Modal>
  );
}

/** Test-data cleanup: deletes the party with its interactions, follow-ups and document links (files stay). */
function DangerZone({ party, onDeleted }: { party: PartyDetail; onDeleted: () => void }) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");
  const names = [party.name_fa, party.name_en].map((n) => (n ?? "").trim()).filter(Boolean);
  const purge = useMutation({
    mutationFn: () => api(`/api/parties/${party.id}`, { method: "DELETE", query: { cascade: true }, body: { confirm_name: typed.trim() } }),
    onSuccess: onDeleted,
  });
  return (
    <Card title={<span className="text-danger">{t("delete.dangerZone")}</span>} className="border-danger xl:col-start-2">
      <div className="flex flex-col gap-2 text-sm">
        <p>{t("delete.cascadeHint")}</p>
        <Field label={t("delete.typeName")} htmlFor="pd-purge">
          <Input id="pd-purge" dir="auto" autoComplete="off" value={typed} placeholder={names[0]} onChange={(e) => setTyped(e.target.value)} />
        </Field>
        <div>
          <Button variant="danger" icon="alert" disabled={!names.includes(typed.trim())} busy={purge.isPending} onClick={() => purge.mutate()}>
            {t("delete.cascadeButton")}
          </Button>
        </div>
        <ErrorNote error={purge.error} />
      </div>
    </Card>
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

/** Sends a method/contact; a 200 {created: false, shared_with} answer asks "Add anyway?" and resends with confirm_shared. */
function useSharedSubmit<T>(send: (confirm: boolean) => Promise<SharedResult<T>>, onCreated: () => void) {
  const [shared, setShared] = useState<SharedWith[] | null>(null);
  const mutation = useMutation({
    mutationFn: send,
    onSuccess: (res) => {
      if (!res.created) { setShared(res.shared_with); return; }
      setShared(null);
      onCreated();
    },
  });
  const prompt = shared && (
    <SharedNumberPrompt shared={shared} busy={mutation.isPending} onYes={() => mutation.mutate(true)} onNo={() => setShared(null)} />
  );
  return { mutation, prompt, reset: () => setShared(null) };
}

/** Value field for a contact method: the phone input for phone/WhatsApp, a plain field otherwise. */
function MethodValue({ type, value, region, onChange, id }: {
  type: string;
  value: string;
  region: string;
  onChange: (next: { value: string; region: string }) => void;
  id?: string;
}) {
  const { t } = useTranslation();
  if (isPhoneType(type)) return <PhoneInput id={id} className="min-w-64 flex-1" value={value} region={region} onChange={onChange} />;
  return <Input id={id} className="min-w-48 flex-1" dir="ltr" aria-label={t("contacts.value")} placeholder={t("contacts.value")} value={value}
    onChange={(e) => onChange({ value: e.target.value, region })} />;
}

function usePartyPhoneRegion(country: string | null) {
  const regions = usePhoneRegions();
  return defaultPhoneRegion(country, regions.data ?? []);
}

function MethodForm({ contactId, country, onDone }: { contactId: string; country: string | null; onDone: () => void }) {
  const { t } = useTranslation();
  const partyRegion = usePartyPhoneRegion(country);
  const [type, setType] = useState("whatsapp");
  const [value, setValue] = useState("");
  const [region, setRegion] = useState<string | null>(null);
  const { mutation: add, prompt, reset } = useSharedSubmit<ContactMethod>(
    (confirm) => api(`/api/contacts/${contactId}/methods`, {
      method: "POST",
      body: { type, value, region: isPhoneType(type) ? region ?? partyRegion : null, confirm_shared: confirm },
    }),
    () => { setValue(""); onDone(); },
  );
  return (
    <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); add.mutate(false); }}>
      <Select className="w-32" aria-label={t("contacts.methodType")} value={type} onChange={(e) => { setType(e.target.value); reset(); }}>
        {METHOD_TYPES.map((m) => <option key={m} value={m}>{t(`contacts.methods.${m}`)}</option>)}
      </Select>
      <MethodValue type={type} value={value} region={region ?? partyRegion}
        onChange={(next) => { setValue(next.value); setRegion(next.region); reset(); }} />
      <Button type="submit" icon="plus" disabled={!value.trim()} busy={add.isPending}>{t("common.add")}</Button>
      {prompt}
      {add.error ? <p className="w-full text-sm text-danger">{errorMessage(t, add.error)}</p> : null}
    </form>
  );
}

function ContactCard({ contact, partyId }: { contact: Contact; partyId: string }) {
  const { t } = useTranslation();
  const refresh = useRefresh(partyId);
  const party = useParty(partyId);
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
        <span className="ms-auto flex flex-wrap items-center justify-end gap-1">
          {!contact.is_primary && contact.status === "active" && <Button variant="ghost" onClick={() => makePrimary.mutate()}>{t("contacts.makePrimary")}</Button>}
          <Button variant="ghost" onClick={() => toggle.mutate()}>{contact.status === "active" ? t("parties.archive") : t("parties.unarchive")}</Button>
          <DeleteButton onDelete={() => api(`/api/contacts/${contact.id}`, { method: "DELETE" }).then(refresh)}
            onArchive={contact.status === "active" ? () => toggle.mutate() : undefined} />
        </span>
      </div>
      <ul className="mt-2 flex flex-col gap-1">
        {contact.methods.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-2 text-sm">
            <Badge>{t(`contacts.methods.${m.type}`)}</Badge>
            <span title={m.value} className={m.status === "archived" ? "line-through opacity-60" : ""}><Bdi ltr className="font-mono">{m.value_display || m.value}</Bdi></span>
            <span className="ms-auto flex items-center gap-3">
              <button type="button" className="text-xs text-muted hover:text-fg" onClick={() => toggleMethod.mutate(m)}>
                {m.status === "active" ? t("parties.archive") : t("parties.unarchive")}
              </button>
              <DeleteButton compact onDelete={() => api(`/api/contacts/methods/${m.id}`, { method: "DELETE" }).then(refresh)} />
            </span>
          </li>
        ))}
      </ul>
      {toggleMethod.error ? <p className="mt-1 text-sm text-danger">{errorMessage(t, toggleMethod.error)}</p> : null}
      {contact.status === "active" && <MethodForm contactId={contact.id} country={party.data?.country_iso2 ?? null} onDone={refresh} />}
    </li>
  );
}

const EMPTY_CONTACT = { name_fa: "", name_en: "", job_title: "", type: "whatsapp", value: "", region: null as string | null };

function Contacts({ party }: { party: PartyDetail }) {
  const { t } = useTranslation();
  const refresh = useRefresh(party.id);
  const partyRegion = usePartyPhoneRegion(party.country_iso2);
  const [form, setForm] = useState(EMPTY_CONTACT);
  const { mutation: create, prompt, reset } = useSharedSubmit<Contact>(
    (confirm) => api("/api/contacts", {
      method: "POST",
      body: {
        party_id: party.id, name_fa: form.name_fa || null, name_en: form.name_en || null, job_title: form.job_title || null,
        methods: form.value.trim()
          ? [{ type: form.type, value: form.value, region: isPhoneType(form.type) ? form.region ?? partyRegion : null }]
          : [],
        confirm_shared: confirm,
      },
    }),
    () => { setForm(EMPTY_CONTACT); refresh(); },
  );
  const set = (patch: Partial<typeof EMPTY_CONTACT>) => { setForm({ ...form, ...patch }); reset(); };
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Card title={t("contacts.title")}>
        {party.contacts.length === 0 ? <EmptyState>{t("contacts.empty")}</EmptyState> : (
          <ul className="flex flex-col gap-2">{party.contacts.map((c) => <ContactCard key={c.id} contact={c} partyId={party.id} />)}</ul>
        )}
      </Card>
      <Card title={t("contacts.add")}>
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(false); }}>
          <Field label={t("parties.nameFa")} htmlFor="ct-fa"><Input id="ct-fa" value={form.name_fa} onChange={(e) => set({ name_fa: e.target.value })} /></Field>
          <Field label={t("parties.nameEn")} htmlFor="ct-en"><Input id="ct-en" dir="ltr" value={form.name_en} onChange={(e) => set({ name_en: e.target.value })} /></Field>
          <Field label={t("contacts.jobTitle")} htmlFor="ct-job"><Input id="ct-job" value={form.job_title} onChange={(e) => set({ job_title: e.target.value })} /></Field>
          <div className="flex flex-wrap gap-2">
            <Select className="w-32" aria-label={t("contacts.methodType")} value={form.type} onChange={(e) => set({ type: e.target.value })}>
              {METHOD_TYPES.map((m) => <option key={m} value={m}>{t(`contacts.methods.${m}`)}</option>)}
            </Select>
            <MethodValue type={form.type} value={form.value} region={form.region ?? partyRegion}
              onChange={(next) => set({ value: next.value, region: next.region })} />
          </div>
          {prompt}
          {create.error ? <p className="w-full text-sm text-danger">{errorMessage(t, create.error)}</p> : null}
          <div><Button type="submit" variant="primary" disabled={!form.name_fa.trim() && !form.name_en.trim()} busy={create.isPending}>{t("common.add")}</Button></div>
        </form>
      </Card>
    </div>
  );
}

// ---- interactions -------------------------------------------------------------------------

const pad = (n: number) => String(n).padStart(2, "0");
const minute = (d: Date) => Math.floor(d.getTime() / 60_000);

/** Correct an interaction: text, and (v0.2.1) party, contact, channel, direction and time. */
function InteractionEditForm({ row, party, onDone }: { row: Interaction; party: PartyDetail; onDone: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();
  const original = new Date(row.occurred_at);
  const [target, setTarget] = useState<Party | null>(party);
  const [contactId, setContactId] = useState(row.contact_id ?? "");
  const [channel, setChannel] = useState<string>(row.channel);
  const [direction, setDirection] = useState<string>(row.direction);
  const [day, setDay] = useState<Date | null>(original);
  const [time, setTime] = useState(`${pad(original.getHours())}:${pad(original.getMinutes())}`);
  const [subject, setSubject] = useState(row.subject ?? "");
  const [body, setBody] = useState(row.body ?? "");
  const contacts = useQuery({
    queryKey: ["contacts", target?.id],
    queryFn: () => api<Contact[]>("/api/contacts", { query: { party_id: target!.id } }),
    enabled: !!target && target.id !== party.id,
  });
  const contactList = target?.id === party.id ? party.contacts : contacts.data ?? [];
  const occurredAt = (() => {
    if (!day || !/^\d{2}:\d{2}$/.test(time)) return null;
    const [h, m] = time.split(":").map(Number);
    return new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m);
  })();

  const save = useMutation({
    mutationFn: () => {
      const changes: Record<string, unknown> = {};
      if (subject !== (row.subject ?? "")) changes.subject = subject || null;
      if (body !== (row.body ?? "")) changes.body = body || null;
      if (target && target.id !== row.party_id) changes.party_id = target.id;
      if ((contactId || null) !== row.contact_id) changes.contact_id = contactId || null;
      if (channel !== row.channel) changes.channel = channel;
      if (direction !== row.direction) changes.direction = direction;
      if (occurredAt && minute(occurredAt) !== minute(original)) changes.occurred_at = occurredAt.toISOString();
      return api(`/api/interactions/${row.id}`, { method: "PATCH", body: changes });
    },
    onSuccess: () => {
      if (target && target.id !== row.party_id) toast(t("interactions.moved"), "success");
      for (const key of ["interactions", "interaction", "party", "parties", "command-center", "contacts"]) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
      onDone();
    },
  });
  const moving = !!target && target.id !== party.id;
  return (
    <form className="mt-2 flex flex-col gap-3 rounded-md border border-line p-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label={t("interactions.moveToParty")} htmlFor="ql-party">
        <PartyPicker value={target} onChange={(p) => { setTarget(p); setContactId(""); }} />
      </Field>
      {moving && <p className="text-xs text-muted">{t("interactions.moveHint")}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label={t("interactions.channel")} htmlFor={`ie-ch-${row.id}`}>
          <Select id={`ie-ch-${row.id}`} value={channel} onChange={(e) => setChannel(e.target.value)}>
            {CHANNELS.map((c) => <option key={c} value={c}>{t(`interactions.channels.${c}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("interactions.direction")} htmlFor={`ie-dir-${row.id}`}>
          <Select id={`ie-dir-${row.id}`} value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="in">{t("interactions.directions.in")}</option>
            <option value="out">{t("interactions.directions.out")}</option>
          </Select>
        </Field>
        <Field label={t("interactions.contact")} htmlFor={`ie-ct-${row.id}`}>
          <Select id={`ie-ct-${row.id}`} value={contactId} disabled={!target} onChange={(e) => setContactId(e.target.value)}>
            <option value="">—</option>
            {contactList.filter((c) => c.status === "active" || c.id === row.contact_id).map((c) => (
              <option key={c.id} value={c.id}>{(f.lang === "fa" ? c.name_fa || c.name_en : c.name_en || c.name_fa) ?? ""}</option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label={t("interactions.when")} htmlFor={`ie-day-${row.id}`}>
        <div className="flex flex-wrap items-center gap-2">
          <DateInput id={`ie-day-${row.id}`} value={day} onChange={setDay} />
          <Input type="time" dir="ltr" className="w-28" value={time} onChange={(e) => setTime(e.target.value)} aria-label={t("interactions.time")} />
        </div>
      </Field>
      <Field label={t("interactions.subject")} htmlFor={`ie-sub-${row.id}`}>
        <Input id={`ie-sub-${row.id}`} dir="auto" value={subject} onChange={(e) => setSubject(e.target.value)} />
      </Field>
      <Field label={t("interactions.body")} htmlFor={`ie-body-${row.id}`}>
        <Textarea id={`ie-body-${row.id}`} dir="auto" rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
      </Field>
      <p className="text-xs text-muted">{t("interactions.correctHint")}</p>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={!target || !occurredAt} busy={save.isPending}>{t("common.save")}</Button>
        <Button onClick={onDone}>{t("common.cancel")}</Button>
      </div>
      <ErrorNote error={save.error} />
    </form>
  );
}

function InteractionItem({ row, party, highlight }: { row: Interaction; party: PartyDetail; highlight: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ref = useRef<HTMLLIElement>(null);
  const [editing, setEditing] = useState(false);
  const detail = useQuery({ queryKey: ["interaction", row.id], queryFn: () => api<{ documents: { link_id: string; document_id: string; title: string }[] }>(`/api/interactions/${row.id}`) });
  useEffect(() => { if (highlight) ref.current?.scrollIntoView({ block: "center" }); }, [highlight]);
  const contact = party.contacts.find((c) => c.id === row.contact_id);
  return (
    <li ref={ref} className={`px-4 py-3 ${highlight ? "bg-accent-soft" : ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone="accent">{t(`interactions.channels.${row.channel}`)}</Badge>
        <Badge>{t(`interactions.directions.${row.direction}`)}</Badge>
        <span className="tabular-nums text-muted">{f.date(row.occurred_at, true)}</span>
        {contact && <Bdi className="text-muted">{contact.name_fa || contact.name_en}</Bdi>}
        <Link to={`/sourcing?from_interaction=${row.id}`} className="ms-auto text-xs text-accent hover:underline">{t("sourcing.inquiry.fromThisInteraction")}</Link>
        <button type="button" className="text-xs text-accent hover:underline" onClick={() => setEditing(!editing)}>{t("interactions.correct")}</button>
      </div>
      {editing ? <InteractionEditForm row={row} party={party} onDone={() => setEditing(false)} /> : (
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
          {list.data!.items.map((row) => <InteractionItem key={row.id} row={row} party={party} highlight={row.id === highlight} />)}
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
