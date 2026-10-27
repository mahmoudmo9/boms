/** Building blocks shared by the inquiry, case, RFQ, offer and catalog pages. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, IconButton, Input, Select, Spinner } from "../../components/ui";
import { api, ApiError, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import { personName } from "../../lib/sourcing";
import type { Currency, DocumentDetail, EventItem, LinkedDocument, PaymentTerm, Product, Unit } from "../../lib/types";
import { EventList } from "../events/EventLogPage";
import { InUseNote } from "../parties/shared";

export const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"] as const;
export const SOURCE_CHANNELS = ["whatsapp", "email", "phone", "tender_portal", "in_person", "letter", "other"] as const;
export const INQUIRY_KINDS = ["rfq", "tender", "direct_order", "other"] as const;
export const RFQ_CHANNELS = ["email", "whatsapp", "letter", "phone", "other"] as const;
export const OFFER_CHANNELS = ["email", "whatsapp", "wechat", "phone", "letter", "other"] as const;

const TONES: Record<string, "neutral" | "success" | "danger" | "warning" | "accent"> = {
  uncovered: "warning", rfq_sent: "accent", has_offer: "accent", selected: "success", cancelled: "neutral",
  new: "accent", needs_info: "warning", ready_for_screening: "accent", rejected: "danger", no_reply: "neutral",
  converted: "success", open: "accent", won: "success", lost: "danger", closed: "neutral",
  draft: "neutral", sent: "accent", answered: "success", no_response: "warning", expired: "neutral",
  replied: "success", declined: "neutral", active: "success", superseded: "neutral", withdrawn: "neutral",
  final: "success", approved: "accent", accepted: "success", partially_accepted: "warning", negotiating: "accent",
};

/** Status badge; ``group`` picks the i18n vocabulary (item, inquiry, case, rfq, recipient, offer). */
export function StatusBadge({ group, status }: { group: string; status: string }) {
  const { t } = useTranslation();
  return <Badge tone={TONES[status] ?? "neutral"}>{t(`sourcing.status.${group}.${status}`)}</Badge>;
}

export function useUnits() {
  return useQuery({
    queryKey: ["basedata", "units", "active"],
    queryFn: () => api<Page<Unit>>("/api/basedata/units", { query: { active: true, page_size: 500 } }),
    staleTime: 5 * 60_000,
  });
}

export function useCurrencies() {
  return useQuery({
    queryKey: ["basedata", "currencies", "active"],
    queryFn: () => api<Page<Currency>>("/api/basedata/currencies", { query: { active: true, page_size: 500 } }),
    staleTime: 5 * 60_000,
  });
}

export function usePaymentTerms() {
  return useQuery({ queryKey: ["sourcing", "payment-terms"], queryFn: () => api<PaymentTerm[]>("/api/inquiries/payment-terms"), staleTime: Infinity });
}

export function useUnitLabel() {
  const units = useUnits();
  const f = useFormat();
  return (code: string | null | undefined, text?: string | null) => {
    if (!code) return text ?? "";
    const unit = units.data?.items.find((u) => u.code === code);
    return unit ? (f.lang === "fa" ? unit.name_fa : unit.name_en) : code;
  };
}

/** Unit: a sys.unit code, or free text when no unit matches ("barrels of 200 l"). */
export function UnitInput({ code, text, onChange, id }: {
  code: string | null;
  text: string | null;
  onChange: (v: { unit_code: string | null; unit_text: string | null }) => void;
  id?: string;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const units = useUnits();
  const [free, setFree] = useState(!code && !!text);
  return (
    <div className="flex min-w-0 gap-1.5">
      <Select id={id} className="w-36 shrink-0" aria-label={t("sourcing.item.unit")} value={free ? "__text" : code ?? ""}
        onChange={(e) => {
          if (e.target.value === "__text") { setFree(true); onChange({ unit_code: null, unit_text: text ?? "" }); }
          else { setFree(false); onChange({ unit_code: e.target.value || null, unit_text: null }); }
        }}>
        <option value="">—</option>
        {(units.data?.items ?? []).map((u) => <option key={u.code} value={u.code}>{f.lang === "fa" ? u.name_fa : u.name_en}</option>)}
        <option value="__text">{t("sourcing.item.unitOther")}</option>
      </Select>
      {free && <Input className="min-w-0 flex-1" aria-label={t("sourcing.item.unitText")} value={text ?? ""} maxLength={300}
        onChange={(e) => onChange({ unit_code: null, unit_text: e.target.value })} />}
    </div>
  );
}

export function CurrencySelect({ value, onChange, id, allowEmpty = true, className = "w-28" }: {
  value: string | null;
  onChange: (v: string | null) => void;
  id?: string;
  allowEmpty?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const currencies = useCurrencies();
  const common = ["USD", "EUR", "AED", "CNY", "IRR", "TRY", "RUB", "INR"];
  const rows = currencies.data?.items ?? [];
  const sorted = [...rows.filter((c) => common.includes(c.code)).sort((a, b) => common.indexOf(a.code) - common.indexOf(b.code)),
    ...rows.filter((c) => !common.includes(c.code))];
  return (
    <Select id={id} dir="ltr" className={className} aria-label={t("sourcing.currency")} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      {allowEmpty && <option value="">—</option>}
      {sorted.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
    </Select>
  );
}

export function IncotermSelect({ value, onChange, id }: { value: string | null; onChange: (v: string | null) => void; id?: string }) {
  const { t } = useTranslation();
  return (
    <Select id={id} dir="ltr" className="w-24" aria-label={t("sourcing.incoterm")} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">—</option>
      {INCOTERMS.map((i) => <option key={i} value={i}>{i}</option>)}
    </Select>
  );
}

/** Money: always amount + currency, left-to-right. */
export function Money({ amount, currency, per, unit }: { amount: string | null | undefined; currency?: string | null; per?: string | null; unit?: string }) {
  const f = useFormat();
  if (amount === null || amount === undefined) return null;
  const basis = per && Number(per) !== 1 ? ` / ${f.num(per)}` : "";
  return <Bdi ltr className="tabular-nums whitespace-nowrap">{f.num(amount)} {currency ?? ""}{basis}{unit ? ` ${unit}` : ""}</Bdi>;
}

export function productName(p: { name_fa: string | null; name_en: string | null }, lang: string) {
  return ((lang === "fa" ? p.name_fa || p.name_en : p.name_en || p.name_fa) ?? "");
}

/** Search-as-you-type product picker. */
export function ProductPicker({ value, onChange, id }: { value: string | null; onChange: (id: string | null, product?: Product) => void; id?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const current = useQuery({
    queryKey: ["products", "one", value],
    queryFn: () => api<Product>(`/api/products/${value}`),
    enabled: !!value,
  });
  const results = useQuery({
    queryKey: ["products", "picker", q],
    queryFn: () => api<Page<Product>>("/api/products", { query: { q, page_size: 8 } }),
    enabled: open && q.trim().length > 0,
  });
  if (value) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-line-strong px-2.5 py-1">
        <Link to={`/sourcing/catalog/${value}`} className="truncate text-sm text-accent hover:underline"><Bdi>{current.data ? productName(current.data, f.lang) : "…"}</Bdi></Link>
        <button type="button" className="ms-auto text-xs text-muted hover:text-fg" onClick={() => onChange(null)}>{t("sourcing.unlinkProduct")}</button>
      </div>
    );
  }
  return (
    <div className="relative">
      <Input id={id} type="search" placeholder={t("sourcing.productSearch")} value={q} onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} />
      {open && q.trim() && (
        <div className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-y-auto rounded-md border border-line bg-surface shadow-lg">
          {results.isFetching && <div className="p-2"><Spinner size={14} /></div>}
          {(results.data?.items ?? []).map((p) => (
            <button key={p.id} type="button" className="flex w-full items-center gap-2 px-2.5 py-1.5 text-start text-sm hover:bg-surface-2"
              onClick={() => { onChange(p.id, p); setOpen(false); setQ(""); }}>
              <Bdi>{productName(p, f.lang)}</Bdi>
              {p.hs_code && <Bdi ltr className="ms-auto font-mono text-xs text-muted">{p.hs_code}</Bdi>}
            </button>
          ))}
          {results.data && results.data.items.length === 0 && <div className="p-2 text-sm text-muted">{t("search.noResults")}</div>}
        </div>
      )}
    </div>
  );
}

/** Upload + link files to an entity (inquiry, case, line item, offer) and list them. */
export function AttachedDocuments({ documents, linkPath, onChanged, title, compact }: {
  documents: LinkedDocument[];
  linkPath: string;
  onChanged: () => void;
  title?: ReactNode;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const attach = async (files: File[]) => {
    setError(null);
    setBusy(true);
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
      await api(linkPath, { method: "POST", body: { document_id: id } }).catch(setError);
    }
    setBusy(false);
    onChanged();
  };
  const unlink = useMutation({
    mutationFn: (d: LinkedDocument) => api(`${linkPath}/${d.link_id}`, { method: "DELETE" }),
    onSuccess: onChanged,
  });
  const body = (
    <>
      <ErrorNote error={error || unlink.error} />
      {documents.length === 0 ? (compact ? null : <EmptyState>{t("parties.noDocuments")}</EmptyState>) : (
        <ul className="divide-y divide-line">
          {documents.map((d) => (
            <li key={d.link_id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
              <Link to={`/documents/${d.document_id}`} className="inline-flex items-center gap-1 font-medium text-accent hover:underline"><Icon name="file" size={14} /><Bdi>{d.title}</Bdi></Link>
              <span className="tabular-nums text-muted">{f.bytes(d.size_bytes)}</span>
              <IconButton icon="x" label={t("documents.unlink")} className="ms-auto" onClick={() => unlink.mutate(d)} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
  const button = (
    <>
      <input ref={input} type="file" multiple hidden onChange={(e) => { if (e.target.files) void attach(Array.from(e.target.files)); e.target.value = ""; }} />
      <Button icon="upload" busy={busy} onClick={() => input.current?.click()}>{t("parties.attach")}</Button>
    </>
  );
  if (compact) return <div className="flex flex-col gap-2"><div>{button}</div>{body}</div>;
  return <Card padded={false} title={title ?? t("parties.documents")} actions={button}>{body}</Card>;
}

export function HistoryCard({ entityType, entityId, title }: { entityType: string; entityId: string; title?: ReactNode }) {
  const events = useQuery({
    queryKey: ["events", entityType, entityId],
    queryFn: () => api<Page<EventItem>>("/api/events", { query: { entity_type: entityType, entity_id: entityId, page_size: 200 } }),
  });
  return <Card padded={false} title={title}><EventList items={events.data?.items ?? []} compact /></Card>;
}

/** Spec-key suggestions (keys used before), for the <datalist> of the specs editor. */
export function useSpecKeys() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(q), 200);
    return () => window.clearTimeout(id);
  }, [q]);
  const keys = useQuery({
    queryKey: ["sourcing", "spec-keys", debounced],
    queryFn: () => api<string[]>("/api/line-items/spec-keys", { query: { q: debounced, limit: 30 } }),
    staleTime: 30_000,
  });
  return { keys: keys.data ?? [], setQuery: setQ };
}

export function useInvalidateSourcing() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["inquiry", "inquiries", "case", "cases", "rfqs", "offers", "coverage", "comparison", "products", "command-center",
      "events", "interactions", "party", "costing", "cost-sheet", "case-quotes", "quote", "quotes"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

/** Test-data cleanup (v0.3.1): DELETE ?cascade=true after typing the exact title; files and interactions stay. */
export function CascadeDeleteCard({ url, confirmKey, expected, hint, typeLabel, button, onDeleted }: {
  url: string;
  confirmKey: "confirm_title" | "confirm_subject";
  expected: string;
  hint: string;
  typeLabel: string;
  button: string;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");
  const purge = useMutation({
    mutationFn: () => api(url, { method: "DELETE", query: { cascade: true }, body: { [confirmKey]: typed.trim() } }),
    onSuccess: onDeleted,
  });
  const inUse = purge.error instanceof ApiError && purge.error.code === "in_use" ? (purge.error.details as Record<string, number>) : null;
  return (
    <Card title={<span className="text-danger">{t("delete.dangerZone")}</span>} className="border-danger">
      <div className="flex flex-col gap-2 text-sm">
        <p>{hint}</p>
        <Field label={typeLabel} htmlFor="cascade-confirm">
          <Input id="cascade-confirm" dir="auto" autoComplete="off" value={typed} placeholder={expected} onChange={(e) => setTyped(e.target.value)} />
        </Field>
        <div>
          <Button variant="danger" icon="alert" disabled={typed.trim() !== expected.trim()} busy={purge.isPending} onClick={() => purge.mutate()}>{button}</Button>
        </div>
        {inUse ? <InUseNote counts={inUse} /> : <ErrorNote error={purge.error} />}
      </div>
    </Card>
  );
}

/** The contact person next to a supplier name (v0.3.2); archived contacts are still named. */
export function ContactName({ fa, en, className = "" }: { fa: string | null | undefined; en: string | null | undefined; className?: string }) {
  const f = useFormat();
  const name = personName(fa, en, f.lang);
  if (!name) return null;
  return <span className={`inline-flex min-w-0 items-center gap-1 text-muted ${className}`}><Icon name="users" size={13} /><Bdi className="truncate">{name}</Bdi></span>;
}
