/** The noun-modifier attribute editor (v0.10.0 section 0.2.3), used on the product page and in the item dialog.
 * Choose a template; fill its attributes (a choice of allowed values, a number with its unit and range, or text);
 * the canonical description fa/en is shown live as the backend builds it; «بازنویسی دستی» lets the owner write the
 * two descriptions himself. Nothing is saved here: the parent sends `nounBody(...)` with its own save. */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { attributeProblems, carryAttributes, cleanAttributes, type NounValue, type ProductTemplate, type TemplateAttribute } from "../lib/nounmod";
import { Checkbox, Field, Input, Select } from "./ui";

type Preview = { canonical_fa: string; canonical_en: string; long_fa: string; long_en: string };

export function useProductTemplates() {
  return useQuery({ queryKey: ["product-templates"], queryFn: () => api<ProductTemplate[]>("/api/product-templates"), staleTime: 300_000 });
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return v;
}

function AttributeField({ a, id, value, problem, onChange }: { a: TemplateAttribute; id: string; value: string; problem: string | undefined;
  onChange: (v: string) => void }) {
  const { t, i18n } = useTranslation();
  const fa = i18n.language === "fa";
  const label = (fa ? a.label_fa : a.label_en) || a.label_en || a.label_fa || a.key;
  const unit = a.unit ? (fa ? a.unit_fa : a.unit_en) ?? a.unit : null;
  const range = a.type === "number" && (a.min !== undefined || a.max !== undefined)
    ? t("nounmod.range", { min: a.min ?? "…", max: a.max ?? "…" }) : undefined;
  const hint = [a.short === false ? t("nounmod.longOnly") : null, range].filter(Boolean).join(" · ") || undefined;
  return (
    <Field label={label} htmlFor={id} hint={problem ? undefined : hint} error={problem ? t(`nounmod.problem.${problem}`, { min: a.min ?? "…", max: a.max ?? "…" }) : undefined}>
      {a.type === "choice" ? (
        <Select id={id} value={value} aria-invalid={Boolean(problem)} onChange={(e) => onChange(e.target.value)} data-testid={`attr-${a.key}`}>
          <option value="">—</option>
          {(a.values ?? []).map((v) => <option key={v.value} value={v.value}>{fa ? v.fa : v.en}</option>)}
        </Select>
      ) : (
        <span className="flex items-center gap-1.5">
          <Input id={id} dir={a.type === "number" ? "ltr" : "auto"} inputMode={a.type === "number" ? "decimal" : undefined} value={value}
            aria-invalid={Boolean(problem)} onChange={(e) => onChange(e.target.value)} data-testid={`attr-${a.key}`} />
          {unit && <span className="shrink-0 text-xs text-muted" title={a.unit}><bdi>{unit}</bdi></span>}
        </span>
      )}
    </Field>
  );
}

export function AttributeEditor({ value, onChange, idPrefix }: { value: NounValue; onChange: (next: NounValue) => void; idPrefix: string }) {
  const { t, i18n } = useTranslation();
  const fa = i18n.language === "fa";
  const templates = useProductTemplates();
  const template = templates.data?.find((x) => x.id === value.template_id) ?? null;
  const problems = attributeProblems(template, value.attributes);
  const valid = Object.keys(problems).length === 0;
  const cleaned = useDebounced(JSON.stringify(cleanAttributes(template, value.attributes)), 250);
  const preview = useQuery({
    queryKey: ["product-templates", "preview", template?.id, cleaned],
    queryFn: () => api<Preview>(`/api/product-templates/${template!.id}/preview`, { method: "POST", body: { attributes: JSON.parse(cleaned) }, background: true }),
    enabled: Boolean(template) && valid, placeholderData: (prev) => prev, retry: false,
  });
  const generated = template && valid ? preview.data : undefined;
  return (
    <div className="flex flex-col gap-3" data-testid="attribute-editor">
      <Field label={t("nounmod.template")} htmlFor={`${idPrefix}-template`} hint={t("nounmod.templateHint")}>
        <Select id={`${idPrefix}-template`} value={value.template_id ?? ""} data-testid="attr-template"
          onChange={(e) => {
            const next = templates.data?.find((x) => x.id === e.target.value) ?? null;
            onChange({ ...value, template_id: next?.id ?? null, attributes: carryAttributes(next, value.attributes) });
          }}>
          <option value="">{t("nounmod.none")}</option>
          {(templates.data ?? []).filter((x) => x.status !== "archived" || x.id === value.template_id)
            .map((x) => <option key={x.id} value={x.id}>{fa ? x.noun_fa : x.noun_en}</option>)}
        </Select>
      </Field>
      {template && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {template.attributes.map((a) => (
            <AttributeField key={a.key} a={a} id={`${idPrefix}-attr-${a.key}`} value={value.attributes[a.key] ?? ""} problem={problems[a.key]}
              onChange={(v) => onChange({ ...value, attributes: { ...value.attributes, [a.key]: v } })} />
          ))}
        </div>
      )}
      {(template || value.canonical_override) && (
        <div className="flex flex-col gap-2 rounded-md border border-line bg-surface-2 p-2.5" data-testid="attr-canonical" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted">{t("nounmod.canonical")}</span>
            <Checkbox label={t("nounmod.override")} checked={value.canonical_override}
              onChange={(on) => onChange({ ...value, canonical_override: on,
                canonical_fa: on ? value.canonical_fa ?? generated?.canonical_fa ?? null : value.canonical_fa,
                canonical_en: on ? value.canonical_en ?? generated?.canonical_en ?? null : value.canonical_en })} />
          </div>
          {value.canonical_override ? (
            <>
              <Field label={t("nounmod.canonicalFa")} htmlFor={`${idPrefix}-canon-fa`}>
                <Input id={`${idPrefix}-canon-fa`} dir="rtl" maxLength={1000} value={value.canonical_fa ?? ""} data-testid="attr-canonical-fa-input"
                  onChange={(e) => onChange({ ...value, canonical_fa: e.target.value })} />
              </Field>
              <Field label={t("nounmod.canonicalEn")} htmlFor={`${idPrefix}-canon-en`}>
                <Input id={`${idPrefix}-canon-en`} dir="ltr" maxLength={1000} value={value.canonical_en ?? ""} data-testid="attr-canonical-en-input"
                  onChange={(e) => onChange({ ...value, canonical_en: e.target.value })} />
              </Field>
              {generated && <p className="text-xs text-muted">{t("nounmod.generated")} <bdi>{fa ? generated.canonical_fa : generated.canonical_en}</bdi></p>}
            </>
          ) : !valid ? (
            <p className="text-xs text-warning">{t("nounmod.fixFirst")}</p>
          ) : generated ? (
            <>
              <p className="text-sm" dir="rtl" lang="fa" data-testid="attr-canonical-fa">{generated.canonical_fa}</p>
              <p className="text-sm" dir="ltr" lang="en" data-testid="attr-canonical-en">{generated.canonical_en}</p>
              {generated.long_en !== generated.canonical_en && (
                <p className="text-xs text-muted">{t("nounmod.long")} <bdi>{fa ? generated.long_fa : generated.long_en}</bdi></p>
              )}
            </>
          ) : (
            <p className="text-xs text-muted">…</p>
          )}
        </div>
      )}
    </div>
  );
}
