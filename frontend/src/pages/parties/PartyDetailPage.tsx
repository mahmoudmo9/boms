import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Bdi, Button, Card, Checkbox, CodeChip, DateInput, EmptyState, errorMessage, ErrorNote, ErrorState, Field, Icon, IconButton, InlineAlert, Input, KpiTile, Loading, Modal, PageHeader, ProgressRing, Segmented, Select, Status, Tabs, Textarea, useToast, ValidatedInput } from "../../design/components";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { PartyFinance } from "./PartyFinance";
import { PhoneInput, usePhoneRegions } from "../../components/PhoneInput";
import { api, ApiError, type Page } from "../../lib/api";
import { defaultPhoneRegion, isPhoneType } from "../../lib/phone";
import { useFormat } from "../../lib/prefs";
import type { Contact, ContactMethod, DocumentDetail, EventItem, Followup, Interaction, Party, PartyDetail, QuoteRow, SharedResult, SharedWith } from "../../lib/types";
import { EventList } from "../events/EventLogPage";
import { CapabilitiesCard } from "../sourcing/Capabilities";
import { Money, StatusBadge } from "../sourcing/shared";
import { useCountries } from "./PartiesPage";
import { useQuickLog } from "./QuickLog";
import { CancelFollowupButton, CHANNELS, DeleteButton, FollowupActions, InUseNote, METHOD_TYPES, PartyName, ROLES, SharedNumberPrompt, StageSelect, stageLabel } from "./shared";
import { ContactField, CountryField, PartyField } from "../../components/fields";

const TABS = ["overview", "contacts", "interactions", "documents", "quotes", "orders", "finance", "history"] as const;
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
    website: party.website ?? "", notes: party.notes ?? "", national_id: party.national_id ?? "", economic_code: party.economic_code ?? "",
  });
  const [dnc, setDnc] = useState(party.do_not_contact);
  const [dncReason, setDncReason] = useState(party.do_not_contact_reason ?? "");
  const [newRole, setNewRole] = useState("");

  const save = useMutation({
    mutationFn: () => api(`/api/parties/${party.id}`, {
      method: "PATCH",
      body: { ...form, name_fa: form.name_fa || null, name_en: form.name_en || null, country_iso2: form.country_iso2 || null,
        website: form.website || null, notes: form.notes || null, national_id: form.national_id || null, economic_code: form.economic_code || null, do_not_contact: dnc, do_not_contact_reason: dnc ? dncReason : null },
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
      <Card title={<span className="flex items-center gap-2">{t("parties.details")} <CodeChip code={party.code} /></span>}>
        <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          <Field label={t("parties.nameFa")} htmlFor="pd-fa"><Input id="pd-fa" value={form.name_fa} onChange={(e) => setForm({ ...form, name_fa: e.target.value })} /></Field>
          <Field label={t("parties.nameEn")} htmlFor="pd-en"><Input id="pd-en" dir="ltr" value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} /></Field>
          <Field label={t("parties.kind")} htmlFor="pd-kind">
            <Select id="pd-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as "company" | "person" })}>
              <option value="company">{t("parties.kinds.company")}</option>
              <option value="person">{t("parties.kinds.person")}</option>
            </Select>
          </Field>
          <Field label={t("parties.country")} htmlFor="pd-country"><CountryField id="pd-country" value={form.country_iso2} onChange={(v) => setForm({ ...form, country_iso2: v })} /></Field>
          {/* v0.9.0: checked while typing (Iranian national ID check digit; Chinese USCC for CN parties) */}
          <Field label={t("finance.party.nationalId")} htmlFor="pd-nid">
            <ValidatedInput id="pd-nid" kind={party.country_iso2 === "CN" ? "uscc" : "national_id_ir"} value={form.national_id} testId="pd-national-id"
              onChange={(v) => setForm({ ...form, national_id: v })} /></Field>
          <Field label={t("finance.party.economicCode")} htmlFor="pd-eco"><Input id="pd-eco" dir="ltr" value={form.economic_code} onChange={(e) => setForm({ ...form, economic_code: e.target.value })} /></Field>
          <div className="sm:col-span-2"><Field label={t("parties.website")} htmlFor="pd-web"><Input id="pd-web" dir="ltr" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} /></Field></div>
          <div className="sm:col-span-2"><Field label={t("parties.notes")} htmlFor="pd-notes"><Textarea id="pd-notes" dir="auto" rows={4} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field></div>
          <div className="rounded-xl border border-line p-3 sm:col-span-2">
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
        {purge.error instanceof ApiError && purge.error.code === "in_use"
          ? <InUseNote counts={purge.error.details as Record<string, number>} /> : <ErrorNote error={purge.error} />}
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
    <li className={`rounded-xl border border-line p-3 ${contact.status === "archived" ? "opacity-60" : ""}`}>
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
    <form className="mt-2 flex flex-col gap-3 rounded-xl border border-line p-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label={t("interactions.moveToParty")} htmlFor="ql-party">
        <PartyField value={target} onChange={(p) => { setTarget(p); setContactId(""); }} />
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
          <ContactField id={`ie-ct-${row.id}`} contacts={contactList.filter((c) => c.status === "active" || c.id === row.contact_id)} value={contactId} disabled={!target} onChange={setContactId} />
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

/** Phase 6: quotes sent to this buyer, read-only; each row opens the quote in its case. */
function Quotes({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const list = useQuery({ queryKey: ["quotes", "party", partyId], queryFn: () => api<QuoteRow[]>(`/api/quotes?party_id=${partyId}`) });
  if (list.isLoading) return <Loading />;
  if (list.error || !list.data) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  return (
    <Card padded={false}>
      {list.data.length === 0 ? <EmptyState>{t("quotes.none")}</EmptyState> : (
        <div className="overflow-x-auto" data-testid="party-quotes">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
              <th className="p-2 text-start">{t("quotes.number")}</th><th className="p-2 text-start">{t("quotes.status")}</th>
              <th className="p-2 text-start">{t("quotes.total")}</th><th className="p-2 text-start">{t("quotes.validUntil")}</th><th className="p-2 text-start">{t("quotes.product.sent")}</th>
            </tr></thead>
            <tbody>{list.data.map((q) => (
              <tr key={q.id} className="border-b border-line">
                <td className="p-2"><Link to={`/cases/${q.case_id}?tab=quotes&quote=${q.id}`} className="text-accent hover:underline"><Bdi ltr>{q.number}</Bdi></Link></td>
                <td className="p-2"><StatusBadge group="quote" status={q.status} /></td>
                <td className="p-2"><Money amount={q.total} currency={q.currency} /></td>
                <td className="p-2 tabular-nums">{f.day(q.valid_until)}</td>
                <td className="p-2 tabular-nums text-muted">{q.sent_at ? f.date(q.sent_at) : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** v0.7.0: this party's sales orders (customer), purchase orders (supplier) and claims, read-only. */
function Orders({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  type Row = { id: string; case_id: string; number: string; status: string; currency: string; total: string; created_at: string; customer_ref?: string | null; supplier_ref?: string | null };
  const list = useQuery({ queryKey: ["party-execution", partyId], queryFn: () => api<{ sales_orders: Row[]; purchase_orders: Row[];
    claims: { id: string; case_id: string; kind: string; direction: string; status: string; opened_on: string }[] }>(`/api/parties/${partyId}/execution`) });
  if (list.isLoading) return <Loading />;
  if (list.error || !list.data) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  const table = (rows: Row[], tab: string, ref: "customer_ref" | "supplier_ref", testId: string) => rows.length === 0 ? <EmptyState>{t("execution.party.none")}</EmptyState> : (
    <div className="overflow-x-auto" data-testid={testId}><table className="w-full text-sm"><tbody>{rows.map((r) => (
      <tr key={r.id} className="border-b border-line">
        <td className="p-2"><Link to={`/cases/${r.case_id}?tab=${tab}`} className="text-accent hover:underline"><Bdi ltr>{r.number}</Bdi></Link></td>
        <td className="p-2">{t(`execution.${tab === "order" ? "order" : "purchase"}.statuses.${r.status}`)}</td>
        <td className="p-2"><Money amount={r.total} currency={r.currency} /></td>
        <td className="p-2"><Bdi ltr>{r[ref] ?? ""}</Bdi></td><td className="p-2 tabular-nums text-muted">{f.date(r.created_at)}</td>
      </tr>))}</tbody></table></div>
  );
  return (
    <div className="flex flex-col gap-4">
      <Card padded={false} title={t("execution.party.salesOrders")}>{table(list.data.sales_orders, "order", "customer_ref", "party-sales-orders")}</Card>
      <Card padded={false} title={t("execution.party.purchaseOrders")}>{table(list.data.purchase_orders, "purchase", "supplier_ref", "party-purchase-orders")}</Card>
      <Card padded={false} title={t("execution.party.claims")}>{list.data.claims.length === 0 ? <EmptyState>{t("execution.party.none")}</EmptyState> : (
        <ul className="divide-y divide-line">{list.data.claims.map((c) => (
          <li key={c.id} className="flex flex-wrap gap-2 px-4 py-2 text-sm"><Link to={`/cases/${c.case_id}?tab=delivery`} className="text-accent hover:underline">{t(`execution.claims.kinds.${c.kind}`)}</Link>
            <span>{t(`execution.claims.statuses.${c.status}`)}</span><span className="tabular-nums text-muted">{f.day(c.opened_on)}</span></li>))}</ul>)}</Card>
    </div>
  );
}

function History({ partyId }: { partyId: string }) {
  const events = useQuery({
    queryKey: ["events", "party", partyId],
    queryFn: () => api<Page<EventItem>>("/api/events", { query: { entity_type: "party", entity_id: partyId, page_size: 200 } }),
  });
  return <Card padded={false}><EventList items={events.data?.items ?? []} compact /></Card>;
}

function CountryName({ code }: { code: string }) {
  const f = useFormat();
  const countries = useCountries();
  const c = countries.data?.items.find((x) => x.iso2 === code);
  return <span className="inline-flex items-center gap-1"><Icon name="globe" size={13} />{c ? (f.lang === "fa" ? c.name_fa : c.name_en) : <bdi dir="ltr">{code}</bdi>}</span>;
}

/** v0.10.0 (ProParty): the party's scores, only from data BOMS has — the average of its ratings and its deals.
 * A tile with no data is not shown. On-time delivery, inspection results and RFQ response time are not computed
 * by BOMS yet, so they are not shown. */
function PartyScores({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const fin = useQuery({ queryKey: ["party-finance", partyId], queryFn: () => api<{ ratings: { count: number; average: Record<string, number | null> } }>(`/api/parties/${partyId}/finance`) });
  const ex = useQuery({ queryKey: ["party-execution", partyId], queryFn: () => api<{ sales_orders: unknown[]; purchase_orders: unknown[]; claims: { status: string }[] }>(`/api/parties/${partyId}/execution`) });
  const avg = Object.entries(fin.data?.ratings.average ?? {}).filter(([, v]) => v !== null) as [string, number][];
  const overall = avg.length ? avg.reduce((s, [, v]) => s + v, 0) / avg.length : null;
  const deals = (ex.data?.sales_orders.length ?? 0) + (ex.data?.purchase_orders.length ?? 0);
  const openClaims = ex.data?.claims.filter((c) => !["closed", "resolved", "rejected"].includes(c.status)).length ?? 0;
  if (overall === null && deals === 0) return null;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="party-scores">
      {overall !== null && (
        <article className="flex items-center gap-4 rounded-2xl border border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to px-5 py-4 xl:col-span-2">
          <ProgressRing value={(overall / 5) * 100} size={76} label={t("party.scores.overall")}><span className="text-lg text-title tabular-nums">{f.num(overall, 1)}</span></ProgressRing>
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="text-xs text-muted">{t("party.scores.overall")} · {t("party.scores.ratings", { n: f.num(fin.data!.ratings.count) })}</span>
            <span className="flex flex-wrap gap-x-4 gap-y-1 text-sm">{avg.map(([k, v]) => <span key={k}>{t(`finance.ratings.criteria.${k}`)} <b className="tabular-nums text-title">{f.num(v, 1)}</b></span>)}</span>
          </div>
        </article>
      )}
      {deals > 0 && <KpiTile label={t("party.scores.deals")} value={f.num(deals)} note={t("party.scores.dealsNote", { so: f.num(ex.data!.sales_orders.length), po: f.num(ex.data!.purchase_orders.length) })} />}
      {deals > 0 && <KpiTile label={t("party.scores.claims")} value={f.num(openClaims)} tone={openClaims ? "warning" : "neutral"} note={t("party.scores.claimsNote", { n: f.num(ex.data!.claims.length) })} />}
    </div>
  );
}

export function PartyDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const f = useFormat();
  const quickLog = useQuickLog();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "overview") as Tab;
  const party = useParty(id);
  if (party.isLoading) return <Loading rows={8} />;
  if (party.error || !party.data) return <ErrorState error={party.error} onRetry={() => void party.refetch()} />;
  const p = party.data;
  // the other-language name, only when both exist (PartyName already shows whichever one exists)
  const subtitle: ReactNode = p.name_fa && p.name_en ? (f.lang === "fa" ? p.name_en : p.name_fa) : null;
  return (
    <div className="flex flex-col gap-5" data-testid="party-page">
      <PageHeader title={<PartyName fa={p.name_fa} en={p.name_en} dnc={p.do_not_contact} />} code={p.code}
        breadcrumb={[{ label: t("nav.parties"), to: "/parties" }, { label: p.code ?? (f.lang === "fa" ? p.name_fa || p.name_en : p.name_en || p.name_fa) ?? "" }]}
        status={<>{p.status === "archived" && <Status tone="neutral">{t("parties.archived")}</Status>}
          {p.roles.map((r) => <Badge key={r.role} tone="accent">{t(`parties.roles.${r.role}`)} · {stageLabel(t, r.role, r.stage)}</Badge>)}</>}
        subtitle={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {subtitle && <Bdi>{subtitle}</Bdi>}
          {p.country_iso2 && <CountryName code={p.country_iso2} />}
          {p.website && <a href={p.website} target="_blank" rel="noreferrer" className="text-accent hover:underline"><bdi dir="ltr">{p.website.replace(/^https?:\/\//, "")}</bdi></a>}
        </span>}
        actions={<Button variant="primary" icon="plus" onClick={() => quickLog.open(p.id)}>{t("quicklog.button")}</Button>}>
        {p.do_not_contact && <InlineAlert tone="danger" title={t("parties.dncWarning")}>{p.do_not_contact_reason}</InlineAlert>}
        <PartyScores partyId={p.id} />
      </PageHeader>
      <Tabs label={t("nav.parties")} active={tab} onSelect={(key) => setParams({ tab: key }, { replace: true })} panelId="party-tab"
        tabs={TABS.filter((key) => key !== "quotes" || p.roles.some((r) => r.role === "buyer")).map((key) => ({ key, label: t(`parties.tabs.${key}`),
          count: key === "contacts" ? f.num(p.contacts.filter((c) => c.status === "active").length) : undefined }))} />
      <div id="party-tab" role="tabpanel" aria-label={t(`parties.tabs.${tab}`)} className="flex flex-col gap-4">
        {tab === "overview" && <Overview key={p.updated_at} party={p} />}
        {tab === "contacts" && <Contacts party={p} />}
        {tab === "interactions" && <Interactions party={p} highlight={params.get("interaction")} />}
        {tab === "documents" && <Documents party={p} />}
        {tab === "quotes" && <Quotes partyId={p.id} />}
        {tab === "orders" && <Orders partyId={p.id} />}
        {tab === "finance" && <PartyFinance partyId={p.id} />}
        {tab === "history" && <History partyId={p.id} />}
      </div>
    </div>
  );
}
