import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Bdi, Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "../../design/components";
import { TimeLeftBadge } from "../../components/TimeLeft";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { CommandCenter, ExecutionSummary, FollowupRow, SetadSummary, SourcingSummary, TendersSummary } from "../../lib/types";
import { useQuickLog } from "./QuickLog";
import { FollowupActions, PartyName, stageLabel } from "./shared";
import { TaskList } from "../tasks/TaskList";
import { TodayTop } from "./Today";

const FUNNELS = ["buyer", "supplier"] as const;

function FollowupList({ rows, tone }: { rows: FollowupRow[]; tone?: "danger" }) {
  const { t } = useTranslation();
  const f = useFormat();
  if (rows.length === 0) return <EmptyState>{t("cc.nothing")}</EmptyState>;
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => (
        <li key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
          <span className={`w-24 shrink-0 tabular-nums ${tone === "danger" ? "font-medium text-danger" : "text-muted"}`}>{f.day(row.due_on)}</span>
          <PartyName fa={row.party_name_fa} en={row.party_name_en} dnc={row.do_not_contact} id={row.party_id} className="max-w-56" />
          {row.party_status === "archived" && <Badge>{t("parties.archived")}</Badge>}
          <span className="min-w-0 flex-1 truncate" dir="auto">{row.action}</span>
          <FollowupActions
            followup={row}
            extra={
              <Link to={`/parties/${row.party_id}`} className="inline-flex h-8 items-center rounded-md px-2 text-sm text-accent hover:bg-surface-2">
                {t("cc.openParty")}
              </Link>
            }
          />
        </li>
      ))}
    </ul>
  );
}

/** Phase 5: items without RFQ, overdue RFQ replies, offers expiring soon, cases not covered, coverage %. */
function SourcingSection({ s }: { s: SourcingSummary }) {
  const { t } = useTranslation();
  const f = useFormat();
  const list = (rows: { key: string; to: string; label: ReactNode; extra?: ReactNode }[]) => rows.length === 0 ? <EmptyState>{t("cc.nothing")}</EmptyState> : (
    <ul className="divide-y divide-line">{rows.map((r) => (
      <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        <Link to={r.to} className="min-w-0 truncate text-accent hover:underline">{r.label}</Link>{r.extra}
      </li>
    ))}</ul>
  );
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium text-title">{t("cc.sourcing.title")}</h2>
        <span className="rounded-md border border-line px-3 py-1 text-sm">
          {t("cc.sourcing.coverage")}: <b className="tabular-nums">{s.coverage_status_percent === null ? "—" : `${f.num(s.coverage_status_percent, 1)}%`}</b>
          <span className="ms-1 text-xs text-muted tabular-nums">({f.num(s.open_items_with_status)}/{f.num(s.open_items)})</span>
        </span>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sourcing.noRfq")} <Badge tone={s.items_without_rfq.length ? "warning" : "neutral"}>{f.num(s.items_without_rfq.length)}</Badge></span>}>
          {list(s.items_without_rfq.map((i) => ({ key: i.item_id, to: `/cases/${i.case_id}?tab=items&item=${i.item_id}`, label: <Bdi>{i.name}</Bdi>,
            extra: <span className="text-xs text-muted"><Bdi>{i.case_title}</Bdi></span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sourcing.noResponseResend")} <Badge tone={s.no_response_resend.length ? "warning" : "neutral"}>{f.num(s.no_response_resend.length)}</Badge></span>}>
          {list(s.no_response_resend.map((i) => ({ key: i.item_id, to: `/cases/${i.case_id}?tab=rfqs`, label: <Bdi>{i.name}</Bdi>,
            extra: <span className="text-xs text-muted"><Bdi>{i.case_title}</Bdi> · {t("cc.sourcing.resendHint")}</span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sourcing.rfqOverdue")} <Badge tone={s.rfq_overdue.length ? "danger" : "neutral"}>{f.num(s.rfq_overdue.length)}</Badge></span>}>
          {list(s.rfq_overdue.map((r) => ({ key: r.recipient_id, to: `/cases/${r.case_id}?tab=rfqs&rfq=${r.rfq_id}`,
            label: <Bdi>{(f.lang === "fa" ? r.party_name_fa || r.party_name_en : r.party_name_en || r.party_name_fa) ?? ""}</Bdi>,
            extra: <span className="text-xs text-muted"><Bdi>{r.rfq_title}</Bdi> · <span className="tabular-nums">{f.day(r.respond_by)}</span></span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sourcing.expiring")} <Badge tone={s.offers_expiring.length ? "warning" : "neutral"}>{f.num(s.offers_expiring.length)}</Badge></span>}>
          {list(s.offers_expiring.map((o) => ({ key: o.offer_id, to: `/cases/${o.case_id}?tab=offers&offer=${o.offer_id}`,
            label: <Bdi>{(f.lang === "fa" ? o.party_name_fa || o.party_name_en : o.party_name_en || o.party_name_fa) ?? ""}</Bdi>,
            extra: <span className="text-xs text-danger">{t("sourcing.compare.daysLeft", { n: f.num(o.days_left) })}</span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sourcing.selectionLost")} <Badge tone={s.selection_lost.length ? "danger" : "neutral"}>{f.num(s.selection_lost.length)}</Badge></span>}>
          {list(s.selection_lost.map((i) => ({ key: i.item_id, to: `/cases/${i.case_id}?tab=items&item=${i.item_id}`, label: <Bdi>{i.name}</Bdi>,
            extra: <span className="text-xs text-muted"><Bdi>{i.case_title}</Bdi> · {t(`sourcing.lostCause.${i.cause}`, { defaultValue: i.cause })}</span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sourcing.notCovered")} <Badge tone={s.cases_not_covered.length ? "warning" : "neutral"}>{f.num(s.cases_not_covered.length)}</Badge></span>}>
          {list(s.cases_not_covered.map((c) => ({ key: c.case_id, to: `/cases/${c.case_id}`, label: <Bdi>{c.case_title}</Bdi>,
            extra: <span className="text-xs text-muted">{t("cc.sourcing.itemsMissing", { n: f.num(c.not_covered), total: f.num(c.items) })}</span> })))}
        </Card>
      </div>
      {s.quotes_awaiting_approval !== undefined && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-medium text-title">{t("cc.sales.title")}</h2>
            <span className="rounded-md border border-line px-3 py-1 text-sm" data-testid="won-lost">
              {t("cc.sales.won30")}: <b className="tabular-nums text-success">{f.num(s.quotes_won_30_days ?? 0)}</b>
              <span className="mx-2 text-muted">·</span>
              {t("cc.sales.lost30")}: <b className="tabular-nums text-danger">{f.num(s.quotes_lost_30_days ?? 0)}</b>
            </span>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sales.awaitingApproval")} <Badge tone={s.quotes_awaiting_approval.length ? "warning" : "neutral"}>{f.num(s.quotes_awaiting_approval.length)}</Badge></span>}>
              {list(s.quotes_awaiting_approval.map((q) => ({ key: q.quote_id, to: `/cases/${q.case_id}?tab=quotes&quote=${q.quote_id}`, label: <bdi dir="ltr">{q.number}</bdi>,
                extra: <span className="text-xs text-muted"><Bdi>{q.case_title}</Bdi></span> })))}
            </Card>
            <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sales.expiring")} <Badge tone={s.quotes_expiring?.length ? "warning" : "neutral"}>{f.num(s.quotes_expiring?.length ?? 0)}</Badge></span>}>
              {list((s.quotes_expiring ?? []).map((q) => ({ key: q.quote_id, to: `/cases/${q.case_id}?tab=quotes&quote=${q.quote_id}`, label: <bdi dir="ltr">{q.number}</bdi>,
                extra: <span className="text-xs text-muted"><Bdi>{(f.lang === "fa" ? q.party_name_fa || q.party_name_en : q.party_name_en || q.party_name_fa) ?? q.case_title}</Bdi> · <span className="text-danger">{q.days_left < 0 ? t("cc.sales.passed") : t("sourcing.compare.daysLeft", { n: f.num(q.days_left) })}</span></span> })))}
            </Card>
            <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.sales.staleFx")} <Badge tone={s.sheets_stale_fx?.length ? "warning" : "neutral"}>{f.num(s.sheets_stale_fx?.length ?? 0)}</Badge></span>}>
              {list((s.sheets_stale_fx ?? []).map((r) => ({ key: r.cost_sheet_id, to: `/cases/${r.case_id}?tab=costing&sheet=${r.cost_sheet_id}`,
                label: <span><Bdi>{r.case_title}</Bdi> · {t("costing.version", { version: f.num(r.version) })}</span>,
                extra: <span className="text-xs text-muted">{t("cc.sales.fxAge", { n: f.num(r.age_days) })}</span> })))}
            </Card>
          </div>
        </>
      )}
    </section>
  );
}

/** v0.5.0: starred / reviewing listings due within 3 days or passed, converted listings whose deadline changed,
 * new listings matching warn keywords, and the last fetch per source. */
function SetadSection({ s }: { s: SetadSummary }) {
  const { t } = useTranslation();
  const f = useFormat();
  const listingLink = (r: { id: string; source: string }) => `/tenders?source=${r.source}&include_old=1&listing=${r.id}`;
  const list = (rows: { key: string; to: string; label: ReactNode; extra?: ReactNode }[]) => rows.length === 0 ? <EmptyState>{t("cc.nothing")}</EmptyState> : (
    <ul className="divide-y divide-line">{rows.map((r) => (
      <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        <Link to={r.to} className="min-w-0 truncate text-accent hover:underline" dir="auto">{r.label}</Link>{r.extra}
      </li>
    ))}</ul>
  );
  return (
    <section className="flex flex-col gap-3" data-testid="cc-setad">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium text-title">{t("cc.setad.title")}</h2>
        {s.runs.map((r) => (
          <span key={r.source} className={`text-xs ${r.stale ? "text-warning" : "text-muted"}`}>
            {t(`listings.sources.${r.source}`)}: {r.at ? <span className="tabular-nums">{f.date(r.at, true)}</span> : t("setad.noRun")}
            {r.status && ` · ${t(`setad.runStatus.${r.status}`)}`}
            {r.stale && ` · ${t("cc.setad.stale", { days: f.num(s.stale_days) })}`}
            {r.errors && <span className="text-danger" dir="auto"> · {r.errors.split("\n")[0]}</span>}
          </span>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.setad.due")} <Badge tone={s.due.length ? "warning" : "neutral"}>{f.num(s.due.length)}</Badge></span>}>
          {list(s.due.map((r) => ({ key: r.id, to: r.inquiry_id ? `/sourcing/inquiries/${r.inquiry_id}` : listingLink(r), label: r.title,
            extra: <span className="flex items-center gap-1.5 text-xs tabular-nums"><span className="text-muted">{f.date(r.deadline, true)}</span><TimeLeftBadge at={r.deadline} /></span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.setad.deadlineChanged")} <Badge tone={s.deadline_changed.length ? "danger" : "neutral"}>{f.num(s.deadline_changed.length)}</Badge></span>}>
          {list(s.deadline_changed.map((r) => ({ key: r.listing_id, to: `/sourcing/inquiries/${r.inquiry_id}`, label: r.title,
            extra: <span className="text-xs tabular-nums text-muted">{r.old ? f.date(r.old, true) : "—"} → {f.date(r.new, true)}</span> })))}
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.setad.warn")} <Badge tone={s.warn_new.length ? "warning" : "neutral"}>{f.num(s.warn_new.length)}</Badge></span>}>
          {list(s.warn_new.map((r) => ({ key: r.id, to: listingLink(r), label: r.title,
            extra: <span className="text-xs text-warning" dir="auto">{r.keywords.join("، ")}</span> })))}
        </Card>
      </div>
    </section>
  );
}

/** v0.6.0: tender dates within 3 days, envelopes incomplete close to the deadline, guarantees expiring or awaiting
 * release, company documents expiring, Setad changes not applied, submitted tenders waiting for a result. */
function TendersSection({ s }: { s: TendersSummary }) {
  const { t } = useTranslation();
  const f = useFormat();
  const list = (rows: { key: string; to: string; label: ReactNode; extra?: ReactNode }[]) => rows.length === 0 ? <EmptyState>{t("cc.nothing")}</EmptyState> : (
    <ul className="divide-y divide-line">{rows.map((r) => (
      <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        <Link to={r.to} className="min-w-0 truncate text-accent hover:underline" dir="auto">{r.label}</Link>{r.extra}
      </li>
    ))}</ul>
  );
  const tab = (caseId: string) => `/cases/${caseId}?tab=tender`;
  const card = (key: string, n: number, tone: "warning" | "danger", body: ReactNode) => (
    <Card padded={false} title={<span className="flex items-center gap-2">{t(`cc.tenders.${key}`)} <Badge tone={n ? tone : "neutral"}>{f.num(n)}</Badge></span>}>{body}</Card>
  );
  return (
    <section className="flex flex-col gap-3" data-testid="cc-tenders">
      <h2 className="text-lg font-medium text-title">{t("cc.tenders.title")}</h2>
      <div className="grid gap-4 xl:grid-cols-3">
        {card("datesSoon", s.dates_soon.length, "warning", list(s.dates_soon.map((r) => ({ key: `${r.tender_id}-${r.kind}-${r.at}`, to: tab(r.case_id), label: r.case_title,
          extra: <span className="flex items-center gap-1.5 text-xs"><span>{t(`tenders.dateKinds.${r.kind}`)}</span><TimeLeftBadge at={r.at} /></span> }))))}
        {card("envelopes", s.envelopes_incomplete.length, "danger", list(s.envelopes_incomplete.map((r) => ({ key: r.tender_id, to: tab(r.case_id), label: r.case_title,
          extra: <span className="text-xs text-danger">{t("tenders.envelopes.progress", { done: f.num(r.done), total: f.num(r.total) })}</span> }))))}
        {card("guarantees", s.guarantees_expiring.length + s.guarantees_release.length, "warning", list([
          ...s.guarantees_expiring.map((r) => ({ key: `e${r.guarantee_id}`, to: tab(r.case_id), label: r.case_title,
            extra: <span className="text-xs text-warning">{t(`tenders.guarantee.purposes.${r.purpose}`)} · {r.valid_until ? f.day(r.valid_until) : "—"}</span> })),
          ...s.guarantees_release.map((r) => ({ key: `r${r.guarantee_id}`, to: tab(r.case_id), label: r.case_title,
            extra: <span className="text-xs text-warning">{t("cc.tenders.awaitingRelease")}</span> }))]))}
        {card("documents", s.documents_expiring.length, "warning", list(s.documents_expiring.map((d) => ({ key: d.id, to: `/settings/company-documents?doc=${d.id}`, label: d.title,
          extra: <span className={`text-xs ${d.expiry === "expired" ? "text-danger" : "text-warning"}`}>{t(`tenders.library.expiry.${d.expiry}`)}{d.expires_on ? ` · ${f.day(d.expires_on)}` : ""}</span> }))))}
        {card("setad", s.setad_changes.length, "danger", list(s.setad_changes.map((r) => ({ key: r.tender_id, to: tab(r.case_id), label: r.case_title,
          extra: <span className="text-xs text-danger">{r.date_changes ? t("cc.tenders.dateChanges", { n: f.num(r.date_changes) }) : ""} {Object.keys(r.new_appendices).length ? t("cc.tenders.newAddenda") : ""}</span> }))))}
        {card("waiting", s.waiting_result.length, "warning", list(s.waiting_result.map((r) => ({ key: r.tender_id, to: tab(r.case_id), label: r.case_title,
          extra: <span className="text-xs text-muted">{t("tenders.dateKinds.opening")} {f.date(r.opening, true)}</span> }))))}
      </div>
    </section>
  );
}

/** v0.7.0 «اجرا»: POs sent but not confirmed, supplier ready dates passed, shipments delayed, process steps due,
 * payments past due (in and out), open claims, sales orders with delivery due within 7 days or overdue. */
export function ExecutionSection({ s }: { s: ExecutionSummary }) {
  const { t } = useTranslation();
  const f = useFormat();
  const list = (rows: { key: string; to: string; label: ReactNode; extra?: ReactNode }[]) => rows.length === 0 ? <EmptyState>{t("cc.nothing")}</EmptyState> : (
    <ul className="divide-y divide-line">{rows.map((r) => (
      <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        <Link to={r.to} className="min-w-0 truncate text-accent hover:underline" dir="auto">{r.label}</Link>{r.extra}
      </li>
    ))}</ul>
  );
  const card = (key: string, n: number, tone: "warning" | "danger", body: ReactNode) => (
    <Card padded={false} title={<span className="flex items-center gap-2">{t(`cc.execution.${key}`)} <Badge tone={n ? tone : "neutral"}>{f.num(n)}</Badge></span>}>{body}</Card>
  );
  const to = (caseId: string, tab: string) => `/cases/${caseId}?tab=${tab}`;
  return (
    <section className="flex flex-col gap-3" data-testid="cc-execution">
      <h2 className="text-lg font-medium text-title">{t("cc.execution.title")}</h2>
      <div className="grid gap-4 xl:grid-cols-3">
        {card("unconfirmed", s.pos_unconfirmed.length, "warning", list(s.pos_unconfirmed.map((r) => ({ key: r.purchase_order_id, to: to(r.case_id, "purchase"), label: r.case_title,
          extra: <span className="text-xs text-warning"><bdi dir="ltr">{r.number}</bdi> · {t("cc.execution.daysAgo", { n: f.num(r.days) })}</span> }))))}
        {card("readyPassed", s.ready_passed.length, "danger", list(s.ready_passed.map((r) => ({ key: r.purchase_order_id ?? r.number ?? "", to: to(r.case_id, "purchase"), label: r.case_title ?? "",
          extra: <span className="text-xs text-danger"><bdi dir="ltr">{r.number}</bdi> · {r.ready_due_on ? f.day(r.ready_due_on) : ""}</span> }))))}
        {card("shipments", s.shipments_delayed.length, "danger", list(s.shipments_delayed.map((r) => ({ key: `${r.shipment_id}-${r.kind}`, to: to(r.case_id, "logistics"), label: r.case_title ?? "",
          extra: <span className="text-xs text-danger">{t(`execution.warnings.${r.kind}`, { days: f.num(r.days) })}</span> }))))}
        {card("steps", s.steps_due.length, "warning", list(s.steps_due.map((r) => ({ key: r.step_id, to: to(r.case_id, "logistics"), label: r.case_title,
          extra: <span className={`text-xs ${r.overdue ? "text-danger" : "text-warning"}`} dir="auto">{f.lang === "fa" ? r.label_fa : r.label_en} · {f.day(r.due_on)}</span> }))))}
        {card("payments", s.payments_overdue.length, "danger", list(s.payments_overdue.map((r) => ({ key: r.milestone_id, to: to(r.case_id, r.direction === "in" ? "order" : "purchase"), label: r.case_title,
          extra: <span className="text-xs text-danger">{t(`cc.execution.direction.${r.direction}`)} · {f.num(r.amount)} {r.currency} · {f.day(r.due_on)}</span> }))))}
        {card("claims", s.claims_open.length, "warning", list(s.claims_open.map((r) => ({ key: r.claim_id, to: to(r.case_id, "delivery"), label: r.case_title,
          extra: <span className="text-xs text-warning">{t(`execution.claims.kinds.${r.kind}`)} · {t(`execution.claims.statuses.${r.status}`)}</span> }))))}
        {card("deliveries", s.deliveries_due.length, "warning", list(s.deliveries_due.map((r) => ({ key: r.sales_order_id, to: to(r.case_id, "delivery"), label: r.case_title,
          extra: <span className={`text-xs ${r.overdue ? "text-danger" : "text-warning"}`}><bdi dir="ltr">{r.number}</bdi> · {f.day(r.delivery_due_on)}</span> }))))}
      </div>
    </section>
  );
}

/** v0.8.0: «کارها», the owner's internal tasks overdue and due today or tomorrow (not follow-ups with a party). */
function TasksSection({ s }: { s: NonNullable<CommandCenter["tasks"]> }) {
  const { t } = useTranslation();
  const f = useFormat();
  const card = (key: "overdue" | "today" | "tomorrow") => (
    <Card key={key} padded={false} className={key === "overdue" && s.overdue.length ? "border-danger" : ""}
      title={<span className="flex items-center gap-2">{t(`cc.tasks.${key}`)} <Badge tone={key === "overdue" && s[key].length ? "danger" : key === "today" ? "accent" : "neutral"}>{f.num(s[key].length)}</Badge></span>}>
      <div className="max-h-72 overflow-y-auto"><TaskList rows={s[key]} tone={key === "overdue" ? "danger" : undefined} /></div>
    </Card>
  );
  return (
    <section className="flex flex-col gap-3" data-testid="cc-tasks">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium text-title">{t("cc.tasks.title")}</h2>
        <Link to="/tasks" className="text-sm text-accent hover:underline">{t("cc.tasks.all")}</Link>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">{card("overdue")}{card("today")}{card("tomorrow")}</div>
    </section>
  );
}

/** v0.8.0: «مالی» — receivables overdue, payables due, delivered not invoiced, received without a supplier invoice,
 * Moadian pending, payments without an FX rate, cases ready to close. */
function FinanceSection({ s }: { s: NonNullable<CommandCenter["finance"]> }) {
  const { t } = useTranslation();
  const f = useFormat();
  const card = (key: keyof typeof s, rows: { key: string; to: string; label: ReactNode; extra?: ReactNode }[], tone: "danger" | "warning" | "accent" = "warning") => (
    <Card key={key} padded={false} title={<span className="flex items-center gap-2">{t(`cc.finance.${key}`)} <Badge tone={rows.length ? tone : "neutral"}>{f.num(rows.length)}</Badge></span>}>
      {rows.length === 0 ? <EmptyState>{t("cc.nothing")}</EmptyState> : (
        <ul className="max-h-64 divide-y divide-line overflow-y-auto">{rows.map((r) => (
          <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
            <Link to={r.to} className="min-w-0 truncate text-accent hover:underline">{r.label}</Link>{r.extra}</li>))}</ul>)}
    </Card>
  );
  const to = (caseId: string) => `/cases/${caseId}?tab=finance`;
  return (
    <section className="flex flex-col gap-3" data-testid="cc-finance">
      <div className="flex flex-wrap items-center gap-3"><h2 className="text-lg font-medium text-title">{t("cc.finance.title")}</h2>
        <Link to="/finance" className="text-sm text-accent hover:underline">{t("cc.finance.open")}</Link></div>
      <div className="grid gap-4 xl:grid-cols-2">
        {card("receivables_overdue", s.receivables_overdue.map((r) => ({ key: r.invoice_id, to: to(r.case_id), label: <bdi dir="ltr">{r.number}</bdi>,
          extra: <span className="text-xs text-danger">{f.num(r.balance)} {r.currency} · {t("cc.finance.daysPast", { n: f.num(r.days_past_due) })}</span> })), "danger")}
        {card("payables_due", s.payables_due.map((r) => ({ key: r.id, to: to(r.case_id), label: <Bdi>{r.label}</Bdi>,
          extra: <span className="text-xs text-warning">{f.num(r.balance)} {r.currency}{r.due_date ? ` · ${f.day(r.due_date)}` : ""}</span> })))}
        {card("delivered_not_invoiced", s.delivered_not_invoiced.map((r) => ({ key: r.sales_order_id, to: to(r.case_id), label: <bdi dir="ltr">{r.number}</bdi>,
          extra: <span className="text-xs text-muted"><Bdi>{r.case_title ?? ""}</Bdi> · {f.num(r.quantity)}</span> })))}
        {card("received_not_invoiced", s.received_not_invoiced.map((r) => ({ key: r.purchase_order_id, to: to(r.case_id), label: <bdi dir="ltr">{r.number}</bdi>,
          extra: <span className="text-xs text-muted"><Bdi>{r.case_title ?? ""}</Bdi></span> })))}
        {card("moadian_pending", s.moadian_pending.map((r) => ({ key: r.invoice_id, to: to(r.case_id), label: <bdi dir="ltr">{r.number}</bdi>,
          extra: <span className="text-xs text-warning">{t(`finance.moadian.statuses.${r.moadian_status}`)}</span> })))}
        {card("payments_without_rate", s.payments_without_rate.map((r) => ({ key: r.record_id, to: to(r.case_id), label: <span>{f.num(r.amount)} {r.currency}</span>,
          extra: <span className="text-xs text-muted">{f.day(r.paid_on)} · <Bdi>{r.case_title ?? ""}</Bdi></span> })), "danger")}
        {card("ready_to_close", s.ready_to_close.map((r) => ({ key: r.case_id, to: to(r.case_id), label: <Bdi>{r.case_title ?? ""}</Bdi> })), "accent")}
      </div>
    </section>
  );
}

export function CommandCenterPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const quickLog = useQuickLog();
  const cc = useQuery({
    queryKey: ["command-center"],
    queryFn: () => api<CommandCenter>("/api/command-center", { background: true }),
    refetchInterval: 60_000,
  });
  if (cc.isLoading) return <Loading rows={8} />;
  if (cc.error || !cc.data) return <ErrorState error={cc.error} onRetry={() => void cc.refetch()} />;
  const d = cc.data;

  return (
    <div className="flex flex-col gap-5" data-testid="command-center">
      <PageHeader
        title={t("nav.commandCenter")}
        subtitle={t("cc.subtitle", { date: f.day(d.today_date) })}
        actions={<Button variant="primary" icon="plus" onClick={() => quickLog.open()}>{t("quicklog.button")}</Button>}
      />
      <TodayTop cc={d} />
      <h2 className="mt-4 font-display text-xl font-semibold text-title">{t("cc.attention")}</h2>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card padded={false} className={d.overdue_count ? "border-danger" : ""}
          title={<span className={`flex items-center gap-2 ${d.overdue_count ? "text-danger" : ""}`}>{t("cc.overdue")} <Badge tone={d.overdue_count ? "danger" : "neutral"}>{f.num(d.overdue_count)}</Badge></span>}>
          <FollowupList rows={d.overdue} tone="danger" />
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.today")} <Badge tone="accent">{f.num(d.today.length)}</Badge></span>}>
          <FollowupList rows={d.today} />
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.upcoming")} <Badge>{f.num(d.upcoming_7_days.length)}</Badge></span>}>
          <FollowupList rows={d.upcoming_7_days} />
        </Card>
        <Card padded={false} title={<span className="flex items-center gap-2">{t("cc.stale", { days: f.num(d.stale_lead_days) })} <Badge tone={d.stale_leads.length ? "warning" : "neutral"}>{f.num(d.stale_leads.length)}</Badge></span>}>
          {d.stale_leads.length === 0 ? (
            <EmptyState>{t("cc.nothing")}</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {d.stale_leads.map((s) => (
                <li key={`${s.party_id}-${s.role}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
                  <PartyName fa={s.party_name_fa} en={s.party_name_en} dnc={s.do_not_contact} id={s.party_id} className="max-w-56" />
                  <Badge>{t(`parties.roles.${s.role}`)} · {stageLabel(t, s.role, s.stage)}</Badge>
                  <span className="text-xs text-muted tabular-nums">
                    {s.last_interaction_at ? t("cc.lastContact", { date: f.date(s.last_interaction_at) }) : t("cc.noContactYet")}
                  </span>
                  <Button variant="ghost" className="ms-auto" icon="plus" onClick={() => quickLog.open(s.party_id)}>{t("quicklog.button")}</Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {d.tasks && <TasksSection s={d.tasks} />}
      <SourcingSection s={d.sourcing} />
      {d.setad && <SetadSection s={d.setad} />}
      {d.tenders && <TendersSection s={d.tenders} />}
      {d.execution && <ExecutionSection s={d.execution} />}
      {d.finance && <FinanceSection s={d.finance} />}
      <div className="grid gap-4 xl:grid-cols-2">
        {FUNNELS.map((role) => (
          <Card key={role} title={t(`funnel.title.${role}`)} actions={<Link className="text-sm text-accent hover:underline" to={`/parties/funnels?role=${role}`}>{t("funnel.openBoard")}</Link>}>
            <div className="flex flex-wrap gap-2">
              {Object.entries(d.funnel_counts[role] ?? {}).map(([stage, n]) => (
                <Link key={stage} to={`/parties?role=${role}&stage=${stage}`}
                  className="flex min-w-24 flex-col rounded-md border border-line px-3 py-2 hover:border-accent">
                  <span className="text-xs text-muted">{stageLabel(t, role, stage)}</span>
                  <span className="text-lg font-semibold tabular-nums">{f.num(n)}</span>
                </Link>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
