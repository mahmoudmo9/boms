/** The review screen (v0.9.0 section 2): the source on one side, the AI's proposal field by field on the other.
 * «پذیرش همهٔ موارد مطمئن», per-field accept / edit / reject, «ثبت». Nothing is written before «ثبت». */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { draftPoll, fromText, groupFields, rectStyle, reviewSummary, shownValue, sourceFocus, splitSpan, toText, type Draft, type DraftField, type FieldSource } from "../lib/ai";
import { Badge, Button, ErrorNote, Input, Modal, Spinner } from "../design/components";

const TONE = { high: "success", medium: "warning", low: "danger" } as const;

function FieldRow({ draft, field, focused, onFocus, onChanged }: { draft: Draft; field: DraftField; focused: boolean; onFocus: () => void; onChanged: () => void }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(toText(shownValue(field)));
  const decide = useMutation({
    mutationFn: (body: { decision: string; value?: unknown }) => api(`/api/ai/drafts/${draft.id}/fields/${field.id}`, { method: "PATCH", body }),
    onSuccess: () => { setEditing(false); onChanged(); },
  });
  const open = draft.status === "ready";
  return (
    <li className={`flex flex-col gap-1 border-b border-line px-1 py-2 ${focused ? "bg-accent-soft" : ""}`} data-testid="draft-field" data-path={field.path}
      data-decision={field.decision ?? "open"} data-focused={focused} onFocusCapture={onFocus} onMouseEnter={onFocus}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted"><bdi>{field.label ?? field.path}</bdi></span>
        <span className="flex items-center gap-1">
          <Badge tone={TONE[field.confidence]}>{t(`ai.review.confidence.${field.confidence}`)}</Badge>
          {field.source?.page && <Badge>{t("ai.review.page", { page: field.source.page })}</Badge>}
          {field.decision && <Badge tone={field.decision === "rejected" ? "danger" : "accent"}>{t(`ai.review.decision.${field.decision}`)}</Badge>}
        </span>
      </div>
      {editing ? (
        <span className="flex gap-1">
          <Input dir="auto" value={text} onChange={(e) => setText(e.target.value)} aria-label={field.label ?? field.path} />
          <Button variant="primary" onClick={() => decide.mutate({ decision: "edited", value: fromText(text, field.proposed) })}>{t("common.save")}</Button>
          <Button variant="ghost" onClick={() => setEditing(false)}>{t("common.cancel")}</Button>
        </span>
      ) : (
        <span className={`text-sm [overflow-wrap:anywhere] ${field.decision === "rejected" ? "text-muted line-through" : ""}`}><bdi>{toText(shownValue(field)) || "—"}</bdi></span>
      )}
      {field.source?.original && <span className="text-xs text-muted">«<bdi>{field.source.original}</bdi>»</span>}
      {open && !editing && (
        <span className="flex gap-1">
          <Button variant="ghost" onClick={() => decide.mutate({ decision: "accepted" })} data-testid="field-accept">{t("ai.review.accept")}</Button>
          <Button variant="ghost" onClick={() => { setText(toText(shownValue(field))); setEditing(true); }} data-testid="field-edit">{t("ai.review.edit")}</Button>
          <Button variant="ghost" onClick={() => decide.mutate({ decision: "rejected" })} data-testid="field-reject">{t("ai.review.reject")}</Button>
        </span>
      )}
      <ErrorNote error={decide.error} />
    </li>
  );
}

/** One PDF page as an image with the region of the field in focus drawn over it (v0.10.0). */
function PdfSource({ draft, index, pages, name, focus }: { draft: Draft; index: number; pages: number; name: string; focus: FieldSource | null }) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const active = sourceFocus(focus, index).active;
  const [followed, setFollowed] = useState<string | null>(null);
  if (active && focus?.page && followed !== focus.field_id) {        // follow the field in focus to its page, once per field
    setFollowed(focus.field_id);
    if (focus.page !== page) setPage(focus.page);
  }
  const rects = active && focus?.page === page ? focus.rects ?? [] : [];
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2 text-xs text-muted">
        <span className="flex items-center gap-1">
          <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label={t("ai.review.prevPage")}>‹</Button>
          <span data-testid="source-page">{t("ai.review.pageOf", { page, pages })}</span>
          <Button variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label={t("ai.review.nextPage")}>›</Button>
        </span>
        {active && focus?.page === page && (
          <span data-testid="source-found" data-found={focus.found}>{focus.found ? t("ai.review.regionFound") : t("ai.review.regionNotFound")}</span>
        )}
      </div>
      <div className="max-h-[32rem] overflow-auto rounded border border-line">
        <div className="relative" dir="ltr">
          <img alt={t("ai.review.pageImage", { name, page })} className="block w-full" src={`/api/ai/drafts/${draft.id}/sources/${index}/pages/${page}`} />
          {rects.map((r, i) => (
            <span key={i} aria-hidden className="pointer-events-none absolute rounded-sm border-2 border-accent bg-accent/20" style={rectStyle(r)} data-testid="source-region" />
          ))}
        </div>
      </div>
    </div>
  );
}

function SourcePanel({ draft, focus }: { draft: Draft; focus: FieldSource | null }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2" data-testid="draft-sources">
      {draft.sources.map((s, i) => {
        const here = sourceFocus(focus, i);
        const [before, marked, after] = s.kind === "pasted" && here.active ? splitSpan(s.text ?? "", focus?.start, focus?.end) : [s.text ?? "", "", ""];
        return (
          <div key={i} className={`rounded-md border p-2 text-sm ${here.active ? "border-accent" : "border-line"}`} data-testid="draft-source" data-active={here.active}>
            <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted">
              <bdi>{s.name ?? t(`ai.review.source.${s.kind}`)}</bdi>
              {s.pages ? <span>{t("ai.review.pages", { count: s.pages })}</span> : null}
            </div>
            {s.kind === "pdf" && s.document_id && <PdfSource draft={draft} index={i} pages={s.pages ?? 1} name={s.name ?? ""} focus={focus} />}
            {s.kind === "image" && s.document_id && <img alt={s.name} className="max-h-96 rounded border border-line" src={`/api/documents/${s.document_id}/preview`} />}
            {s.kind === "sheet" && s.preview && (
              <div className="max-h-96 overflow-auto"><table className="text-xs"><tbody>
                {s.preview.slice(0, 50).map((row, r) => (
                  <tr key={r} className={here.rows.has(r + 1) ? "bg-accent-soft outline outline-2 -outline-offset-2 outline-accent" : ""} data-testid={here.rows.has(r + 1) ? "source-row" : undefined}
                    ref={here.rows.has(r + 1) ? (el) => el?.scrollIntoView?.({ block: "nearest" }) : undefined}>
                    <td className="pe-2 text-muted">{r + 1}</td>{row.map((c, j) => <td key={j} className="border border-line px-1"><bdi>{c}</bdi></td>)}
                  </tr>))}
              </tbody></table></div>
            )}
            {s.kind === "pasted" && (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs" dir="auto">{before}{marked && <mark className="rounded-sm bg-accent-soft outline outline-2 outline-accent" data-testid="source-span">{marked}</mark>}{after}</pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Opens a draft by id: shows progress while the job runs, then the review. */
export function DraftReview({ draftId, open, onClose, onCommitted }: { draftId: string | null; open: boolean; onClose: () => void;
  onCommitted?: (result: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const draft = useQuery({
    queryKey: ["ai", "draft", draftId],
    queryFn: () => api<Draft>(`/api/ai/drafts/${draftId}`, { background: true }),
    enabled: Boolean(draftId) && open,
    refetchInterval: (q) => draftPoll(q.state.data?.status),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["ai", "draft", draftId] });
  const confident = useMutation({ mutationFn: () => api(`/api/ai/drafts/${draftId}/accept-confident`, { method: "POST" }), onSuccess: refresh });
  const commit = useMutation({
    mutationFn: () => api<Draft & { result: Record<string, unknown> }>(`/api/ai/drafts/${draftId}/commit`, { method: "POST" }),
    onSuccess: (d) => { refresh(); onCommitted?.(d.result ?? {}); },
  });
  const reject = useMutation({ mutationFn: () => api(`/api/ai/drafts/${draftId}/reject`, { method: "POST" }), onSuccess: () => { refresh(); onClose(); } });
  const d = draft.data;
  const sum = d ? reviewSummary(d) : null;
  // v0.10.0: the field in focus (keyboard focus or pointer) and where it comes from in the source
  const [focusId, setFocusId] = useState<string | null>(null);
  const focusField = d?.fields.find((f) => f.id === focusId && (f.source?.original || f.source?.page)) ?? null;
  const focus = useQuery({
    queryKey: ["ai", "draft", draftId, "source", focusField?.id],
    queryFn: () => api<FieldSource>(`/api/ai/drafts/${draftId}/fields/${focusField!.id}/source`, { background: true }),
    enabled: Boolean(focusField), staleTime: Infinity,
  });
  return (
    <Modal open={open} wide title={t("ai.review.title")} onClose={onClose} footer={d?.status === "ready" ? (
      <span className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted">{t("ai.review.summary", { accepted: sum!.accepted + sum!.edited, total: sum!.total })}</span>
        <Button disabled={!sum!.confidentOpen} busy={confident.isPending} onClick={() => confident.mutate()} data-testid="accept-confident">{t("ai.review.acceptConfident")}</Button>
        <Button variant="ghost" busy={reject.isPending} onClick={() => reject.mutate()}>{t("ai.review.rejectAll")}</Button>
        <Button variant="primary" disabled={!sum!.canCommit} busy={commit.isPending} onClick={() => commit.mutate()} data-testid="draft-commit">{t("ai.review.commit")}</Button>
      </span>) : undefined}>
      {!d || d.status === "pending" ? (
        <div className="flex items-center gap-2 p-6 text-sm text-muted" data-testid="draft-pending"><Spinner /> {t("ai.review.working")}</div>
      ) : d.status === "failed" ? (
        <p className="text-sm text-danger" data-testid="draft-failed">{t("ai.review.failed")} <bdi className="text-xs">{d.error}</bdi></p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2" data-testid="draft-review" data-status={d.status}>
          <SourcePanel draft={d} focus={focusField && focus.data?.field_id === focusField.id ? focus.data : null} />
          <div className="flex flex-col gap-2">
            {d.checks.length > 0 && (
              <div className="rounded-md border border-warning bg-warning-soft p-2 text-xs" data-testid="draft-checks">
                {d.checks.map((c, i) => <p key={i}>{t("ai.review.totalDiffers", { item: c.item + 1, stated: c.stated, computed: c.computed })}</p>)}
              </div>
            )}
            {[...groupFields(d.fields).entries()].map(([item, fields]) => (
              <section key={item} className="rounded-md border border-line px-2">
                <h3 className="pt-2 text-xs font-semibold">{item >= 0 ? t("ai.review.item", { n: item + 1 }) : t("ai.review.other")}</h3>
                <ul>{fields.map((f) => <FieldRow key={f.id} draft={d} field={f} focused={f.id === focusId} onFocus={() => setFocusId(f.id)} onChanged={refresh} />)}</ul>
              </section>
            ))}
            {d.status !== "ready" && <p className="text-sm text-muted">{t(`ai.review.status.${d.status}`)}</p>}
            <ErrorNote error={commit.error ?? confident.error} />
          </div>
        </div>
      )}
    </Modal>
  );
}
