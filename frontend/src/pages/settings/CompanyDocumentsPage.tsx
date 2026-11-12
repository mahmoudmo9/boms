/** Settings -> Company documents (v0.6.0): the library of fixed company documents reused in tender envelopes, with
 * their expiry state (ok / within 30 days / expired / no expiry) and SetadSuite's quick-add titles. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { Badge, Button, Card, DateInput, EmptyState, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select } from "../../design/components";
import { api, ApiError } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import type { CompanyDocumentRow, DocumentDetail } from "../../lib/types";

const CATEGORIES = ["registration", "tax", "insurance", "certificates", "track_record", "qualification", "identity", "other"] as const;
const TONE = { ok: "success", soon: "warning", expired: "danger", none: "neutral" } as const;

function DocDialog({ doc, initial, onClose, onSaved }: { doc: CompanyDocumentRow | null; initial?: { title: string; category: string }; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ title: doc?.title ?? initial?.title ?? "", category: doc?.category ?? initial?.category ?? "other",
    document_id: doc?.document_id ?? null, issued_on: doc?.issued_on ?? null, expires_on: doc?.expires_on ?? null, note: doc?.note ?? "" });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const data = new FormData();
      data.append("file", file);
      try { return (await api<DocumentDetail>("/api/documents", { method: "POST", form: data })).id; }
      catch (err) { if (err instanceof ApiError && err.code === "duplicate_document") return String(err.details.id); throw err; }
    },
    onSuccess: (id) => setForm((f) => ({ ...f, document_id: id })),
  });
  const save = useMutation({ mutationFn: () => api(doc ? `/api/company-documents/${doc.id}` : "/api/company-documents", { method: doc ? "PATCH" : "POST",
    body: { ...form, note: form.note || null } }), onSuccess: () => { onSaved(); onClose(); } });
  return (
    <Modal open title={doc ? t("tenders.library.edit") : t("tenders.library.add")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!form.title.trim()} busy={save.isPending} data-testid="doc-save" onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="flex flex-col gap-3" data-testid="doc-dialog">
        <Field label={t("tenders.library.titleField")} htmlFor="cd-title"><Input id="cd-title" dir="auto" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label={t("tenders.library.category")} htmlFor="cd-cat"><Select id="cd-cat" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{t(`tenders.library.categories.${c}`)}</option>)}</Select></Field>
        <div className="flex flex-wrap gap-3">
          <Field label={t("tenders.library.issued")} htmlFor="cd-issued"><DateInput id="cd-issued" value={form.issued_on ? fromDateString(form.issued_on) : null} onChange={(d) => setForm({ ...form, issued_on: d ? toDateString(d) : null })} /></Field>
          <Field label={t("tenders.library.expires")} htmlFor="cd-expires"><DateInput id="cd-expires" value={form.expires_on ? fromDateString(form.expires_on) : null} onChange={(d) => setForm({ ...form, expires_on: d ? toDateString(d) : null })} /></Field>
        </div>
        <Field label={t("tenders.library.file")} htmlFor="cd-file">
          <span className="flex flex-wrap items-center gap-2"><input id="cd-file" type="file" className="text-sm" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            {form.document_id && <Link className="text-xs text-accent hover:underline" to={`/documents/${form.document_id}`}>{t("tenders.library.fileSet")}</Link>}</span>
        </Field>
        <Field label={t("tenders.library.note")} htmlFor="cd-note"><Input id="cd-note" dir="auto" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
        <ErrorNote error={upload.error || save.error} />
      </div>
    </Modal>
  );
}

export function CompanyDocumentsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const expiry = params.get("expiry") ?? "";
  const docs = useQuery({ queryKey: ["company-documents", expiry], queryFn: () => api<CompanyDocumentRow[]>("/api/company-documents", { query: expiry ? { expiry } : {} }) });
  const suggestions = useQuery({ queryKey: ["company-documents", "suggestions"], queryFn: () => api<{ title: string; category: string }[]>("/api/company-documents/suggestions") });
  const [dialog, setDialog] = useState<{ doc: CompanyDocumentRow | null; initial?: { title: string; category: string } } | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["company-documents"] });
  const archive = useMutation({ mutationFn: (id: string) => api(`/api/company-documents/${id}`, { method: "PATCH", body: { status: "archived" } }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/company-documents/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const existing = new Set((docs.data ?? []).map((d) => d.title));
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <PageHeader title={t("nav.sub.companyDocuments")} subtitle={t("tenders.library.subtitle")}
        actions={<Button variant="primary" icon="plus" onClick={() => setDialog({ doc: null })} data-testid="add-doc">{t("tenders.library.add")}</Button>} />
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label={t("tenders.library.filter")} className="w-auto" value={expiry} onChange={(e) => setParams(e.target.value ? { expiry: e.target.value } : {}, { replace: true })}>
          <option value="">{t("tenders.library.all")}</option>{(["ok", "soon", "expired", "none"] as const).map((x) => <option key={x} value={x}>{t(`tenders.library.expiry.${x}`)}</option>)}</Select>
        <span className="text-xs text-muted">{t("tenders.library.quickAdd")}:</span>
        {(suggestions.data ?? []).filter((s) => !existing.has(s.title)).map((s) => (
          <button key={s.title} type="button" className="rounded-full border border-line px-2 py-0.5 text-xs hover:bg-surface-2" dir="auto" onClick={() => setDialog({ doc: null, initial: s })}>+ {s.title}</button>))}
      </div>
      <Card padded={false}>
        {docs.isLoading ? <Loading /> : (docs.data ?? []).length === 0 ? <EmptyState>{t("tenders.library.empty")}</EmptyState> : (
          <ul className="divide-y divide-line" data-testid="company-documents">{docs.data!.map((d) => (
            <li key={d.id} className={`flex flex-wrap items-center gap-2 px-4 py-2 text-sm ${params.get("doc") === d.id ? "bg-accent-soft" : ""}`}>
              <span className="min-w-0 flex-1" dir="auto">{d.title}<span className="ms-2 text-xs text-muted">{t(`tenders.library.categories.${d.category}`)}</span></span>
              <Badge tone={TONE[d.expiry]}>{t(`tenders.library.expiry.${d.expiry}`)}{d.expires_on ? ` · ${f.day(d.expires_on)}` : ""}</Badge>
              {d.document_id ? <Link className="text-xs text-accent hover:underline" to={`/documents/${d.document_id}`}>{t("tenders.library.openFile")}</Link> : <span className="text-xs text-warning">{t("tenders.library.noFile")}</span>}
              <Button variant="ghost" onClick={() => setDialog({ doc: d })}>{t("common.edit")}</Button>
              <Button variant="ghost" onClick={() => archive.mutate(d.id)}>{t("tenders.library.archive")}</Button>
              <Button variant="ghost" onClick={() => remove.mutate(d.id)}>{t("common.remove")}</Button>
            </li>))}</ul>
        )}
        <ErrorNote error={archive.error || remove.error} />
      </Card>
      {dialog && <DocDialog doc={dialog.doc} initial={dialog.initial} onClose={() => setDialog(null)} onSaved={refresh} />}
    </div>
  );
}
