/** Settings -> Letterhead: company data printed on quotes (fa/en), the logo, the PDF browser, quote terms. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Button, Card, ErrorNote, Field, FileDrop, Input, PageHeader, Textarea, useToast, ValidatedInput } from "../../design/components";
import { api, ApiError } from "../../lib/api";
import { type Bank, bankFrom, bankIsEmpty, bankText, type PerLang } from "../../lib/bank";
import type { DocumentDetail, SettingsResponse } from "../../lib/types";

const SINGLE = ["company.name_fa", "company.name_en", "company.phone", "company.email", "company.website", "pdf.browser_path",
  "company.national_id", "company.economic_code"] as const;
const PER_LANG = ["company.address", "company.registration", "company.footer",
  "company.signer_name", "company.signer_title"] as const;

export function LetterheadPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const [values, setValues] = useState<Record<string, unknown> | null>(null);
  const [bank, setBank] = useState<Bank | null>(null);
  useEffect(() => {
    if (settings.data) {
      const v = settings.data.values as Record<string, unknown>;
      setBank(bankFrom(v["company.bank"] as Bank | null, v["company.bank_details"] as PerLang | null));
      setValues(Object.fromEntries([...SINGLE.map((k) => [k, (v[k] as string | null) ?? ""]), ...PER_LANG.map((k) => [k, { fa: "", en: "", ...(v[k] as object ?? {}) }]),
        ["company.logo_document_id", v["company.logo_document_id"] ?? null]]));
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: { ...values, "pdf.browser_path": (values?.["pdf.browser_path"] as string) || null,
      ...(bank && !(bankIsEmpty(bank) && !(settings.data?.values as Record<string, unknown> | undefined)?.["company.bank"]) ? { "company.bank": bankIsEmpty(bank) ? null : bank } : {}) } }),
    onSuccess: (data) => { queryClient.setQueryData(["settings"], data); toast(t("common.saved"), "success"); },
  });
  const logo = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      try { return (await api<DocumentDetail>("/api/documents", { method: "POST", form })).id; }
      catch (err) { if (err instanceof ApiError && err.code === "duplicate_document") return String(err.details.id); throw err; }
    },
    onSuccess: (id) => setValues((v) => ({ ...v, "company.logo_document_id": id })),
  });
  if (!values || !bank) return null;
  const single = (key: (typeof SINGLE)[number], dir: "ltr" | "rtl" | "auto" = "auto") => (
    <Field label={t(`letterhead.fields.${key.split(".")[1]}`)} htmlFor={`lh-${key}`}>
      <Input id={`lh-${key}`} dir={dir} value={values[key] as string} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
    </Field>
  );
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <PageHeader title={t("nav.sub.letterhead")} subtitle={t("letterhead.subtitle")} />
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }} className="flex flex-col gap-4">
        <Card title={t("letterhead.company")}>
          <div className="grid gap-3 sm:grid-cols-2">
            {single("company.name_fa", "rtl")}{single("company.name_en", "ltr")}
            {single("company.phone", "ltr")}{single("company.email", "ltr")}{single("company.website", "ltr")}
            {single("company.national_id", "ltr")}{single("company.economic_code", "ltr")}
            <Field label={t("letterhead.fields.logo")} htmlFor="lh-logo" hint={t("letterhead.logoHint")}>
              <div className="flex flex-wrap items-center gap-2">
                <FileDrop accept="image/png,image/jpeg" multiple={false} busy={logo.isPending} testId="lh-logo" onFiles={(files) => files[0] && logo.mutate(files[0])} />
                {values["company.logo_document_id"] ? <Link className="text-xs text-accent hover:underline" to={`/documents/${values["company.logo_document_id"]}`}>{t("letterhead.logoSet")}</Link> : null}
                {values["company.logo_document_id"] ? <Button variant="ghost" onClick={() => setValues({ ...values, "company.logo_document_id": null })}>{t("common.remove")}</Button> : null}
              </div>
            </Field>
          </div>
          <ErrorNote error={logo.error} />
        </Card>
        {PER_LANG.map((key) => (
          <Card key={key} title={t(`letterhead.fields.${key.split(".")[1]}`)}>
            <div className="grid gap-3 sm:grid-cols-2">
              {(["fa", "en"] as const).map((lang) => (
                <Field key={lang} label={t(`common.languageNames.${lang}`)} htmlFor={`lh-${key}-${lang}`}>
                  <Textarea id={`lh-${key}-${lang}`} dir={lang === "fa" ? "rtl" : "ltr"} rows={key.startsWith("company.signer") ? 1 : 3} value={(values[key] as Record<string, string>)[lang] ?? ""}
                    onChange={(e) => setValues({ ...values, [key]: { ...(values[key] as Record<string, string>), [lang]: e.target.value } })} />
                </Field>
              ))}
            </div>
          </Card>
        ))}
        <BankCard bank={bank} onChange={setBank} />
        <Card title={t("letterhead.pdf")}>
          {single("pdf.browser_path", "ltr")}
          <p className="mt-1 text-xs text-muted">{t("letterhead.pdfHint")}</p>
        </Card>
        <Card title={t("letterhead.terms")}>
          <p className="text-sm">{t("letterhead.termsHint")} <Link className="text-accent hover:underline" to="/sourcing/templates?kind=quote_terms">{t("letterhead.termsLink")}</Link></p>
        </Card>
        <ErrorNote error={save.error} />
        <div><Button type="submit" variant="primary" busy={save.isPending}>{t("common.save")}</Button></div>
      </form>
    </div>
  );
}

/** v0.10.0 section 5: bank details as fields; the printed lines are shown as they will appear on the letterhead. */
function BankCard({ bank, onChange }: { bank: Bank; onChange: (b: Bank) => void }) {
  const { t } = useTranslation();
  const perLang = (key: "bank_name" | "account_holder" | "other", rows = 1) => (
    <div className="grid gap-3 sm:grid-cols-2">
      {(["fa", "en"] as const).map((lang) => (
        <Field key={lang} label={`${t(`letterhead.bank.${key}`)} (${t(`common.languageNames.${lang}`)})`} htmlFor={`lh-bank-${key}-${lang}`}>
          {rows > 1
            ? <Textarea id={`lh-bank-${key}-${lang}`} dir={lang === "fa" ? "rtl" : "ltr"} rows={rows} value={bank[key][lang] ?? ""} onChange={(e) => onChange({ ...bank, [key]: { ...bank[key], [lang]: e.target.value } })} />
            : <Input id={`lh-bank-${key}-${lang}`} dir={lang === "fa" ? "rtl" : "ltr"} value={bank[key][lang] ?? ""} onChange={(e) => onChange({ ...bank, [key]: { ...bank[key], [lang]: e.target.value } })} />}
        </Field>
      ))}
    </div>
  );
  return (
    <Card title={t("letterhead.fields.bank_details")} subtitle={t("letterhead.bank.subtitle")} testId="bank-card">
      <div className="flex flex-col gap-4">
        {perLang("bank_name")}
        {perLang("account_holder")}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("letterhead.bank.iban")} htmlFor="lh-bank-iban">
            <ValidatedInput kind="iban" id="lh-bank-iban" value={bank.iban} onChange={(v) => onChange({ ...bank, iban: v })} placeholder="IR00 0000 0000 0000 0000 0000 00" />
          </Field>
          <Field label={t("letterhead.bank.bic")} htmlFor="lh-bank-bic">
            <ValidatedInput kind="bic" id="lh-bank-bic" value={bank.bic} onChange={(v) => onChange({ ...bank, bic: v })} placeholder="BKMTIRTH" />
          </Field>
        </div>
        {perLang("other", 2)}
        <div className="grid gap-3 sm:grid-cols-2" data-testid="bank-preview">
          {(["fa", "en"] as const).map((lang) => (
            <figure key={lang} className="flex flex-col gap-1.5 rounded-xl border border-dashed border-line bg-surface-2 p-3">
              <figcaption className="text-xs text-muted">{t("letterhead.bank.preview", { lang: t(`common.languageNames.${lang}`) })}</figcaption>
              <pre dir={lang === "fa" ? "rtl" : "ltr"} className="font-sans text-sm whitespace-pre-wrap text-fg">{bankText(bank, lang) || "—"}</pre>
            </figure>
          ))}
        </div>
      </div>
    </Card>
  );
}
