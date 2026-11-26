/** v0.10.1 section 4.2 (reference ProCase / light Case): the story blocks of a case before its tabs — the hero, the
 * header facts as chips, the next step with its file drop, the people / documents / money trio and the deal story
 * rail. Data: the case, its costing and quotes, and the read-only case overview (GET /api/cases/{id}/overview). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { EventSentence } from "../../components/EventSentence";
import { FileType } from "../../components/FileType";
import { Button, buttonClass, Card, Chip, CodeChip, EmptyState, ErrorNote, FileDrop, Icon, ProgressRing, Status } from "../../design/components";
import { ApiError, api, type Page } from "../../lib/api";
import { pathPercent, pathSteps } from "../../lib/dealPath";
import { cashFigure } from "../../lib/execution";
import { useFormat } from "../../lib/prefs";
import type { CaseCosting, CaseDetail, CaseQuotes, DocumentDetail, EventItem } from "../../lib/types";
import { useExecution } from "./execution/shared";

export interface CaseOverviewData {
  deal_type: "import" | "export" | "domestic" | null;
  order: { id: string; number: string | null; total: string; currency: string; status: string } | null;
  customer: { id: string; code: string | null; name_fa: string | null; name_en: string | null } | null;
  next_step: ({ kind: "step"; id: string; label_fa: string; label_en: string; group: string | null; reference_label: string | null;
    requires_document: boolean; due_on: string | null; status: string } | { kind: "task"; id: string; title: string; due_on: string; due_at: string | null }) | null;
  people: { id: string; code: string | null; name_fa: string | null; name_en: string | null; role: string;
    contacts: { id: string; name_fa: string | null; name_en: string | null; job_title: string | null; is_primary: boolean }[] }[];
  documents: { count: number; files: { id: string; title: string; original_filename: string; mime_type: string }[];
    shipping: { kind: string; n: number }[]; missing: { id: string; label_fa: string; label_en: string; due_on: string | null }[] };
  money: { actual: Record<string, { received: string; paid: string; net_tied_up: string; tied_up?: string; advance?: string }>;
    expected_profit: { profit: string | null; currency: string | null; estimated: boolean } | null };
  forecast: { kind: "eta" | "step" | "payment" | "invoice_due"; on: string; ref?: string | null; label_fa?: string; label_en?: string;
    direction?: "in" | "out"; amount?: string; currency?: string; label?: string | null; milestone_kind?: string }[];
}

export function useCaseOverview(caseId: string) {
  return useQuery({ queryKey: ["case-overview", caseId], queryFn: () => api<CaseOverviewData>(`/api/cases/${caseId}/overview`) });
}

const name = (p: { name_fa: string | null; name_en: string | null } | null | undefined, lang: string) =>
  (p ? (lang === "fa" ? p.name_fa || p.name_en : p.name_en || p.name_fa) : null) ?? "";

/** Hero: the deal title in the display face, the deal type, one subtitle line (customer · order · amount), the
 * progress and margin rings; status and the case's actions sit in a compact bar under it (``actions``). */
export function CaseHero({ c, actions }: { c: CaseDetail; actions: ReactNode }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ov = useCaseOverview(c.id);
  const ex = useExecution(c.id);
  const costing = useQuery({ queryKey: ["costing", c.id], queryFn: () => api<CaseCosting>(`/api/cases/${c.id}/costing`) });
  const statuses = c.items.map((i) => i.status);
  const shipping = (ex.data?.shipments.length ?? 0) > 0;
  const progress = pathPercent(statuses, c.status, shipping);
  const margin = costing.data?.current?.margin_percent;
  const o = ov.data;
  const amount = o?.order ? f.compactMoney(o.order.total, o.order.currency) : null;
  return (
    <header className="flex flex-col gap-4" data-testid="case-hero">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-2">
            {o?.deal_type && <Status tone="accent" data-testid="case-type">{t(`case.type.${o.deal_type}`)}</Status>}
            <Link to="/cases" className="text-xs text-muted hover:text-accent">{t("nav.cases")}</Link>
          </div>
          <h1 className="font-display text-3xl font-semibold text-title [overflow-wrap:anywhere]"><bdi>{c.title}</bdi></h1>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-fg-2" data-testid="case-subtitle">
            {o?.customer && <Link to={`/parties/${o.customer.id}`} className="hover:text-accent"><bdi>{name(o.customer, f.lang)}</bdi></Link>}
            {o?.order?.number && <><span aria-hidden>·</span><bdi dir="ltr">{o.order.number}</bdi></>}
            {amount && <><span aria-hidden>·</span><span title={amount.full} className="tabular-nums">{amount.text}</span></>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-6" data-testid="case-rings">
          <div className="flex flex-col items-center gap-1.5">
            <ProgressRing value={progress} size={92} label={t("case.path.progress")}><span className="text-lg text-title tabular-nums">{f.num(progress)}٪</span></ProgressRing>
            <span className="text-xs text-muted">{t("case.path.progress")}</span>
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <ProgressRing value={margin != null ? Math.max(0, Math.min(100, Number(margin))) : 0} size={92} tone="success" label={t("costing.pricing.margin")}>
              <span className="text-lg text-title tabular-nums">{margin != null ? `${f.num(margin, 1)}٪` : "—"}</span></ProgressRing>
            <span className="text-xs text-muted">{t("costing.pricing.margin")}</span>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2" data-testid="case-actions">{actions}</div>
    </header>
  );
}

/** Header facts as chips (rule 2.4): codes, the latest quote, the delivery state, one cash figure per currency (1.4)
 * and the warnings. */
export function CaseFacts({ c, children }: { c: CaseDetail; children?: ReactNode }) {
  const { t } = useTranslation();
  const f = useFormat();
  const quotes = useQuery({ queryKey: ["case-quotes", c.id], queryFn: () => api<CaseQuotes>(`/api/cases/${c.id}/quotes`) });
  const ex = useExecution(c.id);
  const h = ex.data?.header;
  const latest = quotes.data?.summary.latest;
  const costing = useQuery({ queryKey: ["costing", c.id], queryFn: () => api<CaseCosting>(`/api/cases/${c.id}/costing`) });
  const exposure = costing.data?.current?.exposure;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="case-facts">
      {c.code && <CodeChip code={c.code} />}
      {h?.order && <Chip><bdi dir="ltr">{h.order.number}</bdi> · {t(`execution.order.statuses.${h.order.status}`)}</Chip>}
      {latest && <Chip>{t("quotes.latest")}: <bdi dir="ltr">{latest.number}</bdi> · {t(`sourcing.status.quote.${latest.status}`, { defaultValue: latest.status })}</Chip>}
      {h && h.items_total > 0 && <Chip>{t("execution.order.itemsDelivered", { done: f.num(h.items_delivered), total: f.num(h.items_total) })}</Chip>}
      {h && Object.entries(h.cash).map(([cur, v]) => {
        const fig = cashFigure(v);
        if (fig.kind === "advance" && Number(fig.amount) === 0) return null;
        return <Chip key={cur}>{t(`execution.cash.${fig.kind}`)}: <span className="tabular-nums">{f.compactMoney(fig.amount, cur).text}</span></Chip>;
      })}
      {c.exposure_estimate && <Chip>{t("sourcing.decision.exposure")}: <span className="tabular-nums">{f.compactMoney(c.exposure_estimate, c.exposure_currency).text}</span></Chip>}
      {exposure !== undefined && exposure !== null && <span data-testid="computed-exposure"><Chip>{t("costing.computedExposure")}: <span className="tabular-nums">{f.compactMoney(exposure, costing.data!.current!.currency).text}</span></Chip></span>}
      {h && h.warnings > 0 && <Status tone="danger">{t("execution.header.warnings", { count: h.warnings, n: f.num(h.warnings) })}</Status>}
      {children}
      {c.inquiry_id && <Link to={`/sourcing/inquiries/${c.inquiry_id}`} className="text-xs text-accent hover:underline">{t("sourcing.case.fromInquiry")}</Link>}
    </div>
  );
}

/** «قدم بعدی»: the earliest open required step (or task) with its reason, due date and primary action; a step that
 * needs documents has a file drop that files them to it. With nothing open, the next stage of the deal path. */
export function NextStepCard({ c }: { c: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const ov = useCaseOverview(c.id);
  const ex = useExecution(c.id);
  const done = () => { void qc.invalidateQueries({ queryKey: ["case-overview", c.id] }); void qc.invalidateQueries({ queryKey: ["execution", c.id] }); void qc.invalidateQueries({ queryKey: ["case", c.id] }); };
  const finishStep = useMutation({ mutationFn: (body: Record<string, unknown>) => api(`/api/process-steps/${(ov.data?.next_step as { id: string }).id}`, { method: "PATCH", body }), onSuccess: done });
  const finishTask = useMutation({ mutationFn: (id: string) => api(`/api/tasks/${id}/done`, { method: "POST", body: {} }), onSuccess: done });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const data = new FormData();
      data.append("file", file);
      let id: string;
      try { id = (await api<DocumentDetail>("/api/documents", { method: "POST", form: data })).id; }
      catch (err) { if (err instanceof ApiError && err.code === "duplicate_document") id = String(err.details.id); else throw err; }
      return api(`/api/process-steps/${(ov.data?.next_step as { id: string }).id}`, { method: "PATCH", body: { document_id: id, status: "done" } });
    },
    onSuccess: done,
  });
  const step = ov.data?.next_step;
  if (!ov.data) return null;
  let body: ReactNode;
  if (!step) {
    const statuses = c.items.map((i) => i.status);
    const next = pathSteps(statuses, c.status, (ex.data?.shipments.length ?? 0) > 0).find((s) => s.state !== "done");
    body = (
      <div className="flex flex-col gap-2">
        <h2 className="font-display text-2xl font-semibold text-title">{next ? t(`case.path.${next.key}`) : t("case.next.allDone")}</h2>
        <p className="text-sm text-fg-2">{next ? t("case.next.stageHint") : t("case.next.allDoneHint")}</p>
      </div>
    );
  } else if (step.kind === "task") {
    body = (
      <div className="flex flex-col gap-2.5">
        <h2 className="font-display text-2xl font-semibold text-title"><bdi>{step.title}</bdi></h2>
        <p className="text-sm text-fg-2">{t("case.next.taskReason")} · <span className="tabular-nums">{f.day(step.due_on)}</span></p>
        <div><Button variant="primary" icon="check" busy={finishTask.isPending} onClick={() => finishTask.mutate(step.id)} data-testid="next-step-do">{t("tasks.done")}</Button></div>
      </div>
    );
  } else {
    const label = f.lang === "fa" ? step.label_fa : step.label_en;
    body = (
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-center">
        <div className="flex min-w-0 flex-col gap-2.5">
          <h2 className="font-display text-2xl font-semibold text-title" data-testid="next-step-title">{label}</h2>
          <p className="text-sm text-fg-2" data-testid="next-step-reason">
            {[step.group ? t(`execution.process.groups.${step.group}`, { defaultValue: step.group }) : null,
              step.requires_document ? t("case.next.needsDocument") : null,
              step.reference_label ? t("case.next.needsReference", { label: step.reference_label }) : null].filter(Boolean).join(" · ")}
            {step.due_on && <> · <span className={`tabular-nums ${step.due_on < new Date().toISOString().slice(0, 10) ? "text-danger" : ""}`}>{t("case.next.due", { date: f.day(step.due_on) })}</span></>}
          </p>
          <div className="flex flex-wrap gap-2">
            {!step.requires_document && <Button variant="primary" icon="check" busy={finishStep.isPending} onClick={() => finishStep.mutate({ status: "done" })} data-testid="next-step-do">{t("case.next.markDone")}</Button>}
            <Link to={`?tab=logistics`} className={buttonClass(step.requires_document ? "secondary" : "ghost", "md")}>{t("case.next.openChecklist")}</Link>
          </div>
          <ErrorNote error={finishStep.error ?? upload.error} />
        </div>
        {step.requires_document && <FileDrop multiple={false} busy={upload.isPending} testId="next-step-drop" label={t("case.next.dropLabel")} hint={t("case.next.dropHint")}
          onFiles={(files) => files[0] && upload.mutate(files[0])} />}
      </div>
    );
  }
  return (
    <section className="rounded-3xl border border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to p-6" data-testid="next-step" data-kind={step?.kind ?? "stage"}>
      <span className="mb-2 block text-xs tracking-wide text-accent">{t("case.next.eyebrow")}</span>
      {body}
    </section>
  );
}

/** The bottom trio: the people of this deal, its documents (missing required ones in warning) and its money. */
export function CaseTrio({ c }: { c: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ov = useCaseOverview(c.id);
  const o = ov.data;
  if (!o) return null;
  const initials = (s: string) => s.replace(/[«»()]/g, "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("");
  const cur = Object.entries(o.money.actual);
  return (
    <div className="grid gap-4 lg:grid-cols-3" data-testid="case-trio">
      <Card title={t("case.trio.people")} testId="case-people">
        {o.people.length === 0 ? <EmptyState compact icon="users" action={<Link to="?tab=offers" className={buttonClass("secondary", "sm")}>{t("case.trio.addParty")}</Link>}>{t("case.trio.noPeople")}</EmptyState> : (
          <ul className="flex flex-col gap-2.5">{o.people.slice(0, 6).map((p) => (
            <li key={`${p.id}-${p.role}`} className="flex items-center gap-2.5 text-sm">
              <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-surface-2 text-xs text-fg-2">{initials(name(p, f.lang))}</span>
              <span className="flex min-w-0 flex-1 flex-col">
                <Link to={`/parties/${p.id}`} className="truncate hover:text-accent"><bdi>{name(p, f.lang)}</bdi></Link>
                <span className="truncate text-xs text-muted">{t(`case.trio.roles.${p.role}`)}{p.contacts[0] ? <> · <bdi>{name(p.contacts[0], f.lang)}</bdi>{p.contacts[0].job_title && <> (<bdi>{p.contacts[0].job_title}</bdi>)</>}</> : null}</span>
              </span>
            </li>))}</ul>
        )}
      </Card>
      <Card title={t("case.trio.documents")} testId="case-documents" subtitle={t("case.trio.docCount", { count: o.documents.count, n: f.num(o.documents.count) })}>
        <div className="flex flex-col gap-3">
          {o.documents.files.length > 0 && <div className="flex flex-wrap gap-1.5">{o.documents.files.slice(0, 5).map((d) => (
            <Link key={d.id} to={`/documents/${d.id}`} title={d.title} className="rounded-lg border border-line px-2 py-1 hover:border-accent-line"><FileType mime={d.mime_type} name={d.original_filename} /></Link>))}</div>}
          {o.documents.shipping.length > 0 && <p className="text-xs text-fg-2">{o.documents.shipping.map((s) => `${t(`execution.shipments.documents.${s.kind}`, { defaultValue: s.kind })} ${f.num(s.n)}`).join(" · ")}</p>}
          {o.documents.missing.length > 0 ? (
            <ul className="flex flex-col gap-1" data-testid="case-missing-docs">{o.documents.missing.slice(0, 4).map((m) => (
              <li key={m.id} className="flex items-center gap-1.5 text-xs text-warning"><Icon name="alert" size={12} />{f.lang === "fa" ? m.label_fa : m.label_en}</li>))}
              {o.documents.missing.length > 4 && <li className="text-xs text-muted">{t("case.trio.moreMissing", { n: f.num(o.documents.missing.length - 4) })}</li>}</ul>
          ) : o.documents.count === 0 ? <EmptyState compact icon="file">{t("case.trio.noDocuments")}</EmptyState> : null}
        </div>
      </Card>
      <Card title={t("case.trio.money")} testId="case-money">
        {cur.length === 0 && !o.money.expected_profit ? <EmptyState compact icon="coins">{t("execution.cash.none")}</EmptyState> : (
          <div className="flex flex-col gap-2.5 text-sm">
            {cur.map(([currency, v]) => {
              const total = Number(v.received) + Number(v.paid) || 1;
              return (
                <div key={currency} className="flex flex-col gap-1" data-currency={currency}>
                  <div className="flex h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                    <span className="bg-success" style={{ width: `${(Number(v.received) / total) * 100}%` }} />
                    <span className="bg-danger" style={{ width: `${(Number(v.paid) / total) * 100}%` }} />
                  </div>
                  <span className="flex flex-wrap justify-between gap-x-3 text-xs text-fg-2">
                    <span>{t("case.trio.received")}: <span className="tabular-nums">{f.compactMoney(v.received, currency).text}</span></span>
                    <span>{t("case.trio.paid")}: <span className="tabular-nums">{f.compactMoney(v.paid, currency).text}</span></span>
                  </span>
                </div>
              );
            })}
            {o.money.expected_profit?.profit && (
              <p className="flex items-center gap-2 text-sm" data-testid="case-expected-profit">
                {t("finance.profit.expected")}: <span className="tabular-nums text-title" title={f.compactMoney(o.money.expected_profit.profit, o.money.expected_profit.currency).full}>
                  {f.compactMoney(o.money.expected_profit.profit, o.money.expected_profit.currency).text}</span>
                {o.money.expected_profit.estimated && <Status tone="warning">{t("finance.profit.estimated")}</Status>}
              </p>)}
          </div>
        )}
      </Card>
    </div>
  );
}

/** The deal story rail: events with their sentences (1.1), dated and linked; «اکنون»; the dated milestones still
 * ahead muted as «پیش‌بینی». */
export function DealStoryRail({ c }: { c: CaseDetail }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ov = useCaseOverview(c.id);
  const history = useQuery({ queryKey: ["events", "case", c.id, "rail"],
    queryFn: () => api<Page<EventItem>>("/api/events", { query: { entity_type: "case", entity_id: c.id, page_size: 12 } }) });
  const events = [...(history.data?.items ?? [])].reverse();
  const ahead = ov.data?.forecast ?? [];
  const forecastText = (x: CaseOverviewData["forecast"][number]) => {
    if (x.kind === "eta") return t("case.story.eta", { ref: x.ref ?? "" });
    if (x.kind === "step") return f.lang === "fa" ? x.label_fa : x.label_en;
    if (x.kind === "invoice_due") return t("case.story.invoiceDue", { ref: x.ref ?? "" });
    return t(`case.story.payment.${x.direction}`, { amount: f.compactMoney(x.amount ?? "0", x.currency).text });
  };
  return (
    <section className="flex flex-col gap-4 rounded-3xl border border-line bg-surface p-5" aria-label={t("case.side.story")} data-testid="case-story">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-accent">{t("case.side.story")}</h2>
        <Link to="?tab=history" className="text-xs text-accent hover:underline">{t("case.side.all")}</Link>
      </div>
      {events.length === 0 && ahead.length === 0 ? <EmptyState compact icon="clock">{t("case.side.noHistory")}</EmptyState> : (
        <ol className="relative flex flex-col gap-4 border-s border-line ps-5">
          {events.map((e) => (
            <li key={e.id} className="relative flex flex-col gap-0.5 text-sm">
              <span aria-hidden className="absolute -start-6.5 top-1.5 size-2.5 rounded-full bg-accent" />
              <span className="text-xs text-muted tabular-nums">{f.date(e.occurred_at)}</span>
              <EventSentence event={e} caseId={c.id} />
            </li>))}
          <li className="relative flex items-center gap-2 text-sm font-semibold text-accent" data-testid="case-story-now">
            <span aria-hidden className="absolute -start-7 top-0.5 size-4 rounded-full border-2 border-accent bg-surface" />{t("cc.line.now")}
          </li>
          {ahead.slice(0, 6).map((x, i) => (
            <li key={`${x.kind}-${i}`} className="relative flex flex-col gap-0.5 text-sm text-muted" data-forecast={x.kind}>
              <span aria-hidden className="absolute -start-6.5 top-1.5 size-2.5 rounded-full border border-line-strong bg-surface" />
              <span className="text-xs tabular-nums">{t("case.story.forecast")} · {f.day(x.on)}</span>
              <span><bdi>{forecastText(x)}</bdi></span>
            </li>))}
        </ol>
      )}
    </section>
  );
}
