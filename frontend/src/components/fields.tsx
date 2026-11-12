/** v0.10.0 section 5: the app's pickers, all built on the library's smart fields — `Combobox` for the short base-data
 * lists (currency, unit, Incoterm, country) and `LookupField` (`GET /api/lookup`) for records (product, party). They
 * replace v0.9.0's `CurrencySelect`, `UnitInput`, `IncotermSelect`, `CountrySelect`, `ProductPicker` and `PartyPicker`
 * with the same values, so the forms send exactly what they sent before. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { AmountInWords, Button, Combobox, ErrorNote, Input, LookupField, type Option } from "../design/components";
import { api } from "../lib/api";
import { INCOTERMS, sortCurrencies, useCountries, useCurrencies, useIncoterms, useUnits } from "../lib/basedata";
import { useFormat } from "../lib/prefs";
import type { LookupItem } from "../lib/smart";
import type { Party, PartyDetail, PossibleDuplicate, Product } from "../lib/types";
import { PartyName } from "../pages/parties/shared";

const hasPersian = (s: string) => /[؀-ۿ]/.test(s);

/** An ISO 4217 currency; the common ones first. */
export function CurrencyField({ value, onChange, id, allowEmpty = true, className = "w-32 shrink-0", ariaLabel }: {
  value: string | null; onChange: (v: string | null) => void; id?: string; allowEmpty?: boolean; className?: string; ariaLabel?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const currencies = useCurrencies();
  const options: Option[] = sortCurrencies(currencies.data?.items ?? []).map((c) => ({ value: c.code, label: c.code, hint: f.lang === "fa" ? c.name_fa : c.name_en }));
  if (value && !options.some((o) => o.value === value)) options.unshift({ value, label: value });
  return <Combobox id={id} options={options} value={value} onChange={(v) => onChange(v)} clearable={allowEmpty} dir="ltr" placeholder="USD"
    ariaLabel={ariaLabel ?? t("sourcing.currency")} className={className} testId={id ? `${id}-field` : undefined} />;
}

/** A unit of measure (UN/ECE Recommendation 20), or free text when none fits ("barrels of 200 l"). */
export function UnitField({ code, text, onChange, id, allowText = true }: {
  code: string | null; text: string | null; onChange: (v: { unit_code: string | null; unit_text: string | null }) => void; id?: string; allowText?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const units = useUnits();
  const [free, setFree] = useState(!code && !!text);
  const options: Option[] = (units.data?.items ?? []).map((u) => ({ value: u.code, label: f.lang === "fa" ? u.name_fa : u.name_en, code: u.code }));
  if (allowText) options.push({ value: "__text", label: t("sourcing.item.unitOther") });
  return (
    <div className="flex min-w-0 gap-1.5">
      <Combobox id={id} options={options} value={free ? "__text" : code} className="w-44 shrink-0" ariaLabel={t("sourcing.item.unit")} testId={id ? `${id}-field` : undefined}
        onChange={(v) => {
          if (v === "__text") { setFree(true); onChange({ unit_code: null, unit_text: text ?? "" }); }
          else { setFree(false); onChange({ unit_code: v, unit_text: null }); }
        }} />
      {free && <Input className="min-w-0 flex-1" aria-label={t("sourcing.item.unitText")} value={text ?? ""} maxLength={300}
        onChange={(e) => onChange({ unit_code: null, unit_text: e.target.value })} />}
    </div>
  );
}

/** An Incoterms® 2020 rule; the code is the value, the name its hint. */
export function IncotermField({ value, onChange, id }: { value: string | null; onChange: (v: string | null) => void; id?: string }) {
  const { t, i18n } = useTranslation();
  const rules = useIncoterms();
  const rows = rules.data ?? INCOTERMS.map((code) => ({ code, name_en: "", name_fa: "" }));
  const options: Option[] = rows.map((r) => ({ value: r.code, label: r.code, hint: (i18n.language === "fa" ? r.name_fa : r.name_en) || null }));
  return <Combobox id={id} options={options} value={value} onChange={(v) => onChange(v)} dir="ltr" placeholder="FOB" className="w-32 shrink-0"
    ariaLabel={t("sourcing.incoterm")} testId={id ? `${id}-field` : undefined} />;
}

/** A country (ISO 3166 alpha-2); empty means "any" in filters and "not set" in forms. */
export function CountryField({ value, onChange, id, allowEmpty = true, emptyLabel, className = "" }: {
  value: string; onChange: (v: string) => void; id?: string; allowEmpty?: boolean; emptyLabel?: string; className?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const countries = useCountries();
  const options: Option[] = (countries.data?.items ?? []).map((c) => ({ value: c.iso2, label: f.lang === "fa" ? c.name_fa : c.name_en, code: c.iso2 }));
  return <Combobox id={id} options={options} value={value || null} onChange={(v) => onChange(v ?? "")} clearable={allowEmpty}
    placeholder={emptyLabel ?? (allowEmpty ? t("common.all") : undefined)} ariaLabel={t("parties.country")} className={className} testId={id ? `${id}-field` : undefined} />;
}

/** A catalogue product, found by name, code or HS; the chosen one links to its page. */
export function ProductField({ value, onChange, id }: { value: string | null; onChange: (id: string | null, product?: Product) => void; id?: string }) {
  const { t, i18n } = useTranslation();
  const current = useQuery({ queryKey: ["products", "one", value], queryFn: () => api<Product>(`/api/products/${value}`), enabled: !!value });
  const item: LookupItem | null = value ? { kind: "product", id: value, code: current.data?.hs_code ?? null, name_fa: current.data?.name_fa ?? current.data?.name_en ?? "…",
    name_en: current.data?.name_en ?? current.data?.name_fa ?? "…" } : null;
  return (
    <LookupField kind="product" id={id} value={item} placeholder={t("sourcing.productSearch")} ariaLabel={t("sourcing.item.product")} testId={id ? `${id}-field` : undefined}
      onChange={(x) => { if (!x) onChange(null); else void api<Product>(`/api/products/${x.id}`).then((p) => onChange(p.id, p)); }}
      renderValue={(x) => <Link to={`/sourcing/catalog/${x.id}`} className="text-accent hover:underline">
        <bdi>{i18n.language === "fa" ? x.name_fa || x.name_en : x.name_en || x.name_fa}</bdi></Link>} />
  );
}

/** A party: search by name, code or national ID, or create one from the typed name (duplicates are shown first). */
export function PartyField({ value, onChange, id = "ql-party", autoFocus }: { value: Party | null; onChange: (p: Party | null) => void; id?: string; autoFocus?: boolean }) {
  const { t } = useTranslation();
  const [duplicates, setDuplicates] = useState<{ name: string; rows: PossibleDuplicate[] } | null>(null);
  const create = useMutation({
    mutationFn: ({ name, confirm }: { name: string; confirm: boolean }) =>
      api<{ created: boolean; possible_duplicates: PossibleDuplicate[]; party?: PartyDetail }>("/api/parties", {
        method: "POST", body: { [hasPersian(name) ? "name_fa" : "name_en"]: name, confirm_duplicate: confirm } }),
    onSuccess: (res, { name }) => {
      if (res.created && res.party) { onChange(res.party); setDuplicates(null); }
      else setDuplicates({ name, rows: res.possible_duplicates });
    },
  });
  const pick = async (partyId: string) => { onChange(await api<PartyDetail>(`/api/parties/${partyId}`)); setDuplicates(null); };
  const item: LookupItem | null = value ? { kind: "party", id: value.id, code: value.code ?? null, name_fa: value.name_fa ?? value.name_en ?? "", name_en: value.name_en ?? value.name_fa ?? "" } : null;
  return (
    <div className="flex min-w-0 flex-col gap-2" data-autofocus={autoFocus || undefined}>
      <LookupField kind="party" id={id} value={item} placeholder={t("quicklog.partyPlaceholder")} ariaLabel={t("quicklog.party")} testId="party-field"
        onChange={(x) => { if (!x) { onChange(null); return; } void pick(x.id); }}
        renderValue={() => value && <PartyName fa={value.name_fa} en={value.name_en} dnc={value.do_not_contact} />}
        create={{ label: (text) => t("quicklog.createPartyNamed", { name: text }), onCreate: (name) => create.mutate({ name, confirm: false }) }} />
      {duplicates && (
        <div className="rounded-xl border border-warning bg-warning-soft p-3 text-sm" data-testid="party-duplicates">
          <p className="mb-2 font-medium text-warning">{t("parties.possibleDuplicates")}</p>
          <ul className="mb-2.5 flex flex-col gap-1.5">
            {duplicates.rows.map((d) => (
              <li key={d.id} className="flex items-center gap-2">
                <PartyName fa={d.name_fa} en={d.name_en} dnc={d.do_not_contact} />
                <Button size="sm" variant="ghost" className="ms-auto" onClick={() => void pick(d.id)}>{t("quicklog.useThis")}</Button>
              </li>
            ))}
          </ul>
          <Button size="sm" onClick={() => create.mutate({ name: duplicates.name, confirm: true })} busy={create.isPending}>{t("parties.createAnyway")}</Button>
        </div>
      )}
      <ErrorNote error={create.error} />
    </div>
  );
}

type ContactLike = { id: string; name_fa: string | null; name_en: string | null; status?: string; title?: string | null; job_title?: string | null };

/** A contact of the chosen party (empty = none); archived contacts are marked. Value "" means no contact. */
export function ContactField({ contacts, value, onChange, id, disabled, emptyLabel }: {
  contacts: ContactLike[]; value: string; onChange: (id: string) => void; id?: string; disabled?: boolean; emptyLabel?: string }) {
  const { t, i18n } = useTranslation();
  const options: Option[] = contacts.map((c) => ({ value: c.id, label: ((i18n.language === "fa" ? c.name_fa || c.name_en : c.name_en || c.name_fa) ?? "").trim(),
    hint: c.status === "archived" ? t("parties.archived") : (c.job_title ?? c.title ?? null) }));
  return <Combobox id={id} options={options} value={value || null} onChange={(v) => onChange(v ?? "")} disabled={disabled}
    placeholder={emptyLabel ?? "—"} ariaLabel={t("interactions.contact")} testId={id ? `${id}-field` : undefined} />;
}

/** One of a short list of parties already on the record (a case's customer and suppliers). */
export function PartyChoice({ parties, value, onChange, id }: { parties: [string, string][]; value: string; onChange: (id: string) => void; id?: string }) {
  const { t } = useTranslation();
  return <Combobox id={id} options={parties.map(([v, label]) => ({ value: v, label }))} value={value || null} onChange={(v) => onChange(v ?? "")}
    clearable={false} ariaLabel={t("quicklog.party")} testId={id ? `${id}-field` : undefined} />;
}

/** v0.10.0 section 5: the calculation beside a money field — the amount at a rate in another currency (a cost or
 * payment in rial), a line total (quantity × unit price) and the amount in words in the user's language. Display only:
 * what is saved is what the form sends, as before. */
export function MoneyNote({ amount, currency, rate, rateCurrency, quantity, words = true }: {
  amount: string | number | null | undefined; currency: string | null | undefined; rate?: string | number | null; rateCurrency?: string | null;
  quantity?: string | number | null; words?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const n = Number(amount);
  if (amount === null || amount === undefined || amount === "" || Number.isNaN(n) || !currency) return null;
  const total = quantity !== null && quantity !== undefined && quantity !== "" && !Number.isNaN(Number(quantity)) ? n * Number(quantity) : null;
  const converted = rate && rateCurrency && rateCurrency !== currency && !Number.isNaN(Number(rate)) ? (total ?? n) * Number(rate) : null;
  return (
    <div className="flex flex-col gap-0.5 text-xs text-muted" data-testid="money-note">
      {total !== null && <span>{t("smart.lineTotal")}: <bdi dir="ltr" className="tabular-nums text-fg-2">{f.num(total)} {currency}</bdi></span>}
      {converted !== null && <span>= <bdi dir="ltr" className="tabular-nums text-fg-2">{f.num(Math.round(converted))} {rateCurrency}</bdi></span>}
      {words && <AmountInWords amount={converted !== null ? Math.round(converted) : total ?? n} currency={converted !== null ? rateCurrency! : currency} lang={f.lang} />}
    </div>
  );
}
