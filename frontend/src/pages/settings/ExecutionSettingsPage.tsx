/** Settings -> Execution (v0.7.0): process templates (steps are data: rename, add, remove, reorder), PO terms templates,
 * the PO price tolerance and the day settings. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Button, Card, Checkbox, ErrorNote, Field, Input, Loading, PageHeader, Select } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api } from "../../lib/api";
import { parseReminderDays } from "../../lib/tenders";
import type { ProcessTemplateRow, SettingsResponse } from "../../lib/types";

type Step = ProcessTemplateRow["steps"][number];
type StepDraft = Omit<Step, "id" | "position"> & { key: string };

const NUMBERS = [["execution.po_price_tolerance_percent", "tolerance"], ["execution.po_confirm_days", "confirmDays"],
  ["execution.ready_followup_days_before", "readyDays"], ["execution.delay_warning_days", "delayDays"],
  ["execution.claim_followup_days", "claimDays"], ["execution.invoice_followup_days", "invoiceDays"],
  ["execution.warranty_remind_days", "warrantyRemindDays"]] as const;

function TemplateEditor({ template, onSaved }: { template: ProcessTemplateRow; onSaved: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState(template.name);
  const [isDefault, setDefault] = useState(template.is_default);
  const [steps, setSteps] = useState<StepDraft[]>(template.steps.map((s) => ({ key: s.id, group: s.group, code: s.code, label_fa: s.label_fa, label_en: s.label_en,
    reference_label: s.reference_label, requires_document: s.requires_document, default_offset_days: s.default_offset_days })));
  const save = useMutation({
    mutationFn: () => api(`/api/process-templates/${template.id}`, { method: "PATCH", body: { name, is_default: isDefault,
      steps: steps.map(({ key: _key, ...s }) => ({ ...s, code: s.code || `step_${Math.random().toString(36).slice(2, 8)}` })) } }),
    onSuccess: onSaved,
  });
  const set = (i: number, patch: Partial<StepDraft>) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, dir: -1 | 1) => { const next = [...steps]; [next[i], next[i + dir]] = [next[i + dir], next[i]]; setSteps(next); };
  return (
    <div className="flex flex-col gap-2" data-testid="process-template-editor">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("execution.settings.templateName")} htmlFor={`pt-name-${template.id}`}><Input id={`pt-name-${template.id}`} dir="auto" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Checkbox label={t("execution.settings.default")} checked={isDefault} onChange={setDefault} />
      </div>
      <ul className="flex flex-col gap-1.5">{steps.map((s, i) => (
        <li key={s.key} className="flex flex-wrap items-center gap-1.5 rounded-md border border-line p-1.5" data-testid="template-step">
          <Input dir="ltr" className="w-32" aria-label={t("execution.settings.group")} value={s.group ?? ""} onChange={(e) => set(i, { group: e.target.value || null })} />
          <Input dir="rtl" className="min-w-56 flex-1" aria-label={t("execution.settings.labelFa")} value={s.label_fa} onChange={(e) => set(i, { label_fa: e.target.value })} />
          <Input dir="ltr" className="min-w-48 flex-1" aria-label={t("execution.settings.labelEn")} value={s.label_en} onChange={(e) => set(i, { label_en: e.target.value })} />
          <Input dir="auto" className="w-48" aria-label={t("execution.settings.referenceLabel")} placeholder={t("execution.settings.referenceLabel")} value={s.reference_label ?? ""}
            onChange={(e) => set(i, { reference_label: e.target.value || null })} />
          <Input dir="ltr" className="w-20" inputMode="numeric" aria-label={t("execution.settings.offset")} placeholder={t("execution.settings.offset")}
            value={s.default_offset_days ?? ""} onChange={(e) => set(i, { default_offset_days: e.target.value === "" ? null : Number(e.target.value.replace(/[^\d-]/g, "")) || 0 })} />
          <Checkbox label={t("execution.settings.requiresDocument")} checked={s.requires_document} onChange={(v) => set(i, { requires_document: v })} />
          <Button variant="ghost" disabled={i === 0} aria-label={t("tenders.envelopes.up")} onClick={() => move(i, -1)}>▲</Button>
          <Button variant="ghost" disabled={i === steps.length - 1} aria-label={t("tenders.envelopes.down")} onClick={() => move(i, 1)}>▼</Button>
          <Button variant="ghost" aria-label={t("common.remove")} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>✕</Button>
        </li>))}</ul>
      <span className="flex flex-wrap gap-1.5">
        <Button onClick={() => setSteps([...steps, { key: `n${steps.length}${Date.now()}`, group: steps.at(-1)?.group ?? null, code: "", label_fa: "", label_en: "", reference_label: null,
          requires_document: false, default_offset_days: null }])}>{t("execution.settings.addStep")}</Button>
        <Button variant="primary" busy={save.isPending} disabled={!name.trim() || steps.some((s) => !s.label_fa.trim() || !s.label_en.trim())} onClick={() => save.mutate()} data-testid="template-save">{t("common.save")}</Button>
      </span>
      <ErrorNote error={save.error} />
    </div>
  );
}

export function ExecutionSettingsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const templates = useQuery({ queryKey: ["process-templates"], queryFn: () => api<ProcessTemplateRow[]>("/api/process-templates") });
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [newType, setNewType] = useState("import");
  useEffect(() => {
    if (settings.data) {
      const v = settings.data.values as Record<string, unknown>;
      setForm({ ...Object.fromEntries(NUMBERS.map(([key]) => [key, String(v[key] ?? "")])),
        "execution.step_reminder_days": ((v["execution.step_reminder_days"] as number[]) ?? [3, 1]).join("، ") });
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: {
      ...Object.fromEntries(NUMBERS.map(([key]) => [key, Number(form![key])])), "execution.step_reminder_days": parseReminderDays(form!["execution.step_reminder_days"]) } }),
    onSuccess: (data) => { queryClient.setQueryData(["settings"], data); toast(t("common.saved"), "success"); },
  });
  const create = useMutation({ mutationFn: () => api<ProcessTemplateRow>("/api/process-templates", { method: "POST", body: { deal_type: newType, name: t(`execution.dealTypes.${newType}`),
    steps: [{ code: "step_1", label_fa: "مرحلهٔ ۱", label_en: "Step 1" }] } }), onSuccess: (row) => { void templates.refetch(); setEditing(row.id); } });
  if (!form) return <Loading />;
  const valid = NUMBERS.every(([key]) => form[key] !== "" && Number(form[key]) >= 0) && parseReminderDays(form["execution.step_reminder_days"]) !== null;
  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <PageHeader title={t("nav.sub.executionSettings")} subtitle={t("execution.settings.subtitle")} />
      <Card title={t("execution.settings.numbers")}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="execution-numbers">
          {NUMBERS.map(([key, label]) => (
            <Field key={key} label={t(`execution.settings.${label}`)} htmlFor={`es-${label}`}>
              <Input id={`es-${label}`} dir="ltr" inputMode="decimal" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /></Field>))}
          <Field label={t("execution.settings.stepReminders")} htmlFor="es-steps" hint={t("tenders.dates.remindersHint")}>
            <Input id="es-steps" dir="auto" value={form["execution.step_reminder_days"]} onChange={(e) => setForm({ ...form, "execution.step_reminder_days": e.target.value })} /></Field>
        </div>
        <ErrorNote error={save.error} />
        <Button className="mt-2" variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()} data-testid="execution-settings-save">{t("common.save")}</Button>
      </Card>
      <Card title={t("execution.settings.poTerms")}>
        <p className="text-sm">{t("execution.settings.poTermsHint")} <Link className="text-accent hover:underline" to="/sourcing/templates?kind=po_terms">{t("execution.settings.poTermsLink")}</Link></p>
      </Card>
      <Card title={t("execution.settings.templates")} actions={<span className="flex gap-1.5">
        <Select aria-label={t("execution.settings.dealType")} className="w-auto" value={newType} onChange={(e) => setNewType(e.target.value)}>
          {["import", "export", "domestic"].map((d) => <option key={d} value={d}>{t(`execution.dealTypes.${d}`)}</option>)}</Select>
        <Button icon="plus" busy={create.isPending} onClick={() => create.mutate()}>{t("execution.settings.newTemplate")}</Button></span>}>
        {templates.isLoading && <Loading />}
        <ul className="flex flex-col gap-2" data-testid="process-templates">{(templates.data ?? []).map((tpl) => (
          <li key={tpl.id} className="rounded-md border border-line p-2">
            {editing === tpl.id ? <TemplateEditor template={tpl} onSaved={() => { void templates.refetch(); setEditing(null); }} /> : (
              <span className="flex flex-wrap items-center gap-2 text-sm"><b dir="auto">{tpl.name}</b><span className="text-xs text-muted">{t(`execution.dealTypes.${tpl.deal_type}`)}</span>
                {tpl.is_default && <span className="text-xs text-success">{t("execution.settings.default")}</span>}
                <span className="text-xs text-muted">{t("execution.settings.steps", { n: tpl.steps.length })}</span>
                <Button variant="ghost" className="ms-auto" onClick={() => setEditing(tpl.id)}>{t("common.edit")}</Button></span>)}
          </li>))}</ul>
        <ErrorNote error={create.error} />
      </Card>
    </div>
  );
}
