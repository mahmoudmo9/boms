import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Icon } from "../../components/Icon";
import { Badge, Button, ButtonLink, Card, ErrorNote, Field, IconButton, Input, Loading, Select, Textarea } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { DocumentDetail, EventItem } from "../../lib/types";
import { EventList } from "../events/EventLogPage";
import { textStatusTone } from "./DocumentsPage";

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function DocumentDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();

  const doc = useQuery({
    queryKey: ["document", id],
    queryFn: () => api<DocumentDetail>(`/api/documents/${id}`),
    refetchInterval: (q) => (q.state.data?.text_status === "pending" ? 3000 : false),
  });
  const events = useQuery({
    queryKey: ["events", "document", id],
    queryFn: () => api<Page<EventItem>>("/api/events", { query: { entity_type: "document", entity_id: id, page_size: 50 } }),
  });

  const [form, setForm] = useState({ title: "", notes: "", language: "" });
  useEffect(() => {
    if (doc.data) setForm({ title: doc.data.title, notes: doc.data.notes ?? "", language: doc.data.language ?? "" });
  }, [doc.data]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["document", id] });
    void queryClient.invalidateQueries({ queryKey: ["events", "document", id] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const save = useMutation({
    mutationFn: () =>
      api(`/api/documents/${id}`, {
        method: "PATCH",
        body: { title: form.title, notes: form.notes || null, language: form.language || null },
      }),
    onSuccess: () => {
      toast(t("common.saved"), "success");
      refresh();
    },
  });

  const [link, setLink] = useState({ entity_type: "", entity_id: "", role: "attachment" });
  const addLink = useMutation({
    mutationFn: () => api(`/api/documents/${id}/links`, { method: "POST", body: link }),
    onSuccess: () => {
      setLink({ entity_type: "", entity_id: "", role: "attachment" });
      refresh();
    },
  });
  const removeLink = useMutation({
    mutationFn: (linkId: string) => api(`/api/documents/${id}/links/${linkId}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  if (doc.isLoading) return <Loading />;
  if (doc.error || !doc.data) return <ErrorNote error={doc.error} />;
  const d = doc.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/documents" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
          <Icon name="chevronStart" size={15} /> {t("nav.documents")}
        </Link>
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="text-lg font-semibold">{d.title}</h1>
        <div className="flex gap-2">
          {d.previewable && (
            <ButtonLink href={`/api/documents/${d.id}/preview`} icon="eye" newTab>{t("documents.openPreview")}</ButtonLink>
          )}
          <ButtonLink href={`/api/documents/${d.id}/download`} variant="primary" icon="download">{t("documents.download")}</ButtonLink>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="flex flex-col gap-4">
          <Card title={t("documents.details")}>
            <dl>
              <MetaRow label={t("documents.filename")}><Bdi>{d.original_filename}</Bdi></MetaRow>
              <MetaRow label={t("documents.type")}><Bdi>{d.mime_type}</Bdi></MetaRow>
              <MetaRow label={t("documents.size")}><span className="tabular-nums">{f.bytes(d.size_bytes)}</span></MetaRow>
              <MetaRow label={t("documents.uploadedAt")}><span className="tabular-nums">{f.date(d.uploaded_at, true)}</span></MetaRow>
              <MetaRow label={t("documents.text")}>
                {d.text_status === "none" ? "—" : <Badge tone={textStatusTone(d.text_status)}>{t(`documents.textStatus.${d.text_status}`)}</Badge>}
              </MetaRow>
              <MetaRow label="SHA-256"><Bdi ltr className="font-mono text-xs break-all">{d.sha256}</Bdi></MetaRow>
            </dl>
          </Card>

          <Card title={t("documents.edit")}>
            <form
              className="flex flex-col gap-3"
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <Field label={t("documents.title")} htmlFor="doc-title">
                <Input id="doc-title" value={form.title} required maxLength={500} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label={t("documents.notes")} htmlFor="doc-notes">
                <Textarea id="doc-notes" value={form.notes} rows={4} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </Field>
              <Field label={t("documents.language")} htmlFor="doc-lang">
                <Select id="doc-lang" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                  <option value="">—</option>
                  <option value="fa">{t("documents.languages.fa")}</option>
                  <option value="en">{t("documents.languages.en")}</option>
                  <option value="other">{t("documents.languages.other")}</option>
                </Select>
              </Field>
              <ErrorNote error={save.error} />
              <div>
                <Button type="submit" variant="primary" busy={save.isPending}>{t("common.save")}</Button>
              </div>
            </form>
          </Card>

          <Card title={t("documents.links")}>
            {d.links.length === 0 ? (
              <p className="text-sm text-muted">{t("documents.noLinks")}</p>
            ) : (
              <ul className="mb-3 flex flex-col gap-1">
                {d.links.map((l) => (
                  <li key={l.id} className="flex items-center gap-2 text-sm">
                    <Icon name="link" size={14} className="text-muted" />
                    <Bdi ltr>{l.entity_type}</Bdi>
                    <span className="text-muted">/</span>
                    <Bdi ltr className="font-medium">{l.entity_id}</Bdi>
                    <Badge>{l.role}</Badge>
                    <IconButton icon="x" label={t("documents.unlink")} className="ms-auto" onClick={() => removeLink.mutate(l.id)} />
                  </li>
                ))}
              </ul>
            )}
            <form
              className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]"
              onSubmit={(e) => {
                e.preventDefault();
                addLink.mutate();
              }}
            >
              <Input dir="ltr" placeholder={t("documents.entityType")} value={link.entity_type} required pattern="[a-z][a-z0-9_.]*"
                onChange={(e) => setLink({ ...link, entity_type: e.target.value })} aria-label={t("documents.entityType")} />
              <Input dir="ltr" placeholder={t("documents.entityId")} value={link.entity_id} required
                onChange={(e) => setLink({ ...link, entity_id: e.target.value })} aria-label={t("documents.entityId")} />
              <Input dir="ltr" placeholder={t("documents.role")} value={link.role} required pattern="[a-z][a-z0-9_]*"
                onChange={(e) => setLink({ ...link, role: e.target.value })} aria-label={t("documents.role")} />
              <Button type="submit" icon="plus" busy={addLink.isPending}>{t("documents.link")}</Button>
            </form>
            <div className="mt-2"><ErrorNote error={addLink.error || removeLink.error} /></div>
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          {d.previewable && (
            <Card title={t("documents.preview")} padded={false}>
              {d.mime_type === "application/pdf" ? (
                <iframe title={d.title} src={`/api/documents/${d.id}/preview`} className="h-[70vh] w-full rounded-b-lg" />
              ) : (
                <img src={`/api/documents/${d.id}/preview`} alt={d.title} className="mx-auto max-h-[70vh] p-2" />
              )}
            </Card>
          )}
          <Card title={t("documents.history")} padded={false}>
            <EventList items={events.data?.items ?? []} compact />
          </Card>
        </div>
      </div>
    </div>
  );
}
