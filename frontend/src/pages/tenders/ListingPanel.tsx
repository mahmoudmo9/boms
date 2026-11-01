/** Side panel of one listing: fields grouped as SetadSuite does (technical fields behind a toggle), items, attachments
 * (preview, open in Windows, folder), change history, screening actions and site actions. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Badge, Button, Checkbox, ErrorNote, Field, Loading, Modal, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { daysLeft, deadlineTone } from "../../lib/listings";
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

export function ListingPanel({ id, onClose, onConvert }: { id: string; onClose: () => void; onConvert?: (id: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const [technical, setTechnical] = useState(false);
  const [dialog, setDialog] = useState<null | "dismiss" | "add" | "remove">(null);
  const detail = useQuery({ queryKey: ["listing", id], queryFn: () => api<ListingDetail>(`/api/listings/${id}`) });
  const screen = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<ListingDetail>(`/api/listings/${id}/screen`, { method: "POST", body }),
    onSuccess: (d) => { queryClient.setQueryData(["listing", id], d); setDialog(null); void queryClient.invalidateQueries({ queryKey: ["listings"] }); },
  });
  const command = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const agent = await api<{ alive: boolean }>("/api/setad/agent");
      if (!agent.alive) await api("/api/setad/agent/start", { method: "POST" });
      return api("/api/setad/commands", { method: "POST", body });
    },
    onSuccess: () => { setDialog(null); void queryClient.invalidateQueries({ queryKey: ["setad-agent"] }); },
  });
  const [note, setNote] = useState("");
  useEffect(() => { setNote(detail.data?.screening?.note ?? ""); }, [detail.data?.screening?.note]);
  if (detail.isLoading) return <aside className="order-first w-full xl:order-none xl:w-[24rem] xl:shrink-0"><Loading /></aside>;
  if (!detail.data) return <aside className="order-first w-full xl:order-none xl:w-[24rem] xl:shrink-0"><ErrorNote error={detail.error} /></aside>;
  const d = detail.data;
  const l = d.listing;
  const s = d.screening;
  const status = s?.status ?? "new";
  const converted = status === "converted";
  const tender = l.source === "setad_tender";
  const checks = d.checklist_questions.map((_, i) => Boolean(s?.checklist?.[i]));
  return (
    <aside className="order-first flex w-full flex-col gap-3 xl:order-none xl:w-[24rem] xl:shrink-0" data-testid="listing-panel" aria-label={t("listings.panel")}>
      <div className="rounded-md border border-line bg-surface p-3">
        <div className="mb-1 flex items-start gap-2">
          <h2 className="min-w-0 flex-1 text-base font-semibold" dir="auto">{l.title}</h2>
          <button type="button" className="text-muted hover:text-fg" aria-label={t("common.close")} onClick={onClose}>✕</button>
        </div>
        <p className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted">
          <Bdi ltr className="font-mono">{l.external_no}</Bdi><Bdi>{l.organization}</Bdi>
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
          <Button onClick={() => command.mutate({ command: "fetch_detail", listing_ids: [id] })}>{t("listings.fetchDetail")}</Button>
          <Button onClick={() => command.mutate({ command: "download_files", listing_ids: [id] })}>{t("listings.download")}</Button>
          {!converted && (status === "starred" || status === "reviewing") && onConvert &&
            <Button variant="primary" onClick={() => onConvert(id)}>{t("listings.convert")}</Button>}
          {l.detail_url && <a className="inline-flex h-8 items-center rounded-md px-2 text-sm text-accent hover:bg-surface-2" href={l.detail_url} target="_blank" rel="noreferrer">{t("listings.openOnSetad")}</a>}
          {tender && (l.in_my_calls
            ? <Button variant="ghost" onClick={() => setDialog("remove")}>{t("listings.removeMyCalls")}</Button>
            : <Button onClick={() => setDialog("add")}>{t("listings.addMyCalls")}</Button>)}
          {tender && l.in_my_calls && <Button variant="ghost" onClick={() => command.mutate({ command: "open_payment_page", listing_id: id })}>{t("listings.paymentPage")}</Button>}
        </div>
        <ErrorNote error={screen.error || command.error} />
      </div>

      <section className="rounded-md border border-line bg-surface p-3 text-sm">
        <h3 className="mb-2 font-medium">{t("listings.schedule")}</h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {DATE_FIELDS.filter((k) => l[k]).map((k) => {
            const days = k === "published_at" ? null : daysLeft(l[k]);
            return [<dt key={`${k}-t`} className="text-muted">{t(`listings.dates.${k}`)}</dt>,
              <dd key={`${k}-v`} className="tabular-nums">{f.date(l[k], true)}
                {days !== null && <Badge tone={deadlineTone(days)}>{days < 0 ? t("listings.passed") : t("listings.daysLeft", { count: days, n: f.num(days) })}</Badge>}
                {k === "response_deadline" && !l.deadline_exact && <span className="ms-1 text-xs text-muted">({t("listings.estimate")})</span>}</dd>];
          })}
          {tender && l.document_price !== null && <><dt className="text-muted">{t("listings.documentPrice")}</dt>
            <dd><Bdi ltr className="tabular-nums">{Number(l.document_price) === 0 ? t("listings.free") : `${f.num(l.document_price)} IRR`}</Bdi></dd></>}
        </dl>
      </section>

      {d.groups.map((g) => (
        <section key={g.title} className="rounded-md border border-line bg-surface p-3 text-sm">
          <h3 className="mb-2 font-medium" dir="auto">{g.title}</h3>
          <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1">
            {g.pairs.map(([k, v], i) => [<dt key={`k${i}`} className="text-muted" dir="auto">{k}</dt>, <dd key={`v${i}`} dir="auto" className="break-words">{v}</dd>])}
          </dl>
        </section>
      ))}
      {d.technical.length > 0 && (
        <section className="rounded-md border border-line bg-surface p-3 text-sm">
          <Checkbox label={t("listings.technical")} checked={technical} onChange={setTechnical} />
          {technical && <dl className="mt-2 grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1 text-xs">
            {d.technical.map(([k, v]) => [<dt key={`k${k}`} className="font-mono text-muted" dir="ltr">{k}</dt>, <dd key={`v${k}`} dir="auto" className="break-words">{v}</dd>])}
          </dl>}
        </section>
      )}
      {d.detail?.buyer_note && <section className="rounded-md border border-line bg-surface p-3 text-sm">
        <h3 className="mb-1 font-medium">{t("listings.buyerNote")}</h3><p dir="auto" className="whitespace-pre-wrap">{d.detail.buyer_note}</p></section>}
      {d.detail && d.detail.items.rows.length > 0 && (
        <section className="overflow-x-auto rounded-md border border-line bg-surface p-3 text-sm">
          <h3 className="mb-2 font-medium">{t("listings.items")}</h3>
          <table className="w-full text-xs" data-testid="listing-items"><thead><tr className="text-muted">{d.detail.items.headers.map((h) => <th key={h} className="p-1 text-start" dir="auto">{h}</th>)}</tr></thead>
            <tbody>{d.detail.items.rows.map((r, i) => <tr key={i} className="border-t border-line">{r.map((c, j) => <td key={j} className="p-1" dir="auto">{c}</td>)}</tr>)}</tbody></table>
        </section>
      )}
      <section className="rounded-md border border-line bg-surface p-3">
        <h3 className="mb-1 text-sm font-medium">{t("listings.attachments")}</h3>
        {d.files.length === 0
          ? <p className="text-sm text-muted">{d.detail ? t("listings.noAttachments") : t("listings.fetchFirst")}</p>
          : <ul className="divide-y divide-line" data-testid="listing-files">{d.files.map((file) => <FileRow key={file.id} file={file} />)}</ul>}
      </section>
      <section className="rounded-md border border-line bg-surface p-3 text-sm">
        <h3 className="mb-2 font-medium">{t("listings.checklist")}</h3>
        <div className="flex flex-col gap-1.5">
          {d.checklist_questions.map((q, i) => (
            <Checkbox key={q} label={q} checked={checks[i]} onChange={(v) => screen.mutate({ action: "checklist", checklist: checks.map((c, j) => (j === i ? v : c)) })} />
          ))}
        </div>
        <Field label={t("listings.note")} htmlFor="listing-note">
          <Textarea id="listing-note" dir="auto" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
            onBlur={() => note !== (s?.note ?? "") && screen.mutate({ action: "note", note })} />
        </Field>
      </section>
      {d.changes.length > 0 && (
        <section className="rounded-md border border-line bg-surface p-3 text-sm">
          <h3 className="mb-2 font-medium">{t("listings.changes")}</h3>
          <ul className="flex flex-col gap-1 text-xs" data-testid="listing-changes">{d.changes.map((c, i) => (
            <li key={i}><span className="tabular-nums text-muted">{f.date(c.at, true)}</span> · {t(`listings.fields.${c.field}`, { defaultValue: c.field })}:{" "}
              <Bdi ltr>{fmtValue(c.old, f)}</Bdi> → <Bdi ltr>{fmtValue(c.new, f)}</Bdi></li>))}</ul>
        </section>
      )}
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

function fmtValue(v: string | null, f: ReturnType<typeof useFormat>): string {
  if (v === null || v === "") return "—";
  return /^\d{4}-\d{2}-\d{2}T/.test(v) ? f.date(v, true) : v;
}
