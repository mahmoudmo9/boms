import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Bdi } from "../../components/Bdi";
import { Badge, Button, Card, EmptyState, ErrorNote, Loading, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { CommandCenter, FollowupRow, SourcingSummary } from "../../lib/types";
import { useQuickLog } from "./QuickLog";
import { FollowupActions, PartyName, stageLabel } from "./shared";

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
        <h2 className="text-base font-semibold">{t("cc.sourcing.title")}</h2>
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
            <h2 className="text-base font-semibold">{t("cc.sales.title")}</h2>
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

export function CommandCenterPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const quickLog = useQuickLog();
  const cc = useQuery({
    queryKey: ["command-center"],
    queryFn: () => api<CommandCenter>("/api/command-center", { background: true }),
    refetchInterval: 60_000,
  });
  if (cc.isLoading) return <Loading />;
  if (cc.error || !cc.data) return <ErrorNote error={cc.error} />;
  const d = cc.data;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={t("nav.commandCenter")}
        subtitle={t("cc.subtitle", { date: f.day(d.today_date) })}
        actions={<Button variant="primary" icon="plus" onClick={() => quickLog.open()}>{t("quicklog.button")}</Button>}
      />
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
      <SourcingSection s={d.sourcing} />
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
