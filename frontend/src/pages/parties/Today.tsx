/** The top of the command center (v0.10.0, reference ProToday / light Main): the most important thing now with its
 * time left, today's timeline, four figures from data BOMS has (profit of the deals closed this quarter, quote win
 * rate, cash tied up now, today's Setad matches by keyword), the cash flow of the next 90 days and the AI line.
 * The mockup's «بینش‌ها» card is not built (rules and AI insights come in v0.11.0). */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useNow } from "../../components/TimeLeft";
import { Button, buttonClass, Card, Chip, DayLine, EmptyState, Icon, KpiTile, ProgressBar, ProgressRing, Segmented, Status } from "../../design/components";
import { Bars, CashFlow, Sparkline } from "../../design/components/charts";
import { api, type Page } from "../../lib/api";
import { capTone } from "../../lib/ai";
import { useAuth } from "../../lib/auth";
import { useFormat } from "../../lib/prefs";
import { backupHealth, clockLeft, dayLine, focus, lineCounts, mainCurrency, type Moment, moments, type Overview, timeLeftPercent, todayLine } from "../../lib/today";
import type { BackupRun, CommandCenter } from "../../lib/types";
import { useTasksInvalidate } from "../tasks/TaskList";
import { useQuickLog } from "./QuickLog";

/** v0.10.1 (4.1): the header facts beside the title — today's date in the user's calendar, the time and the last
 * backup's health («بکاپ سالم» / «بکاپ قدیمی» / «بکاپ ناموفق»). */
export function CommandHeaderFacts() {
  const { t } = useTranslation();
  const f = useFormat();
  const now = useNow();
  const backups = useQuery({ queryKey: ["system", "backups", "latest"], queryFn: () => api<Page<BackupRun>>("/api/system/backups", { query: { page: 1, page_size: 1 }, background: true }) });
  const last = backups.data?.items[0];
  const health = backupHealth(last, now);
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm text-fg-2" data-testid="cc-header-facts">
      <span>{f.longDate(now)}</span><span aria-hidden>·</span><span className="tabular-nums">{f.time(now)}</span>
      {backups.data && <Link to="/settings/system" data-testid="backup-chip" data-health={health}>
        <Status tone={health === "ok" ? "success" : health === "old" || health === "none" ? "warning" : "danger"}>{t(`cc.backup.${health}`)}</Status></Link>}
    </span>
  );
}

/** The item's own job as the primary action (4.1): a task is done here, a follow-up logged, the others open where
 * the work is done. «باز کردن» stays the secondary action. */
function FocusAction({ item }: { item: Moment }) {
  const { t } = useTranslation();
  const quickLog = useQuickLog();
  const invalidate = useTasksInvalidate();
  const id = item.key.split("-").slice(1).join("-");
  const done = useMutation({ mutationFn: () => api(`/api/tasks/${id}/done`, { method: "POST", body: {} }), onSuccess: invalidate });
  if (item.kind === "task") return <Button variant="primary" icon="check" busy={done.isPending} onClick={() => done.mutate()} data-testid="cc-focus-do">{t("cc.focus.do.task")}</Button>;
  if (item.kind === "followup") return <Button variant="primary" icon="plus" onClick={() => quickLog.open(item.link.split("/").pop())} data-testid="cc-focus-do">{t("cc.focus.do.followup")}</Button>;
  const to = item.kind === "tender" ? `${item.link}&section=proposal` : item.link;
  return <Link to={to} className={buttonClass("primary", "md")} data-testid="cc-focus-do">{t(`cc.focus.do.${item.kind}`)}</Link>;
}

function FocusCard({ cc }: { cc: CommandCenter }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const now = useNow();
  const item = focus(moments(cc, i18n.language), now);
  if (!item) {
    return (
      <Card kind="accent" className="lg:col-span-5" testId="cc-focus">
        <EmptyState compact icon="checkCircle" title={t("cc.focus.clear")}>{t("cc.focus.clearHint")}</EmptyState>
      </Card>
    );
  }
  const c = clockLeft(item.at, now);
  const big = c.days >= 1 ? f.num(c.days) : `${f.num(c.hours)}:${f.num(String(c.minutes).padStart(2, "0")).padStart(2, f.lang === "fa" ? "۰" : "0")}`;
  const unit = c.passed ? t("cc.focus.passed") : c.days >= 1 ? t("cc.focus.daysLeft") : t("cc.focus.hoursLeft");
  const pct = timeLeftPercent(item, now);
  const tenderId = item.kind === "tender" ? item.key.split("-").slice(1, 6).join("-") : null;
  const env = tenderId ? cc.tenders?.envelopes_incomplete.find((e) => e.tender_id === tenderId) : undefined;
  return (
    <article className="flex flex-col gap-6 rounded-3xl border border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to p-7 sm:flex-row sm:items-center lg:col-span-5" data-testid="cc-focus" data-kind={item.kind}>
      <ProgressRing value={pct} size={140} stroke={8} tone={c.passed ? "danger" : "accent"} label={`${t("cc.focus.timeLeft")}: ${big} ${unit}`}>
        <span className="flex flex-col items-center leading-none">
          <span className="font-display text-4xl font-semibold text-title tabular-nums" data-testid="cc-focus-clock">{big}</span>
          <span className="mt-1.5 text-xs text-muted">{unit}</span>
        </span>
      </ProgressRing>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <span className="text-xs tracking-wide text-accent">{t("cc.focus.eyebrow")} · {t(`cc.focus.kind.${item.kind}`)}</span>
        <h2 className="font-display text-2xl font-semibold text-title [overflow-wrap:anywhere]"><bdi>{item.title}</bdi></h2>
        {item.detail && <p className="text-sm text-fg-2"><bdi>{item.kind === "tender" ? t(`tenders.dateKinds.${item.detail}`, { defaultValue: item.detail }) : item.detail}</bdi></p>}
        {env && <div className="flex flex-wrap gap-1.5" data-testid="cc-focus-steps"><Chip>{t("tenders.envelopes.progress", { done: f.num(env.done), total: f.num(env.total) })}</Chip></div>}
        <p className="text-xs text-muted tabular-nums">{item.allDay ? f.day(item.at.slice(0, 10)) : f.date(item.at, true)}</p>
        <div className="mt-1 flex flex-wrap gap-2">
          <FocusAction item={item} />
          <Link to={item.link} className={buttonClass("secondary", "md")} data-testid="cc-focus-open">{t("cc.focus.open")}</Link>
        </div>
      </div>
    </article>
  );
}

function TodayLine({ cc }: { cc: CommandCenter }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const now = useNow();
  const all = moments(cc, i18n.language);
  const overdue = (cc.tasks?.overdue.length ?? 0) + cc.overdue.length;
  const line = dayLine(all, now, overdue);
  const current = line.shown.find((m) => !m.passed && !m.done)?.key;
  const todays = todayLine(all, now);
  return (
    <Card className="lg:col-span-7" title={t("cc.line.title")} testId="cc-today-line"
      subtitle={lineCounts(todays).map((c) => t(`cc.line.kinds.${c.kind}`, { count: c.n, n: f.num(c.n) })).join(" · ") || undefined}
      actions={<span className="flex flex-wrap items-center gap-3 text-xs" data-testid="cc-line-aside">
        {line.untimed > 0 && <Link to="/tasks" className="text-fg-2 hover:text-accent">{t("cc.line.untimed", { count: line.untimed, n: f.num(line.untimed) })}</Link>}
        {line.overdue > 0 && <Link to="/tasks" className="text-danger hover:underline">{t("cc.line.overdue", { count: line.overdue, n: f.num(line.overdue) })}</Link>}
      </span>}>
      {line.shown.length === 0 ? <EmptyState compact icon="calendar">{t("cc.line.emptyTimed")}</EmptyState> : (
        <>
          <DayLine label={t("cc.line.title")} now={line.now} nowLabel={t("cc.line.now")}
            items={line.shown.map((m) => ({ key: m.key, position: m.position, when: f.time(new Date(m.at)), title: m.title, href: m.link,
              done: m.done, passed: m.passed, current: m.key === current }))}
            renderLink={(item, children) => <Link to={item.href!} className="block hover:text-accent">{children}</Link>} />
          {line.more > 0 && <div className="text-end"><Link to="/tasks" className="text-sm text-accent hover:underline" data-testid="cc-line-more">{t("cc.line.more", { n: f.num(line.more) })}</Link></div>}
        </>
      )}
    </Card>
  );
}

function Kpis({ o }: { o: Overview }) {
  const { t } = useTranslation();
  const f = useFormat();
  const { user } = useAuth();
  const period = user?.calendar === "gregorian" ? o.profit_quarter.gregorian : o.profit_quarter.jalali;
  const periodLabel = user?.calendar === "gregorian" ? t("cc.kpi.quarter", { q: f.num(Math.floor((Number(period.from.slice(5, 7)) - 1) / 3) + 1) })
    : t("cc.kpi.season", { name: t(`cc.kpi.seasons.${o.profit_quarter.jalali.season}`), year: f.num(String(o.profit_quarter.jalali.year)).replace(/[٬,]/g, "") });
  const [main, ...rest] = period.by_currency;
  const tied = o.tied_up.by_currency;
  const advance = o.tied_up.advance_by_currency ?? [];
  const profit = main ? f.compactMoney(main.profit, main.currency) : null;
  const cur = main?.currency;
  const spark = (period.months ?? []).map((m) => Number(m.by_currency.find((r) => r.currency === cur)?.profit ?? 0));
  const prev = Number(period.previous?.by_currency.find((r) => r.currency === cur)?.profit ?? 0);
  const change = main && prev ? Math.round(((Number(main.profit) - prev) / Math.abs(prev)) * 100) : null;
  const tiedMain = tied[0] ? f.compactMoney(tied[0].amount, tied[0].currency) : null;
  const months = o.win_rate.months.map((m) => ({ key: m.month, label: f.lang === "fa" ? m.month.slice(5, 7) : m.month.slice(5, 7), value: m.won + m.lost }));
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label={t("cc.kpi.title")} data-testid="cc-kpis">
      <KpiTile label={t("cc.kpi.profit")} testId="kpi-profit" emphasis={Boolean(main)}
        value={main ? profit!.figure : "—"} unit={main ? profit!.unit : undefined} full={profit?.full}
        note={main ? `${periodLabel} · ${t("cc.kpi.deals", { n: f.num(period.deals) })}${rest.length ? ` · ${rest.map((r) => f.compactMoney(r.profit, r.currency).text).join("، ")}` : ""}` : t("cc.kpi.noClosed", { period: periodLabel })}>
        {spark.some((v) => v !== 0) && <Sparkline label={t("cc.kpi.profitTrend")} values={spark} height={40} format={(n) => f.compact(n)} />}
        {change !== null && <span className={`text-xs ${change >= 0 ? "text-success" : "text-danger"}`} data-testid="kpi-profit-change">
          {t("cc.kpi.vsPrevious", { pct: `${change >= 0 ? "+" : "−"}${f.num(Math.abs(change), 0)}` })}</span>}
      </KpiTile>
      <KpiTile label={t("cc.kpi.winRate")} testId="kpi-win" value={o.win_rate.percent === null ? "—" : `${f.num(o.win_rate.percent, 0)}٪`.replace("٪", f.lang === "fa" ? "٪" : "%")}
        note={o.win_rate.decided ? t("cc.kpi.winNote", { won: f.num(o.win_rate.won), decided: f.num(o.win_rate.decided) }) : t("cc.kpi.noDecided")}>
        {o.win_rate.decided > 0 && <Bars label={t("cc.kpi.winRate")} items={months} highlight={months[months.length - 1]?.key} format={(n) => f.num(n)} height={44} />}
      </KpiTile>
      <KpiTile label={t("cc.kpi.tiedUp")} testId="kpi-tied" value={tiedMain ? tiedMain.figure : "—"} unit={tiedMain?.unit} full={tiedMain?.full}
        note={<>
          {tied.length ? `${t("cc.kpi.tiedCases", { count: o.tied_up.cases, n: f.num(o.tied_up.cases) })}${tied.length > 1 ? ` · ${tied.slice(1).map((r) => f.compactMoney(r.amount, r.currency).text).join("، ")}` : ""}` : t("cc.kpi.nothingTied")}
          {advance.length > 0 && <span className="block text-muted" data-testid="kpi-advance">{t("cc.kpi.advance")}: {advance.map((r) => f.compactMoney(r.amount, r.currency).text).join("، ")}</span>}
        </>} />
      <KpiTile label={t("cc.kpi.setad")} testId="kpi-setad" value={f.num(o.setad_today.count)} unit={t("cc.kpi.setadUnit")}
        note={o.setad_today.count ? undefined : t("cc.kpi.setadNone")}>
        {o.setad_today.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1.5">{o.setad_today.keywords.map((k) => <Chip key={k.keyword}><bdi>{k.keyword}</bdi> {f.num(k.count)}</Chip>)}</div>
        )}
      </KpiTile>
    </section>
  );
}

function CashCard({ o }: { o: Overview }) {
  const { t } = useTranslation();
  const f = useFormat();
  const cf = o.cash_flow;
  const [currency, setCurrency] = useState<string | null>(null);
  const shown = cf.currencies.find((c) => c.currency === (currency ?? mainCurrency(cf))) ?? null;
  const weekLabel = (iso: string, i: number) => (i === 0 ? t("cc.cash.thisWeek") : f.day(iso).slice(-5));
  return (
    <Card className="lg:col-span-7" title={t("cc.cash.title")} subtitle={t("cc.cash.subtitle")} testId="cc-cash"
      actions={cf.currencies.length > 1 ? <Segmented size="sm" label={t("ds.money.currency")} value={shown?.currency ?? ""} onChange={setCurrency}
        options={cf.currencies.map((c) => ({ value: c.currency, label: <bdi dir="ltr">{c.currency}</bdi> }))} /> : undefined}>
      {!shown ? <EmptyState compact icon="coins">{t("cc.cash.empty")}</EmptyState> : (
        <CashFlow label={`${t("cc.cash.title")} (${shown.currency})`} format={(n) => f.compact(n)}
          legend={{ cashIn: t("cc.cash.in"), cashOut: t("cc.cash.out"), balance: t("cc.cash.net"), lowest: t("cc.cash.lowest") }}
          points={shown.weeks.map((w, i) => ({ key: w.week, label: weekLabel(w.week, i), cashIn: Number(w.in), cashOut: Number(w.out) }))} />
      )}
      {(cf.overdue.length > 0 || cf.undated > 0) && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          {cf.overdue.map((o) => <Status key={o.currency} tone="warning">{t("cc.cash.overdue", { in: f.num(o.in, 0), out: f.num(o.out, 0), currency: o.currency })}</Status>)}
          {cf.undated > 0 && <span>{t("cc.cash.undated", { n: f.num(cf.undated) })}</span>}
        </p>
      )}
    </Card>
  );
}

function AiCard({ cc }: { cc: CommandCenter }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ai = cc.ai;
  return (
    <Card className="lg:col-span-5" title={t("cc.aiLine.title")} testId="cc-ai"
      actions={<Link to="/settings/ai" className="text-sm text-accent hover:underline">{t("cc.aiLine.settings")}</Link>}>
      {!ai?.configured ? <EmptyState compact icon="sparkle" action={<Link to="/settings/ai" className={buttonClass("secondary", "sm")}>{t("cc.aiLine.connect")}</Link>}>{t("cc.aiLine.none")}</EmptyState> : (
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-light text-title tabular-nums"><bdi dir="ltr">${f.num(ai.spent_usd)}</bdi></span>
            <span className="text-sm text-muted">{t("cc.aiLine.ofCap", { cap: f.num(ai.cap_usd) })}</span>
            {ai.warning && <Status tone={capTone(ai) === "danger" ? "danger" : "warning"}>{t("ai.settings.cap.warning", { level: ai.warning })}</Status>}
          </div>
          <ProgressBar label={t("cc.aiLine.title")} value={ai.percent} tone={capTone(ai) === "danger" ? "danger" : capTone(ai) === "warning" ? "warning" : "accent"} />
          <p className="flex items-center gap-1.5 text-xs text-muted"><Icon name="sparkle" size={12} />{t("ai.settings.cap.subscription", { count: ai.subscription_calls })}</p>
          {!ai.api_fallback_enabled && <p className="text-xs text-warning">{t("ai.settings.cap.disabled")}</p>}
        </div>
      )}
    </Card>
  );
}

export function TodayTop({ cc }: { cc: CommandCenter }) {
  const o = (cc as CommandCenter & { overview?: Overview }).overview;
  return (
    <>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12"><FocusCard cc={cc} /><TodayLine cc={cc} /></div>
      {o && <Kpis o={o} />}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">{o && <CashCard o={o} />}<AiCard cc={cc} /></div>
    </>
  );
}
