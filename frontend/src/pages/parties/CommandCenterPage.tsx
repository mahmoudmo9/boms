import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Button, Card, EmptyState, ErrorNote, Loading, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { CommandCenter, FollowupRow } from "../../lib/types";
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
