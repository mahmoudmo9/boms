/** Settings -> Tenders (v0.6.0): reminder days before tender dates, guarantee reminder offsets, the release follow-up,
 * envelope templates and the result reasons. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Checkbox, ErrorNote, Field, Input, Loading, PageHeader, Select } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api } from "../../lib/api";
import { parseReminderDays } from "../../lib/tenders";
import type { EnvelopeTemplateRow, ResultReasonRow, SettingsResponse } from "../../lib/types";

type Line = { envelope: "A" | "B" | "C"; title: string; kind: string };

function TemplateEditor({ template, onSaved }: { template: EnvelopeTemplateRow | null; onSaved: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState(template?.name ?? "");
  const [isDefault, setDefault] = useState(template?.is_default ?? false);
  const [lines, setLines] = useState<Line[]>(template?.lines.map((l) => ({ envelope: l.envelope, title: l.title, kind: l.kind })) ?? []);
  const save = useMutation({
    mutationFn: () => api(template ? `/api/envelope-templates/${template.id}` : "/api/envelope-templates", { method: template ? "PUT" : "POST",
      body: { name, is_default: isDefault, lines: lines.filter((l) => l.title.trim()) } }),
    onSuccess: onSaved,
  });
  const remove = useMutation({ mutationFn: () => api(`/api/envelope-templates/${template!.id}`, { method: "DELETE" }), onSuccess: onSaved });
  const move = (i: number, dir: -1 | 1) => { const next = [...lines]; [next[i], next[i + dir]] = [next[i + dir], next[i]]; setLines(next); };
  return (
    <div className="flex flex-col gap-2" data-testid="template-editor">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("tenders.settings.templateName")} htmlFor="tpl-name"><Input id="tpl-name" dir="auto" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Checkbox label={t("tenders.settings.default")} checked={isDefault} onChange={setDefault} />
      </div>
      <ul className="flex flex-col gap-1">
        {lines.map((l, i) => (
          <li key={i} className="flex flex-wrap items-center gap-1.5">
            <Select aria-label={t("tenders.envelopes.envelope")} className="w-auto" value={l.envelope} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, envelope: e.target.value as Line["envelope"] } : x))}>
              {(["A", "B", "C"] as const).map((e) => <option key={e} value={e}>{t(`tenders.envelopes.names.${e}`)}</option>)}</Select>
            <Input dir="auto" className="min-w-64 flex-1" aria-label={t("tenders.envelopes.itemTitle")} value={l.title} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} />
            <Select aria-label={t("tenders.envelopes.kind")} className="w-auto" value={l.kind} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, kind: e.target.value } : x))}>
              {["document", "bid_bond", "price_form"].map((k) => <option key={k} value={k}>{t(`tenders.envelopes.kinds.${k}`)}</option>)}</Select>
            <Button variant="ghost" disabled={i === 0} aria-label={t("tenders.envelopes.up")} onClick={() => move(i, -1)}>▲</Button>
            <Button variant="ghost" disabled={i === lines.length - 1} aria-label={t("tenders.envelopes.down")} onClick={() => move(i, 1)}>▼</Button>
            <Button variant="ghost" aria-label={t("common.remove")} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</Button>
          </li>
        ))}
      </ul>
      <span className="flex flex-wrap gap-1.5">
        <Button onClick={() => setLines([...lines, { envelope: "B", title: "", kind: "document" }])}>{t("tenders.settings.addLine")}</Button>
        <Button variant="primary" disabled={!name.trim()} busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
        {template && !template.is_default && <Button variant="ghost" busy={remove.isPending} onClick={() => remove.mutate()}>{t("common.remove")}</Button>}
      </span>
      <ErrorNote error={save.error || remove.error} />
    </div>
  );
}

export function TendersSettingsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const templates = useQuery({ queryKey: ["envelope-templates"], queryFn: () => api<EnvelopeTemplateRow[]>("/api/envelope-templates") });
  const reasons = useQuery({ queryKey: ["tender-result-reasons", "all"], queryFn: () => api<ResultReasonRow[]>("/api/tender-result-reasons", { query: { include_inactive: true } }) });
  const [form, setForm] = useState<{ days: string; gdays: string; release: string } | null>(null);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [rows, setRows] = useState<ResultReasonRow[] | null>(null);
  useEffect(() => {
    if (settings.data) {
      const v = settings.data.values as Record<string, unknown>;
      setForm({ days: ((v["tenders.reminder_days"] as number[]) ?? [3, 1]).join("، "), gdays: ((v["tenders.guarantee_reminder_days"] as number[]) ?? [30, 7]).join("، "),
        release: String(v["tenders.release_followup_days"] ?? 7) });
    }
  }, [settings.data]);
  useEffect(() => { if (reasons.data) setRows(reasons.data); }, [reasons.data]);
  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: { "tenders.reminder_days": parseReminderDays(form!.days),
      "tenders.guarantee_reminder_days": parseReminderDays(form!.gdays), "tenders.release_followup_days": Number(form!.release) } }),
    onSuccess: (data) => { queryClient.setQueryData(["settings"], data); toast(t("common.saved"), "success"); },
  });
  const saveReasons = useMutation({ mutationFn: () => api<ResultReasonRow[]>("/api/tender-result-reasons", { method: "PUT", body: { reasons: rows!.map(({ code, label_fa, label_en, active }) => ({ code, label_fa, label_en, active })) } }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["tender-result-reasons"] }); toast(t("common.saved"), "success"); } });
  if (!form) return <Loading />;
  const valid = parseReminderDays(form.days) !== null && parseReminderDays(form.gdays) !== null && Number(form.release) >= 0;
  const refreshTemplates = () => { void queryClient.invalidateQueries({ queryKey: ["envelope-templates"] }); setEditing(null); };
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <PageHeader title={t("nav.sub.tenderSettings")} subtitle={t("tenders.settings.subtitle")} />
      <Card title={t("tenders.settings.reminders")}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("tenders.settings.reminderDays")} htmlFor="ts-days" hint={t("tenders.dates.remindersHint")}><Input id="ts-days" dir="auto" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} /></Field>
          <Field label={t("tenders.settings.guaranteeDays")} htmlFor="ts-gdays"><Input id="ts-gdays" dir="auto" value={form.gdays} onChange={(e) => setForm({ ...form, gdays: e.target.value })} /></Field>
          <Field label={t("tenders.settings.releaseDays")} htmlFor="ts-release"><Input id="ts-release" dir="ltr" inputMode="numeric" value={form.release} onChange={(e) => setForm({ ...form, release: e.target.value })} /></Field>
        </div>
        <ErrorNote error={save.error} />
        <Button className="mt-2" variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
      </Card>
      <Card title={t("tenders.settings.templates")} actions={<Button icon="plus" onClick={() => setEditing("new")}>{t("tenders.settings.newTemplate")}</Button>}>
        <ul className="flex flex-col gap-2">
          {(templates.data ?? []).map((tpl) => (
            <li key={tpl.id} className="rounded-md border border-line p-2">
              {editing === tpl.id ? <TemplateEditor template={tpl} onSaved={refreshTemplates} /> : (
                <span className="flex flex-wrap items-center gap-2 text-sm"><b dir="auto">{tpl.name}</b>{tpl.is_default && <span className="text-xs text-success">{t("tenders.settings.default")}</span>}
                  <span className="text-xs text-muted">{t("tenders.settings.lines", { n: tpl.lines.length })}</span>
                  <Button variant="ghost" className="ms-auto" onClick={() => setEditing(tpl.id)}>{t("common.edit")}</Button></span>)}
            </li>
          ))}
          {editing === "new" && <li className="rounded-md border border-accent p-2"><TemplateEditor template={null} onSaved={refreshTemplates} /></li>}
        </ul>
      </Card>
      <Card title={t("tenders.settings.reasons")}>
        {rows && <ul className="flex flex-col gap-1.5" data-testid="reason-rows">{rows.map((r, i) => (
          <li key={r.code} className="flex flex-wrap items-center gap-1.5">
            <code className="w-40 text-xs text-muted" dir="ltr">{r.code}</code>
            <Input dir="rtl" aria-label={`${r.code} fa`} value={r.label_fa} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, label_fa: e.target.value } : x))} />
            <Input dir="ltr" aria-label={`${r.code} en`} value={r.label_en} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, label_en: e.target.value } : x))} />
            <Checkbox label={t("tenders.settings.active")} checked={r.active} onChange={(v) => setRows(rows.map((x, j) => j === i ? { ...x, active: v } : x))} />
          </li>))}</ul>}
        <ErrorNote error={saveReasons.error} />
        <Button className="mt-2" variant="primary" busy={saveReasons.isPending} onClick={() => saveReasons.mutate()}>{t("common.save")}</Button>
      </Card>
    </div>
  );
}
