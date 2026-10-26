/** Offers: record form (item grid with keyboard navigation), list, comparison matrix, coverage. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, Fragment, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, Input, Modal, Select, Textarea } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import { flattenComparison, personName, validityTone } from "../../lib/sourcing";
import type { CaseDetail, ComparisonItem, Contact, Coverage, DocumentDetail, Offer, Party, Rfq } from "../../lib/types";
import { PartyPicker } from "../parties/QuickLog";
import { DueDatePicker, PartyName } from "../parties/shared";
import { ContactName, CurrencySelect, IncotermSelect, Money, OFFER_CHANNELS, StatusBadge, UnitInput, useInvalidateSourcing, useUnitLabel } from "../sourcing/shared";

interface Row {
  line_item_id: string;
  name: string;
  include: boolean;
  available: boolean;
  unit_price: string;
  price_per_quantity: string;
  unit_code: string | null;
  unit_text: string | null;
  moq: string;
  lead_time_days: string;
  spec_deviation: string;
}

const GRID_COLUMNS = ["unit_price", "price_per_quantity", "moq", "lead_time_days", "spec_deviation"] as const;

/** Enter / ArrowDown / ArrowUp move to the same column of the next / previous row. */
function gridKey(e: KeyboardEvent<HTMLInputElement>, row: number, column: string) {
  const delta = e.key === "Enter" || e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
  if (!delta) return;
  const next = document.querySelector<HTMLInputElement>(`[data-grid="${row + delta}-${column}"]`);
  if (next) { e.preventDefault(); next.focus(); next.select(); }
}

export function OfferForm({ caseData, onClose, onSaved, initialPartyId }: { caseData: CaseDetail; onClose: () => void; onSaved: () => void; initialPartyId?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const rfqs = useQuery({ queryKey: ["rfqs", caseData.id], queryFn: () => api<Rfq[]>("/api/rfqs", { query: { case_id: caseData.id } }) });
  const existing = useQuery({ queryKey: ["offers", caseData.id], queryFn: () => api<Offer[]>("/api/offers", { query: { case_id: caseData.id } }) });
  const [party, setParty] = useState<Party | null>(null);
  const [header, setHeader] = useState({
    channel: "email", currency: "USD" as string | null, incoterm: null as string | null, incoterm_place: "", valid_until: null as string | null,
    payment_terms: "", lead_time_days: "", compliance_notes: "", raw_text: "", received_at: null as string | null,
  });
  const [rows, setRows] = useState<Row[]>(() => caseData.items.filter((i) => i.status !== "cancelled").map((i) => ({
    line_item_id: i.id, name: i.name, include: true, available: true, unit_price: "", price_per_quantity: "1",
    unit_code: i.unit_code, unit_text: i.unit_text, moq: "", lead_time_days: "", spec_deviation: "",
  })));
  const [supersedes, setSupersedes] = useState("");
  const [noFollowup, setNoFollowup] = useState(true);
  const [reason, setReason] = useState(t("sourcing.offer.defaultNoFollowup"));
  const [action, setAction] = useState("");
  const [due, setDue] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const recipients = (rfqs.data ?? []).flatMap((r) => r.recipients);
  // the offer answers this RFQ recipient (if any): its contact is pre-selected (v0.3.2)
  const recipient = recipients.find((r) => r.party_id === party?.id && ["sent", "no_response"].includes(r.status));
  const contacts = useQuery({ queryKey: ["contacts", party?.id], queryFn: () => api<Contact[]>("/api/contacts", { query: { party_id: party!.id } }), enabled: !!party });
  const [contactId, setContactId] = useState("");
  useEffect(() => { setContactId(recipient?.contact_id ?? ""); }, [party?.id, recipient?.id, recipient?.contact_id]);
  useEffect(() => { if (initialPartyId) void api<Party>(`/api/parties/${initialPartyId}`).then(setParty); }, [initialPartyId]);
  const contactOptions = (contacts.data ?? []).filter((c) => c.status === "active" || c.id === contactId);
  const previous = (existing.data ?? []).filter((o) => o.party_id === party?.id && o.status === "active");
  const setRow = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (i === j ? { ...r, ...patch } : r)));

  const save = useMutation({
    mutationFn: async () => {
      const documentIds: string[] = [];
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        try { documentIds.push((await api<DocumentDetail>("/api/documents", { method: "POST", form })).id); }
        catch (err) { if (err instanceof ApiError && err.code === "duplicate_document") documentIds.push(String(err.details.id)); else throw err; }
      }
      return api("/api/offers", {
        method: "POST",
        body: {
          case_id: caseData.id, party_id: party!.id, channel: header.channel, currency: header.currency,
          incoterm: header.incoterm, incoterm_place: header.incoterm_place || null, valid_until: header.valid_until,
          payment_terms: header.payment_terms || null, lead_time_days: header.lead_time_days ? Number(header.lead_time_days) : null,
          compliance_notes: header.compliance_notes || null, raw_text: header.raw_text || null,
          received_at: header.received_at ? fromDateString(header.received_at).toISOString() : null,
          supersedes_offer_id: supersedes || null, document_ids: documentIds,
          rfq_recipient_id: recipient?.id ?? null, contact_id: contactId || null,
          followup: noFollowup ? null : { action, due_on: due },
          no_followup_reason: noFollowup ? reason : null,
          items: rows.filter((r) => r.include).map((r) => ({
            line_item_id: r.line_item_id, available: r.available, unit_price: r.available ? r.unit_price || null : null,
            price_per_quantity: r.price_per_quantity || "1", unit_code: r.unit_code, unit_text: r.unit_text,
            moq: r.moq || null, lead_time_days: r.lead_time_days ? Number(r.lead_time_days) : null, spec_deviation: r.spec_deviation || null,
          })),
        },
      });
    },
    onSuccess: () => { onSaved(); onClose(); },
  });
  const valid = party && header.currency && rows.some((r) => r.include) && rows.every((r) => !r.include || !r.available || r.unit_price)
    && (noFollowup ? reason.trim() : action.trim() && due);

  return (
    <Modal open wide title={t("sourcing.offer.record")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" busy={save.isPending} disabled={!valid} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto pe-1">
        <Field label={t("sourcing.offer.supplier")} htmlFor="ql-party"><PartyPicker value={party} onChange={(p) => { setParty(p); setSupersedes(""); setContactId(""); }} /></Field>
        {party && (
          <Field label={t("sourcing.offer.contact")} htmlFor="of-contact" hint={recipient?.contact_id ? t("sourcing.offer.contactFromRfq") : undefined}>
            <Select id="of-contact" value={contactId} onChange={(e) => setContactId(e.target.value)}>
              <option value="">{t("sourcing.offer.noContact")}</option>
              {contactOptions.map((c) => <option key={c.id} value={c.id}>{personName(c.name_fa, c.name_en, f.lang)}{c.status === "archived" ? ` (${t("parties.archived")})` : ""}</option>)}
            </Select>
          </Field>
        )}
        {recipients.length > 0 && !party && (
          <div className="flex flex-wrap gap-1.5">
            {recipients.filter((r) => r.status !== "draft").map((r) => (
              <button key={r.id} type="button" className="rounded-md border border-line px-2 py-1 text-sm hover:bg-surface-2"
                onClick={() => void api<Party>(`/api/parties/${r.party_id}`).then(setParty)}>
                <Bdi>{r.party_name_fa || r.party_name_en}</Bdi> <StatusBadge group="recipient" status={r.status} />
              </button>
            ))}
          </div>
        )}
        {previous.length > 0 && (
          <Field label={t("sourcing.offer.supersedes")} htmlFor="of-sup">
            <Select id="of-sup" value={supersedes} onChange={(e) => setSupersedes(e.target.value)}>
              <option value="">{t("sourcing.offer.keepPrevious")}</option>
              {previous.map((o) => <option key={o.id} value={o.id}>{t("sourcing.offer.previousOf", { date: o.received_at.slice(0, 10), currency: o.currency })}</option>)}
            </Select>
          </Field>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("sourcing.offer.channel")} htmlFor="of-ch">
            <Select id="of-ch" value={header.channel} onChange={(e) => setHeader({ ...header, channel: e.target.value })}>
              {OFFER_CHANNELS.map((c) => <option key={c} value={c}>{t(`sourcing.channels.${c}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("sourcing.currency")} htmlFor="of-cur"><CurrencySelect id="of-cur" className="w-full" allowEmpty={false} value={header.currency} onChange={(v) => setHeader({ ...header, currency: v })} /></Field>
          <Field label={t("sourcing.offer.received")} htmlFor="of-rec">
            <DateInput id="of-rec" value={header.received_at ? fromDateString(header.received_at) : null} onChange={(d) => setHeader({ ...header, received_at: d ? toDateString(d) : null })} />
          </Field>
          <Field label={t("sourcing.incoterm")} htmlFor="of-inco">
            <div className="flex gap-1.5"><IncotermSelect id="of-inco" value={header.incoterm} onChange={(v) => setHeader({ ...header, incoterm: v })} />
              <Input dir="auto" aria-label={t("sourcing.incotermPlace")} placeholder={t("sourcing.incotermPlace")} value={header.incoterm_place} onChange={(e) => setHeader({ ...header, incoterm_place: e.target.value })} /></div>
          </Field>
          <Field label={t("sourcing.offer.validUntil")} htmlFor="of-valid">
            <DateInput id="of-valid" value={header.valid_until ? fromDateString(header.valid_until) : null} onChange={(d) => setHeader({ ...header, valid_until: d ? toDateString(d) : null })} />
          </Field>
          <Field label={t("sourcing.offer.leadTime")} htmlFor="of-lead"><Input id="of-lead" dir="ltr" inputMode="numeric" value={header.lead_time_days} onChange={(e) => setHeader({ ...header, lead_time_days: e.target.value.replace(/\D/g, "") })} /></Field>
          <div className="sm:col-span-3"><Field label={t("sourcing.offer.paymentTerms")} htmlFor="of-pay"><Input id="of-pay" dir="auto" value={header.payment_terms} onChange={(e) => setHeader({ ...header, payment_terms: e.target.value })} /></Field></div>
        </div>
        <div className="shrink-0 overflow-x-auto rounded-md border border-line">
          <table className="w-full text-sm">
            <thead><tr className="bg-surface-2 text-xs text-muted">
              <th className="p-1.5 text-start">{t("sourcing.item.name")}</th>
              <th className="p-1.5 text-start">{t("sourcing.offer.available")}</th>
              <th className="p-1.5 text-start">{t("sourcing.offer.unitPrice")}</th>
              <th className="p-1.5 text-start">{t("sourcing.offer.per")}</th>
              <th className="p-1.5 text-start">{t("sourcing.item.unit")}</th>
              <th className="p-1.5 text-start">{t("sourcing.offer.moq")}</th>
              <th className="p-1.5 text-start">{t("sourcing.offer.leadTimeShort")}</th>
              <th className="p-1.5 text-start">{t("sourcing.offer.deviation")}</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.line_item_id} className={`border-t border-line ${r.include ? "" : "opacity-50"}`}>
                  <td className="p-1.5"><Checkbox label={<Bdi>{r.name}</Bdi>} checked={r.include} onChange={(v) => setRow(i, { include: v })} /></td>
                  <td className="p-1.5"><input type="checkbox" aria-label={t("sourcing.offer.available")} className="h-4 w-4 accent-[var(--accent)]" checked={r.available} disabled={!r.include} onChange={(e) => setRow(i, { available: e.target.checked })} /></td>
                  {GRID_COLUMNS.slice(0, 2).map((c) => (
                    <td key={c} className="p-1.5"><Input data-grid={`${i}-${c}`} dir="ltr" className={c === "unit_price" ? "w-28" : "w-20"} inputMode="decimal" aria-label={t(`sourcing.offer.grid.${c}`)}
                      disabled={!r.include || !r.available} value={r[c]} onKeyDown={(e) => gridKey(e, i, c)} onChange={(e) => setRow(i, { [c]: e.target.value })} /></td>
                  ))}
                  <td className="p-1.5"><UnitInput code={r.unit_code} text={r.unit_text} onChange={(u) => setRow(i, u)} /></td>
                  {GRID_COLUMNS.slice(2).map((c) => (
                    <td key={c} className="p-1.5"><Input data-grid={`${i}-${c}`} dir={c === "spec_deviation" ? "auto" : "ltr"} className={c === "spec_deviation" ? "w-40" : "w-20"} aria-label={t(`sourcing.offer.grid.${c}`)}
                      disabled={!r.include} value={r[c]} onKeyDown={(e) => gridKey(e, i, c)} onChange={(e) => setRow(i, { [c]: e.target.value })} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted">{t("sourcing.offer.gridHint")}</p>
        <Field label={t("sourcing.offer.compliance")} htmlFor="of-comp"><Input id="of-comp" dir="auto" value={header.compliance_notes} onChange={(e) => setHeader({ ...header, compliance_notes: e.target.value })} /></Field>
        <Field label={t("sourcing.offer.rawText")} htmlFor="of-raw" hint={t("sourcing.inquiry.rawTextHint")}><Textarea id="of-raw" dir="auto" rows={4} value={header.raw_text} onChange={(e) => setHeader({ ...header, raw_text: e.target.value })} /></Field>
        <Field label={t("sourcing.offer.files")} htmlFor="of-files">
          <input id="of-files" type="file" multiple className="text-sm" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </Field>
        <fieldset className="rounded-md border border-line p-3">
          <legend className="px-1 text-sm font-semibold">{t("quicklog.nextAction")} *</legend>
          <Checkbox label={t("quicklog.noFollowup")} checked={noFollowup} onChange={setNoFollowup} />
          {noFollowup ? <Input className="mt-2" dir="auto" aria-label={t("quicklog.noFollowupReason")} value={reason} onChange={(e) => setReason(e.target.value)} /> : (
            <div className="mt-2 flex flex-col gap-2">
              <Input dir="auto" aria-label={t("followups.action")} placeholder={t("followups.actionPlaceholder")} value={action} onChange={(e) => setAction(e.target.value)} />
              <DueDatePicker value={due} onChange={setDue} />
            </div>
          )}
        </fieldset>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

export function OffersTab({ caseData, highlight, recordFor }: { caseData: CaseDetail; highlight: string | null; recordFor?: string | null }) {
  const { t } = useTranslation();
  const f = useFormat();
  const unitLabel = useUnitLabel();
  const invalidate = useInvalidateSourcing();
  const [recording, setRecording] = useState(!!recordFor);
  const offers = useQuery({ queryKey: ["offers", caseData.id], queryFn: () => api<Offer[]>("/api/offers", { query: { case_id: caseData.id } }) });
  const refresh = () => { void offers.refetch(); invalidate(); };
  const withdraw = useMutation({ mutationFn: (id: string) => api(`/api/offers/${id}/status`, { method: "POST", body: { status: "withdrawn" } }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/offers/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const names = Object.fromEntries(caseData.items.map((i) => [i.id, i.name]));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end"><Button variant="primary" icon="plus" onClick={() => setRecording(true)}>{t("sourcing.offer.record")}</Button></div>
      <ErrorNote error={offers.error || withdraw.error || remove.error} />
      {(offers.data ?? []).length === 0 && !offers.isLoading && <Card><EmptyState>{t("sourcing.offer.empty")}</EmptyState></Card>}
      {(offers.data ?? []).map((o) => (
        <Card key={o.id} className={o.id === highlight ? "border-accent" : ""}
          title={<span className="flex flex-wrap items-center gap-2"><PartyName fa={o.party_name_fa} en={o.party_name_en} id={o.party_id} />
            <ContactName fa={o.contact_name_fa} en={o.contact_name_en} />
            <StatusBadge group="offer" status={o.status} />{!o.valid && o.status === "active" && <Badge tone="danger">{t("sourcing.offer.pastValidity")}</Badge>}</span>}
          actions={<>
            {o.status === "active" && <Button variant="ghost" onClick={() => withdraw.mutate(o.id)}>{t("sourcing.offer.withdraw")}</Button>}
            <Button variant="ghost" onClick={() => remove.mutate(o.id)}>{t("delete.button")}</Button>
          </>}>
          <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
            <span>{t(`sourcing.channels.${o.channel}`)} · <span className="tabular-nums">{f.date(o.received_at)}</span></span>
            <span><Bdi ltr>{o.currency}</Bdi>{o.incoterm && <> · <Bdi ltr>{o.incoterm} {o.incoterm_place ?? ""}</Bdi></>}</span>
            {o.valid_until && <span>{t("sourcing.offer.validUntil")}: <span className="tabular-nums">{f.day(o.valid_until)}</span></span>}
            {o.payment_terms && <span dir="auto">{o.payment_terms}</span>}
          </div>
          <ul className="flex flex-col gap-1 text-sm">
            {o.items.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-2">
                <Bdi className="font-medium">{names[i.line_item_id] ?? ""}</Bdi>
                {i.available ? <Money amount={i.unit_price} currency={o.currency} per={i.price_per_quantity} unit={unitLabel(i.unit_code, i.unit_text)} />
                  : <Badge tone="danger">{t("sourcing.offer.notAvailable")}</Badge>}
                {i.moq && <span className="text-xs text-muted">MOQ <Bdi ltr>{f.num(i.moq)}</Bdi></span>}
                {i.spec_deviation && <Badge tone="warning">{i.spec_deviation}</Badge>}
              </li>
            ))}
          </ul>
          {o.documents.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2">{o.documents.map((d) => (
              <li key={d.link_id}><Link to={`/documents/${d.document_id}`} className="inline-flex items-center gap-1 text-sm text-accent hover:underline"><Icon name="file" size={14} /><Bdi>{d.title}</Bdi></Link></li>
            ))}</ul>
          )}
        </Card>
      ))}
      {recording && <OfferForm caseData={caseData} initialPartyId={recordFor ?? undefined} onClose={() => setRecording(false)} onSaved={refresh} />}
    </div>
  );
}

function SelectButton({ itemId, offerItemId, current, onDone }: { itemId: string; offerItemId: string; current: string | null; onDone: () => void }) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const select = useMutation({
    mutationFn: () => api(`/api/line-items/${itemId}/select`, { method: "POST", body: { offer_item_id: offerItemId, reason: reason || null } }),
    onSuccess: () => { setAsking(false); onDone(); },
  });
  if (current === offerItemId) return <Badge tone="success">{t("sourcing.compare.selected")}</Badge>;
  return (
    <>
      <Button onClick={() => (current ? setAsking(true) : select.mutate())} busy={select.isPending}>{t("sourcing.compare.select")}</Button>
      {asking && (
        <Modal open title={t("sourcing.compare.changeTitle")} onClose={() => setAsking(false)}
          footer={<><Button onClick={() => setAsking(false)}>{t("common.cancel")}</Button>
            <Button variant="primary" disabled={!reason.trim()} busy={select.isPending} onClick={() => select.mutate()}>{t("sourcing.compare.select")}</Button></>}>
          <Field label={t("sourcing.reason")} htmlFor="sel-reason"><Input id="sel-reason" dir="auto" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        </Modal>
      )}
      {select.error && !asking ? <ErrorNote error={select.error} /> : null}
    </>
  );
}

export function ComparisonMatrix({ item, onChanged }: { item: ComparisonItem; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const unitLabel = useUnitLabel();
  const lines = flattenComparison(item);
  const unitGroupLabel = (g: string) => (g.startsWith("kind:") ? t(`sourcing.compare.kinds.${g.slice(5)}`) : g.startsWith("unit:") ? unitLabel(g.slice(5)) : g.startsWith("text:") ? g.slice(5) : t("sourcing.compare.noUnit"));
  return (
    <Card padded={false} title={<span className="flex flex-wrap items-center gap-2"><Bdi>{item.name}</Bdi><StatusBadge group="item" status={item.status} />
      {item.quantity && <span className="text-xs font-normal text-muted"><Bdi>{f.num(item.quantity)} {unitLabel(item.unit_code, item.unit_text)}</Bdi></span>}</span>}>
      {lines.length === 0 ? <EmptyState>{t("sourcing.compare.noOffers")}</EmptyState> : (
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead><tr className="text-xs text-muted">
              <th className="sticky start-0 z-10 border-b border-line bg-surface-2 p-2 text-start">{t("sourcing.offer.supplier")}</th>
              {["price", "incoterm", "moq", "leadTime", "payment", "validity", "compliance", "deviation", "documents", ""].map((h) => (
                <th key={h} className="border-b border-line bg-surface-2 p-2 text-start whitespace-nowrap">{h ? t(`sourcing.compare.columns.${h}`) : ""}</th>
              ))}
            </tr></thead>
            <tbody>
              {lines.map((line, i) => line.kind === "group" ? (
                <tr key={`g${i}`}><td colSpan={11} className="border-b border-line bg-surface-2/50 px-2 py-1 text-xs font-medium">
                  <Bdi ltr>{line.currency}</Bdi> · {unitGroupLabel(line.unitGroup)}
                  {!line.comparable && <span className="ms-2"><Badge tone="warning">{t("sourcing.compare.notComparable")}</Badge></span>}
                </td></tr>
              ) : (
                <tr key={line.offer_item_id} className={line.selected ? "bg-success-soft" : line.lowest ? "bg-accent-soft" : ""}>
                  <td className="sticky start-0 z-10 border-b border-line bg-surface p-2">
                    <PartyName fa={line.party_name_fa} en={line.party_name_en} id={line.party_id} className="max-w-48" />
                    <ContactName fa={line.contact_name_fa} en={line.contact_name_en} className="block max-w-48 text-xs" />
                  </td>
                  <td className="border-b border-line p-2">
                    <div className="flex flex-wrap items-center gap-1">
                      <Money amount={line.unit_price} currency={line.currency} per={line.price_per_quantity} unit={unitLabel(line.unit_code, line.unit_text)} />
                      {line.lowest && <Badge tone="accent">{t("sourcing.compare.lowest")}</Badge>}
                      {line.badges.map((b) => <Badge key={b} tone="warning">{t(`sourcing.compare.badges.${b}`)}</Badge>)}
                    </div>
                  </td>
                  <td className="border-b border-line p-2"><Bdi ltr>{[line.incoterm, line.incoterm_place].filter(Boolean).join(" ")}</Bdi></td>
                  <td className="border-b border-line p-2"><Bdi ltr>{line.moq ? `${f.num(line.moq)} ${line.moq_unit ?? ""}` : ""}</Bdi></td>
                  <td className="border-b border-line p-2 tabular-nums">{line.lead_time_days !== null ? t("sourcing.compare.days", { n: f.num(line.lead_time_days) }) : ""}</td>
                  <td className="border-b border-line p-2" dir="auto">{line.payment_terms ?? ""}</td>
                  <td className="border-b border-line p-2 whitespace-nowrap">
                    {line.valid_until && <span className={validityTone(line.days_left) === "danger" ? "font-medium text-danger" : validityTone(line.days_left) === "warning" ? "text-warning" : ""}>
                      {f.day(line.valid_until)} ({t("sourcing.compare.daysLeft", { n: f.num(line.days_left ?? 0) })})</span>}
                  </td>
                  <td className="border-b border-line p-2 text-xs" dir="auto">{line.compliance_notes ?? ""}</td>
                  <td className="border-b border-line p-2 text-xs" dir="auto">{line.spec_deviation ?? ""}</td>
                  <td className="border-b border-line p-2">{line.documents.map((d) => <Link key={d.link_id} to={`/documents/${d.document_id}`} title={d.title} className="text-accent"><Icon name="file" size={14} /></Link>)}</td>
                  <td className="border-b border-line p-2"><SelectButton itemId={item.item_id} offerItemId={line.offer_item_id} current={item.selected_offer_item_id} onDone={onChanged} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function ComparisonTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const invalidate = useInvalidateSourcing();
  const [itemId, setItemId] = useState("");
  const comparison = useQuery({
    queryKey: ["comparison", caseData.id],
    queryFn: () => api<{ items: ComparisonItem[] }>(`/api/cases/${caseData.id}/comparison`),
  });
  const refresh = () => { void comparison.refetch(); invalidate(); };
  const items = (comparison.data?.items ?? []).filter((i) => i.status !== "cancelled" && (!itemId || i.item_id === itemId));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select className="w-72" aria-label={t("sourcing.compare.item")} value={itemId} onChange={(e) => setItemId(e.target.value)}>
          <option value="">{t("sourcing.compare.allItems")}</option>
          {(comparison.data?.items ?? []).map((i) => <option key={i.item_id} value={i.item_id}>{i.name}</option>)}
        </Select>
        <span className="text-xs text-muted">{t("sourcing.compare.noFx")}</span>
      </div>
      <ErrorNote error={comparison.error} />
      {items.map((i) => <Fragment key={i.item_id}><ComparisonMatrix item={i} onChanged={refresh} /></Fragment>)}
    </div>
  );
}

export function CoverageCard({ caseId, onChanged }: { caseId: string; onChanged: () => void }) {
  const { t } = useTranslation();
  const coverage = useQuery({ queryKey: ["coverage", caseId], queryFn: () => api<Coverage>(`/api/cases/${caseId}/coverage`) });
  const unitLabel = useUnitLabel();
  const [marking, setMarking] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const mark = useMutation({
    mutationFn: () => api(`/api/line-items/${marking}/no-coverage`, { method: "POST", body: { reason } }),
    onSuccess: () => { setMarking(null); setReason(""); void coverage.refetch(); onChanged(); },
  });
  const data = coverage.data;
  if (!data) return null;
  return (
    <Card padded={false} title={<span className="flex items-center gap-2">{t("sourcing.coverage.title")}
      {data.gate.ok ? <Badge tone="success">{t("sourcing.coverage.gateOk")}</Badge> : <Badge tone="warning">{t("sourcing.coverage.gateMissing", { count: data.gate.missing.length })}</Badge>}</span>}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
            <th className="p-2 text-start">{t("sourcing.item.name")}</th>
            <th className="p-2 text-start">{t("sourcing.status.label")}</th>
            <th className="p-2 text-start">{t("sourcing.coverage.validOffers")}</th>
            <th className="p-2 text-start">{t("sourcing.coverage.bestPrices")}</th>
            <th className="p-2" />
          </tr></thead>
          <tbody>
            {data.items.filter((i) => i.status !== "cancelled").map((i) => (
              <tr key={i.item_id} className="border-b border-line">
                <td className="p-2"><Bdi>{i.name}</Bdi></td>
                <td className="p-2"><div className="flex flex-wrap gap-1"><StatusBadge group="item" status={i.status} />{i.no_coverage_confirmed && <Badge tone="danger">{t("sourcing.noCoverage")}</Badge>}{i.selection_lost && <Badge tone="warning">{t("sourcing.selectionLost")}</Badge>}</div></td>
                <td className="p-2 tabular-nums">{i.valid_offers}</td>
                <td className="p-2"><div className="flex flex-col gap-0.5">{i.best_prices.map((b) => <Money key={`${b.currency}${b.unit_group}`} amount={b.unit_price} currency={b.currency} per={b.price_per_quantity} unit={unitLabel(b.unit_code, b.unit_text)} />)}</div></td>
                <td className="p-2 text-end">{!i.no_coverage_confirmed && i.status !== "selected" && <Button variant="ghost" onClick={() => setMarking(i.item_id)}>{t("sourcing.markNoCoverage")}</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data.gate.ok && data.gate.missing.length > 0 && (
        <p className="px-4 py-2 text-xs text-muted">{t("sourcing.coverage.missingList")}: {data.gate.missing.map((m) => m.name).join("، ")}</p>
      )}
      {marking && (
        <Modal open title={t("sourcing.markNoCoverage")} onClose={() => setMarking(null)}
          footer={<><Button onClick={() => setMarking(null)}>{t("common.cancel")}</Button>
            <Button variant="primary" disabled={!reason.trim()} busy={mark.isPending} onClick={() => mark.mutate()}>{t("common.save")}</Button></>}>
          <Field label={t("sourcing.reason")} htmlFor="nc-reason"><Input id="nc-reason" dir="auto" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <ErrorNote error={mark.error} />
        </Modal>
      )}
    </Card>
  );
}
