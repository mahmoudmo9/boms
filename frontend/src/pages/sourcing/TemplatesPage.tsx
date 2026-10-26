import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, Field, Input, Modal, PageHeader, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { PLACEHOLDERS, placeholdersIn, unknownPlaceholders } from "../../lib/sourcing";
import type { MessageTemplate } from "../../lib/types";

type Draft = Pick<MessageTemplate, "language" | "channel" | "name" | "subject_template" | "body_template" | "is_default">;

function TemplateDialog({ template, onClose, onSaved }: { template: MessageTemplate | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [form, setForm] = useState<Draft>(template ?? { language: "en", channel: "email", name: "", subject_template: "", body_template: "", is_default: false });
  const unknown = unknownPlaceholders(form.subject_template, form.body_template);
  const unbalanced = placeholdersIn(form.subject_template).unbalanced || placeholdersIn(form.body_template).unbalanced;
  const preview = useQuery({
    queryKey: ["templates", "preview", form.subject_template, form.body_template, form.language],
    queryFn: () => api<{ subject: string; body: string }>("/api/message-templates/preview", { method: "POST", body: { subject_template: form.subject_template, body_template: form.body_template, language: form.language } }),
    enabled: !unknown.length && !unbalanced && !!form.body_template.trim(),
  });
  const save = useMutation({
    mutationFn: () => (template
      ? api(`/api/message-templates/${template.id}`, { method: "PATCH", body: form })
      : api("/api/message-templates", { method: "POST", body: form })),
    onSuccess: () => { onSaved(); onClose(); },
  });
  const dir = form.language === "fa" ? "rtl" : "ltr";
  return (
    <Modal open wide title={template ? t("sourcing.templates.edit") : t("sourcing.templates.new")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" busy={save.isPending} disabled={!form.name.trim() || !form.body_template.trim() || unknown.length > 0 || unbalanced} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="grid max-h-[68vh] gap-3 overflow-y-auto pe-1 lg:grid-cols-2">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-[4.5rem_auto_minmax(0,1fr)] gap-2">
            <Field label={t("sourcing.templates.language")} htmlFor="tp-lang"><Input id="tp-lang" dir="ltr" maxLength={3} value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value.toLowerCase() })} /></Field>
            <Field label={t("sourcing.rfq.channel")} htmlFor="tp-ch">
              <Select id="tp-ch" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value as Draft["channel"] })}>
                {(["email", "whatsapp", "letter"] as const).map((c) => <option key={c} value={c}>{t(`sourcing.channels.${c}`)}</option>)}
              </Select>
            </Field>
            <Field label={t("sourcing.templates.name")} htmlFor="tp-name"><Input id="tp-name" dir="auto" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          </div>
          <Field label={t("sourcing.rfq.subject")} htmlFor="tp-subj"><Input id="tp-subj" dir={dir} value={form.subject_template} onChange={(e) => setForm({ ...form, subject_template: e.target.value })} /></Field>
          <Field label={t("sourcing.rfq.message")} htmlFor="tp-body"><Textarea id="tp-body" dir={dir} rows={12} className="font-mono text-xs" value={form.body_template} onChange={(e) => setForm({ ...form, body_template: e.target.value })} /></Field>
          <Checkbox label={t("sourcing.templates.default")} checked={form.is_default} onChange={(v) => setForm({ ...form, is_default: v })} />
          {unknown.length > 0 && <p className="text-sm text-danger">{t("sourcing.templates.unknown")}: <Bdi ltr>{unknown.map((u) => `{${u}}`).join(" ")}</Bdi></p>}
          {unbalanced && <p className="text-sm text-danger">{t("errors.invalid_template")}</p>}
          <ErrorNote error={save.error} />
        </div>
        <div className="flex flex-col gap-3">
          <Card title={t("sourcing.templates.placeholders")}>
            <ul className="flex flex-col gap-1 text-sm">
              {PLACEHOLDERS.map((p) => <li key={p}><Bdi ltr className="font-mono text-xs">{`{${p}}`}</Bdi> — {t(`sourcing.templates.ph.${p}`)}</li>)}
            </ul>
            <p className="mt-2 text-xs text-muted">{t("sourcing.templates.braces")}</p>
          </Card>
          <Card title={t("sourcing.templates.preview")}>
            {preview.data ? <>
              {preview.data.subject && <p className="mb-2 text-sm font-medium" dir={dir}>{preview.data.subject}</p>}
              <pre className="font-sans text-xs whitespace-pre-wrap [unicode-bidi:plaintext]" dir={dir}>{preview.data.body}</pre>
            </> : <EmptyState>—</EmptyState>}
          </Card>
        </div>
      </div>
    </Modal>
  );
}

export function TemplatesPage() {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<MessageTemplate | "new" | null>(null);
  const list = useQuery({ queryKey: ["templates"], queryFn: () => api<{ items: MessageTemplate[] }>("/api/message-templates", { query: { include_archived: true } }) });
  const archive = useMutation({
    mutationFn: (tpl: MessageTemplate) => api(`/api/message-templates/${tpl.id}`, { method: "PATCH", body: { status: tpl.status === "active" ? "archived" : "active" } }),
    onSuccess: () => void list.refetch(),
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/message-templates/${id}`, { method: "DELETE" }), onSuccess: () => void list.refetch() });
  return (
    <div>
      <PageHeader title={t("sourcing.templates.title")} subtitle={<>{t("sourcing.templates.subtitle")} <Link to="/settings" className="text-accent hover:underline">{t("sourcing.templates.signatureLink")}</Link></>}
        actions={<Button variant="primary" icon="plus" onClick={() => setEditing("new")}>{t("sourcing.templates.new")}</Button>} />
      <Card padded={false}>
        <ErrorNote error={list.error || archive.error || remove.error} />
        <ul className="divide-y divide-line">
          {(list.data?.items ?? []).map((tpl) => (
            <li key={tpl.id} className={`flex flex-wrap items-center gap-2 px-4 py-2 text-sm ${tpl.status === "archived" ? "opacity-60" : ""}`}>
              <button type="button" className="font-medium text-accent hover:underline" onClick={() => setEditing(tpl)}><Bdi>{tpl.name}</Bdi></button>
              <Badge>{t(`sourcing.channels.${tpl.channel}`)}</Badge>
              <Badge><Bdi ltr>{tpl.language}</Bdi></Badge>
              {tpl.is_default && <Badge tone="success">{t("sourcing.templates.isDefault")}</Badge>}
              {tpl.status === "archived" && <Badge>{t("parties.archived")}</Badge>}
              <span className="ms-auto flex gap-1">
                <Button variant="ghost" onClick={() => archive.mutate(tpl)}>{tpl.status === "active" ? t("parties.archive") : t("parties.unarchive")}</Button>
                <Button variant="ghost" onClick={() => remove.mutate(tpl.id)}>{t("delete.button")}</Button>
              </span>
            </li>
          ))}
        </ul>
      </Card>
      {editing && <TemplateDialog template={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => void list.refetch()} />}
    </div>
  );
}
