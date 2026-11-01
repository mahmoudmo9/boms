/** Side panel of one listing (v0.6.0: a header with the actions and tabs like the sections of Setad's own detail page):
 * fields grouped as SetadSuite does, schedule with live time left, items, attachments (preview, open in Windows,
 * folder), screening, history, and the technical fields (site titles first) behind a toggle. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { TimeLeftBadge } from "../../components/TimeLeft";
import { Badge, Button, Checkbox, ErrorNote, Field, Input, Loading, Modal, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { groupTechnical, listingJobState, siteDate, type TechRow, technicalLabel, valueLabel } from "../../lib/setadFields";
import { stripRemainingRemark } from "../../lib/timeLeft";
import { useAgent } from "./ConnectionBar";
import { useFormat } from "../../lib/prefs";
import type { ListingDetail, ListingFile, SettingsResponse } from "../../lib/types";

const PREVIEWABLE = new Set(["pdf", "png", "jpg", "jpeg", "gif", "webp", "bmp", "txt"]);
const DATE_FIELDS = ["published_at", "response_deadline", "documents_deadline", "proposal_deadline", "inquiry_deadline",
  "opening_at", "price_valid_until"] as const;

export function DismissDialog({ onClose, onConfirm, busy, error }: { onClose: () => void; onConfirm: (reason: string) => void; busy: boolean; error: unknown }) {
  const { t } = useTranslation();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const reasons = ((settings.data?.values as Record<string, unknown> | undefined)?.["setad.dismiss_reasons"] as string[] | undefined) ?? [];
  const [reason, setReason] = useState("");
  return (
    <Modal open title={t("listings.dismiss")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="danger" disabled={!reason.trim()} busy={busy} onClick={() => onConfirm(reason.trim())}>{t("listings.dismiss")}</Button></>}>
      <Field label={t("listings.dismissReason")} htmlFor="dismiss-reason">
        <Select id="dismiss-reason" className="w-full" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="">—</option>
          {reasons.map((r) => <option key={r} value={r}>{r}</option>)}
        </Select>
      </Field>
      <ErrorNote error={error} />
    </Modal>
  );
}

function ConfirmSiteAction({ title, text, onClose, onConfirm, busy, error }: { title: string; text: string; onClose: () => void; onConfirm: () => void; busy: boolean; error: unknown }) {
  const { t } = useTranslation();
  const [sure, setSure] = useState(false);
  return (
    <Modal open title={title} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!sure} busy={busy} onClick={onConfirm}>{t("listings.confirmOnSetad")}</Button></>}>
      <p className="mb-3 text-sm">{text}</p>
      <Checkbox label={t("listings.confirmSure")} checked={sure} onChange={setSure} />
      <ErrorNote error={error} />
    </Modal>
  );
}

function FileRow({ file }: { file: ListingFile }) {
  const { t } = useTranslation();
  const open = useMutation({ mutationFn: (folder: boolean) => api(`/api/listings/files/${file.id}/open`, { method: "POST", query: { folder } }) });
  const ext = (file.extension || file.name.split(".").pop() || "").toLowerCase();
  const ready = file.state === "downloaded";
  return (
    <li className="flex flex-wrap items-center gap-2 py-1 text-sm">
      <Bdi className={ready ? "" : "text-muted"}>{file.name}</Bdi>
      <Badge tone={ready ? "success" : file.state === "missing" || file.state === "error" ? "danger" : "neutral"}>{t(`listings.fileState.${file.state}`)}</Badge>
      <span className="ms-auto flex gap-1">
        {ready && PREVIEWABLE.has(ext) && <a className="inline-flex h-7 items-center rounded px-2 text-xs text-accent hover:bg-surface-2"
          href={`/api/listings/files/${file.id}/content`} target="_blank" rel="noreferrer">{t("listings.preview")}</a>}
        {ready && <Button variant="ghost" onClick={() => open.mutate(false)}>{t("listings.openWindows")}</Button>}
        {ready && <Button variant="ghost" onClick={() => open.mutate(true)}>{t("listings.openFolder")}</Button>}
      </span>
      <ErrorNote error={open.error} />
    </li>
  );
}

export const PANEL_TABS = ["fields", "schedule", "items", "files", "screening", "history", "technical"] as const;
export type PanelTab = (typeof PANEL_TABS)[number];

/** A label/value list on a two-column grid (no absolute positioning; long values wrap; nothing leaves the panel). */
function FieldList({ rows }: { rows: { key: string; label: ReactNode; hint?: string; value: ReactNode }[] }) {
  return (
    <dl className="grid min-w-0 grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
      {rows.map((r) => [
        <dt key={`${r.key}-l`} className="min-w-0 text-muted" dir="auto">{r.label}
          {r.hint && <span className="block truncate font-mono text-[10px] text-muted/70" dir="ltr" title={r.hint}>{r.hint}</span>}</dt>,
        <dd key={`${r.key}-v`} className="min-w-0 [overflow-wrap:anywhere]">{r.value}</dd>,
      ])}
    </dl>
  );
}

/** URLs and codes: one line, left-to-right, with copy and open. */
function LinkValue({ url }: { url: string }) {
  const { t } = useTranslation();
  return (
    <span className="flex min-w-0 items-center gap-1">
      <bdi dir="ltr" className="min-w-0 flex-1 truncate font-mono text-xs" title={url}>{url}</bdi>
      <button type="button" className="shrink-0 text-xs text-accent hover:underline" onClick={() => void navigator.clipboard?.writeText(url)}>{t("listings.copy")}</button>
      <a className="shrink-0 text-xs text-accent hover:underline" href={url} target="_blank" rel="noreferrer">{t("listings.open")}</a>
    </span>
  );
}

function SiteValue({ value }: { value: string }) {
  const f = useFormat();
  const date = siteDate(value);
  if (date) return <span className="tabular-nums">{f.date(date.iso, date.time)}</span>;
  if (/^https?:\/\//i.test(value.trim())) return <LinkValue url={value.trim()} />;
  return <span dir="auto">{stripRemainingRemark(value)}</span>;
}

export function ListingPanel({ id, onClose, onConvert, tab, onTab, refreshKey }: {
  id: string; onClose: () => void; onConvert?: (id: string) => void; tab: PanelTab; onTab: (t: PanelTab) => void; refreshKey?: number;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const lang = f.lang === "fa" ? "fa" : "en";
  const queryClient = useQueryClient();
  const agent = useAgent();
  const [technical, setTechnical] = useState(() => load("boms.listings.technical") === "1");
  const [techFilter, setTechFilter] = useState("");
  const [dialog, setDialog] = useState<null | "dismiss" | "add" | "remove">(null);
  // cached detail shows at once; a refresh runs in the background (moving with the keyboard reuses the cache)
  const detail = useQuery({ queryKey: ["listing", id], queryFn: () => api<ListingDetail>(`/api/listings/${id}`), staleTime: Infinity,
    placeholderData: keepPreviousData });
  useEffect(() => { if (refreshKey) void detail.refetch(); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const screen = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<ListingDetail>(`/api/listings/${id}/screen`, { method: "POST", body }),
    onSuccess: (d) => { queryClient.setQueryData(["listing", id], d); setDialog(null); void queryClient.invalidateQueries({ queryKey: ["listings"] }); },
  });
  const command = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      if (!agent.data?.alive) await api("/api/setad/agent/start", { method: "POST" });
      return api("/api/setad/commands", { method: "POST", body });
    },
    onSuccess: () => { setDialog(null); void queryClient.invalidateQueries({ queryKey: ["setad-agent"] }); },
  });
  const [note, setNote] = useState("");
  useEffect(() => { setNote(detail.data?.screening?.note ?? ""); }, [detail.data?.screening?.note]);
  const downloading = listingJobState(agent.data, id, "download_files");
  const detailing = listingJobState(agent.data, id, "fetch_detail");
  const shell = "flex h-full min-h-0 w-full flex-col overflow-hidden rounded-md border border-line bg-surface";
  if (detail.isLoading) return <aside className={shell} data-testid="listing-panel"><Loading /></aside>;
  if (!detail.data) return <aside className={shell} data-testid="listing-panel"><ErrorNote error={detail.error} /></aside>;
  const d = detail.data;
  const l = d.listing;
  const s = d.screening;
  const status = s?.status ?? "new";
  const converted = status === "converted";
  const tender = l.source === "setad_tender";
  const checks = d.checklist_questions.map((_, i) => Boolean(s?.checklist?.[i]));
  const tabs = PANEL_TABS.filter((x) => x !== "technical" || technical);
  const current: PanelTab = tabs.includes(tab) ? tab : "fields";
  const jobText = (job: ReturnType<typeof listingJobState>, kind: "download" | "detail") => !job ? null
    : job.state === "queued" ? t(`listings.job.${kind}Queued`)
      : job.total ? t(`listings.job.${kind}Running`, { n: f.num(job.done ?? 0), total: f.num(job.total) }) : t(`listings.job.${kind}Started`);
  const techRows: TechRow[] = d.technical.map(([key, value]) => ({ key, label: technicalLabel(key, null, lang), value: valueLabel(value, lang) }));
  return (
    <aside className={shell} data-testid="listing-panel" aria-label={t("listings.panel")}>
      <header className="shrink-0 border-b border-line p-3">
        <div className="mb-1 flex items-start gap-2">
          <h2 className="min-w-0 flex-1 text-base font-semibold [overflow-wrap:anywhere]" dir="auto">{l.title}</h2>
          <button type="button" className="shrink-0 text-muted hover:text-fg" aria-label={t("common.close")} onClick={onClose}>✕</button>
        </div>
        <p className="mb-2 flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted">
          <bdi dir="ltr" className="font-mono">{l.external_no}</bdi><span className="min-w-0 truncate" dir="auto" title={l.organization}>{l.organization}</span>
          <Badge tone={converted ? "success" : status === "dismissed" ? "neutral" : status === "starred" ? "warning" : "accent"}>{t(`listings.status.${status}`)}</Badge>
          {d.warn.map((w) => <Badge key={w} tone="danger">⚠ <Bdi>{w}</Bdi></Badge>)}
        </p>
        {converted && s?.inquiry_id && <p className="mb-2 text-sm"><Link className="text-accent hover:underline" to={`/sourcing/inquiries/${s.inquiry_id}`}>{t("listings.convertedTo")}</Link></p>}
        <div className="flex flex-wrap gap-1.5" data-testid="panel-actions">
          {!converted && (status === "starred"
            ? <Button onClick={() => screen.mutate({ action: "unstar" })}>{t("listings.unstar")}</Button>
            : <Button onClick={() => screen.mutate({ action: "star" })}>★ {t("listings.star")}</Button>)}
          {!converted && status !== "reviewing" && <Button onClick={() => screen.mutate({ action: "reviewing" })}>{t("listings.reviewing")}</Button>}
          {!converted && (status === "dismissed"
            ? <Button onClick={() => screen.mutate({ action: "restore" })}>{t("listings.restore")}</Button>
            : <Button variant="ghost" onClick={() => setDialog("dismiss")}>{t("listings.dismiss")}</Button>)}
          <Button disabled={Boolean(detailing)} onClick={() => command.mutate({ command: "fetch_detail", listing_ids: [id] })}>{t("listings.fetchDetail")}</Button>
          <Button disabled={Boolean(downloading)} onClick={() => command.mutate({ command: "download_files", listing_ids: [id] })}>{t("listings.download")}</Button>
          {!converted && (status === "starred" || status === "reviewing") && onConvert &&
            <Button variant="primary" onClick={() => onConvert(id)}>{t("listings.convert")}</Button>}
          {l.detail_url && <a className="inline-flex h-8 items-center rounded-md px-2 text-sm text-accent hover:bg-surface-2" href={l.detail_url} target="_blank" rel="noreferrer">{t("listings.openOnSetad")}</a>}
          {tender && (l.in_my_calls
            ? <Button variant="ghost" onClick={() => setDialog("remove")}>{t("listings.removeMyCalls")}</Button>
            : <Button onClick={() => setDialog("add")}>{t("listings.addMyCalls")}</Button>)}
          {tender && l.in_my_calls && <Button variant="ghost" onClick={() => command.mutate({ command: "open_payment_page", listing_id: id })}>{t("listings.paymentPage")}</Button>}
        </div>
        {(downloading || detailing) && <p className="mt-2 text-xs text-accent" role="status" data-testid="panel-job">
          {[jobText(detailing, "detail"), jobText(downloading, "download")].filter(Boolean).join(" · ")}</p>}
        <ErrorNote error={screen.error || command.error} />
        <div className="mt-2 flex items-center gap-2">
          <div className="flex min-w-0 flex-1 gap-0.5 overflow-x-auto" role="tablist" data-testid="panel-tabs">
            {tabs.map((x) => (
              <button key={x} type="button" role="tab" aria-selected={current === x} onClick={() => onTab(x)} data-testid={`panel-tab-${x}`}
                className={`shrink-0 rounded px-2 py-1 text-xs ${current === x ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-surface-2"}`}>{t(`listings.tabs.${x}`)}</button>
            ))}
          </div>
          {d.technical.length > 0 && <Checkbox label={t("listings.technical")} checked={technical}
            onChange={(v) => { setTechnical(v); save("boms.listings.technical", v ? "1" : "0"); if (!v && current === "technical") onTab("fields"); }} />}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3 text-sm" data-testid="panel-body">
        {current === "fields" && (d.groups.length === 0 ? <p className="text-muted">{t("listings.noDetailYet")}</p> : d.groups.map((g) => (
          <section key={g.title} className="mb-3">
            <h3 className="mb-1.5 text-xs font-medium text-muted" dir="auto">{g.title}</h3>
            <FieldList rows={g.pairs.map(([k, v], i) => ({ key: `${g.title}-${i}`, label: k, value: <SiteValue value={v} /> }))} />
          </section>
        )))}
        {current === "schedule" && (
          <FieldList rows={[
            ...DATE_FIELDS.filter((k) => l[k]).map((k) => ({ key: k, label: t(`listings.dates.${k}`), value: (
              <span className="flex flex-wrap items-center gap-1.5"><span className="tabular-nums">{f.date(l[k], true)}</span>
                {k !== "published_at" && <TimeLeftBadge at={l[k]} estimate={k === "response_deadline" && !l.deadline_exact} />}</span>) })),
            ...(tender && l.document_price !== null ? [{ key: "price", label: t("listings.documentPrice"),
              value: <bdi dir="ltr" className="tabular-nums">{Number(l.document_price) === 0 ? t("listings.free") : `${f.num(l.document_price)} IRR`}</bdi> }] : []),
            ...(l.guarantee_amount !== null ? [{ key: "guarantee", label: t("listings.guaranteeAmount"),
              value: <span><bdi dir="ltr" className="tabular-nums">{f.num(l.guarantee_amount)}</bdi> {l.guarantee_currency}{l.guarantee_description ? <span className="block text-xs text-muted" dir="auto">{l.guarantee_description}</span> : null}</span> }] : []),
            ...(l.estimate !== null ? [{ key: "estimate", label: t("listings.estimateAmount"),
              value: <span><bdi dir="ltr" className="tabular-nums">{f.num(l.estimate)}</bdi> {l.estimate_currency}</span> }] : []),
          ]} />
        )}
        {current === "items" && (<>
          {d.detail?.buyer_note && <section className="mb-3"><h3 className="mb-1 text-xs font-medium text-muted">{t("listings.buyerNote")}</h3>
            <p dir="auto" className="whitespace-pre-wrap [overflow-wrap:anywhere]">{d.detail.buyer_note}</p></section>}
          {d.detail && d.detail.items.rows.length > 0 ? (
            <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="listing-items"><thead><tr className="text-muted">{d.detail.items.headers.map((h) => <th key={h} className="p-1 text-start" dir="auto">{h}</th>)}</tr></thead>
              <tbody>{d.detail.items.rows.map((r, i) => <tr key={i} className="border-t border-line">{r.map((c, j) => <td key={j} className="p-1" dir="auto"><SiteValue value={c} /></td>)}</tr>)}</tbody></table></div>
          ) : <p className="text-muted">{d.detail ? t("listings.noItems") : t("listings.fetchFirst")}</p>}
        </>)}
        {current === "files" && (d.files.length === 0
          ? <p className="text-muted">{d.detail ? t("listings.noAttachments") : t("listings.fetchFirst")}</p>
          : <ul className="divide-y divide-line" data-testid="listing-files">{d.files.map((file) => <FileRow key={file.id} file={file} />)}</ul>)}
        {current === "screening" && (
          <div className="flex flex-col gap-1.5">
            {d.checklist_questions.map((q, i) => (
              <Checkbox key={q} label={q} checked={checks[i]} onChange={(v) => screen.mutate({ action: "checklist", checklist: checks.map((c, j) => (j === i ? v : c)) })} />
            ))}
            <Field label={t("listings.note")} htmlFor="listing-note">
              <Textarea id="listing-note" dir="auto" rows={3} value={note} onChange={(e) => setNote(e.target.value)}
                onBlur={() => note !== (s?.note ?? "") && screen.mutate({ action: "note", note })} />
            </Field>
          </div>
        )}
        {current === "history" && (
          <ul className="flex flex-col gap-1 text-xs" data-testid="listing-changes">
            {d.changes.map((c, i) => (
              <li key={`c${i}`} className="[overflow-wrap:anywhere]"><span className="tabular-nums text-muted">{f.date(c.at, true)}</span> · {t(`listings.fields.${c.field}`, { defaultValue: c.field })}:{" "}
                <Bdi ltr>{fmtValue(c.old, f)}</Bdi> → <Bdi ltr>{fmtValue(c.new, f)}</Bdi></li>))}
            {d.events.map((e, i) => (
              <li key={`e${i}`} className="[overflow-wrap:anywhere]"><span className="tabular-nums text-muted">{f.date(e.at, true)}</span> · {t(`listings.actions.${e.action}`, { defaultValue: e.action })}
                {e.data.reason ? ` · ${String(e.data.reason)}` : ""}{e.data.result ? ` · ${t(`listings.results.${String(e.data.result)}`, { defaultValue: String(e.data.result) })}` : ""}</li>))}
            {d.changes.length === 0 && d.events.length === 0 && <li className="text-muted">{t("listings.noHistory")}</li>}
          </ul>
        )}
        {current === "technical" && (<>
          <Input dir="auto" className="mb-2 w-full" aria-label={t("listings.technicalFilter")} placeholder={t("listings.technicalFilter")}
            value={techFilter} onChange={(e) => setTechFilter(e.target.value)} />
          {groupTechnical(techRows, techFilter).map((g) => (
            <section key={g.group} className="mb-3" data-testid="technical-fields">
              <h3 className="mb-1.5 text-xs font-medium text-muted">{t(`listings.techGroups.${g.group}`)}</h3>
              <FieldList rows={g.rows.map((r) => ({ key: r.key, label: r.label ?? <bdi dir="ltr" className="font-mono text-xs">{r.key}</bdi>,
                hint: r.label ? r.key : undefined, value: <SiteValue value={r.value} /> }))} />
            </section>
          ))}
        </>)}
      </div>
      {dialog === "dismiss" && <DismissDialog onClose={() => setDialog(null)} busy={screen.isPending} error={screen.error}
        onConfirm={(reason) => screen.mutate({ action: "dismiss", reason })} />}
      {(dialog === "add" || dialog === "remove") && (
        <ConfirmSiteAction title={dialog === "add" ? t("listings.addMyCalls") : t("listings.removeMyCalls")}
          text={t(dialog === "add" ? "listings.addMyCallsText" : "listings.removeMyCallsText", { number: l.external_no })}
          busy={command.isPending} error={command.error} onClose={() => setDialog(null)}
          onConfirm={() => command.mutate({ command: dialog === "add" ? "add_my_call" : "remove_my_call", listing_id: id, confirmed: true })} />
      )}
    </aside>
  );
}

function load(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function save(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* not remembered */ }
}

function fmtValue(v: string | null, f: ReturnType<typeof useFormat>): string {
  if (v === null || v === "") return "—";
  return /^\d{4}-\d{2}-\d{2}T/.test(v) ? f.date(v, true) : v;
}
