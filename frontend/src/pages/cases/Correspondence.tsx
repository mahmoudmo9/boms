/** v0.10.1 (0.4.6) the case's «مکاتبات»: every incoming and outgoing interaction of the case, newest first, grouped by
 * party with a filter; each row with direction, channel, contact, subject, the first lines, attachments and the record
 * it concerns. «ثبت مکاتبه» and an .eml drop record a new one here. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { EmlDialog, EmlDrop, type EmlPreview } from "../../components/EmlIntake";
import { FileType } from "../../components/FileType";
import { Badge, Bdi, Button, Card, EmptyState, Icon, Loading, Segmented } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { CaseDetail } from "../../lib/types";
import { useQuickLog } from "../parties/QuickLog";

export interface ThreadItem { id: string; party_id: string; contact_id: string | null; channel: string; direction: "in" | "out"; occurred_at: string;
  subject: string | null; excerpt: string | null; ref_type: string | null; ref_id: string | null; ref_code: string | null; raw_document_id: string | null;
  party_name_fa: string | null; party_name_en: string | null; contact_name_fa: string | null; contact_name_en: string | null;
  files: { id: string; title: string; filename: string; mime_type: string; size: number; role: string }[] }
export interface CaseThread { items: ThreadItem[]; parties: { id: string; name_fa: string | null; name_en: string | null }[] }

export function useCaseThread(caseId: string) {
  return useQuery({ queryKey: ["case-thread", caseId], queryFn: () => api<CaseThread>(`/api/interactions/case/${caseId}`) });
}

export function CorrespondenceTab({ caseData }: { caseData: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const quickLog = useQuickLog();
  const thread = useCaseThread(caseData.id);
  const [party, setParty] = useState("all");
  const [eml, setEml] = useState<EmlPreview | null>(null);
  const name = (fa: string | null, en: string | null) => ((f.lang === "fa" ? fa || en : en || fa) ?? "");
  const items = (thread.data?.items ?? []).filter((i) => party === "all" || i.party_id === party);
  return (
    <Card title={t("case.thread.title")} testId="case-thread" actions={
      <Button icon="plus" onClick={() => quickLog.open(caseData.party_id ?? undefined, { caseId: caseData.id, label: caseData.code })} data-testid="thread-log">
        {t("case.thread.log")}</Button>}>
      <div className="mb-3"><EmlDrop compact onRead={setEml} /></div>
      {(thread.data?.parties.length ?? 0) > 1 && (
        <div className="mb-3"><Segmented size="sm" label={t("case.thread.party")} value={party} onChange={setParty}
          options={[{ value: "all", label: t("common.all") }, ...thread.data!.parties.map((p) => ({ value: p.id, label: name(p.name_fa, p.name_en) }))]} /></div>
      )}
      {thread.isLoading ? <Loading rows={4} /> : items.length === 0 ? <EmptyState>{t("case.thread.empty")}</EmptyState> : (
        <ol className="flex flex-col divide-y divide-line" data-testid="thread-list">
          {items.map((i) => (
            <li key={i.id} className="flex gap-3 py-3" data-testid="thread-item" data-direction={i.direction}>
              <span className={`mt-0.5 inline-grid size-7 shrink-0 place-items-center rounded-full ${i.direction === "in" ? "bg-info-soft text-info" : "bg-accent-soft text-accent"}`}
                title={t(`interactions.directions.${i.direction}`)}>
                <Icon name={i.direction === "in" ? "arrowStart" : "arrowEnd"} size={14} /></span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <Bdi className="font-medium text-fg">{name(i.party_name_fa, i.party_name_en)}</Bdi>
                  {(i.contact_name_fa || i.contact_name_en) && <span>· <Bdi>{name(i.contact_name_fa, i.contact_name_en)}</Bdi></span>}
                  <Badge>{t(`interactions.channels.${i.channel}`)}</Badge>
                  {i.ref_type && <Badge tone="accent">{t(`eml.refs.${i.ref_type}`)}{i.ref_code ? <> · <Bdi ltr>{i.ref_code}</Bdi></> : null}</Badge>}
                  {i.raw_document_id && <Badge icon="inbox">.eml</Badge>}
                  <span className="ms-auto tabular-nums">{f.date(i.occurred_at, true)}</span>
                </div>
                {i.subject && <p className="text-sm font-medium [unicode-bidi:plaintext]" dir="auto">{i.subject}</p>}
                {i.excerpt && <p className="line-clamp-3 text-sm whitespace-pre-line text-fg-2 [unicode-bidi:plaintext]" dir="auto">{i.excerpt}</p>}
                {i.files.filter((x) => x.role !== "source").length > 0 && (
                  <ul className="flex flex-wrap gap-2">{i.files.filter((x) => x.role !== "source").map((x) => (
                    <li key={x.id}><a href={`/documents/${x.id}`} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-0.5 text-xs hover:bg-hover">
                      <FileType mime={x.mime_type} name={x.filename} /><Bdi>{x.title || x.filename}</Bdi></a></li>))}</ul>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
      {eml && <EmlDialog preview={eml} fixed={{ caseId: caseData.id }} onClose={() => setEml(null)} />}
    </Card>
  );
}
