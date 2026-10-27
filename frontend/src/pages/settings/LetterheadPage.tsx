/** Settings -> Letterhead: company data printed on quotes (fa/en), the logo, the PDF browser, quote terms. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Button, Card, ErrorNote, Field, Input, PageHeader, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, ApiError } from "../../lib/api";
import type { DocumentDetail, SettingsResponse } from "../../lib/types";

const SINGLE = ["company.name_fa", "company.name_en", "company.phone", "company.email", "company.website", "pdf.browser_path"] as const;
const PER_LANG = ["company.address", "company.registration", "company.bank_details", "company.footer"] as const;

export function LetterheadPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const [values, setValues] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    if (settings.data) {
      const v = settings.data.values as Record<string, unknown>;
      setValues(Object.fromEntries([...SINGLE.map((k) => [k, (v[k] as string | null) ?? ""]), ...PER_LANG.map((k) => [k, { fa: "", en: "", ...(v[k] as object ?? {}) }]),
        ["company.logo_document_id", v["company.logo_document_id"] ?? null]]));
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: { ...values, "pdf.browser_path": (values?.["pdf.browser_path"] as string) || null } }),
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
  if (!values) return null;
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
            <Field label={t("letterhead.fields.logo")} htmlFor="lh-logo" hint={t("letterhead.logoHint")}>
              <div className="flex flex-wrap items-center gap-2">
                <input id="lh-logo" type="file" accept="image/png,image/jpeg" className="text-sm" onChange={(e) => e.target.files?.[0] && logo.mutate(e.target.files[0])} />
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
                  <Textarea id={`lh-${key}-${lang}`} dir={lang === "fa" ? "rtl" : "ltr"} rows={3} value={(values[key] as Record<string, string>)[lang] ?? ""}
                    onChange={(e) => setValues({ ...values, [key]: { ...(values[key] as Record<string, string>), [lang]: e.target.value } })} />
                </Field>
              ))}
            </div>
          </Card>
        ))}
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
