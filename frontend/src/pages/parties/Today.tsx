/** The top of the command center (v0.10.0, reference ProToday / light Main): the most important thing now with its
 * time left, today's timeline, four figures from data BOMS has (profit of the deals closed this quarter, quote win
 * rate, cash tied up now, today's Setad matches by keyword), the cash flow of the next 90 days and the AI line.
 * The mockup's «بینش‌ها» card is not built (rules and AI insights come in v0.11.0). */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useNow, useTimeLeftText } from "../../components/TimeLeft";
import { Bars, buttonClass, Card, CashFlow, Chip, DatedTimeline, EmptyState, Icon, KpiTile, ProgressBar, ProgressRing, Segmented, Status } from "../../design/components";
import { capTone } from "../../lib/ai";
import { useAuth } from "../../lib/auth";
import { useFormat } from "../../lib/prefs";
import { focus, mainCurrency, moments, type Overview, timeLeftPercent, todayLine } from "../../lib/today";
import type { CommandCenter } from "../../lib/types";

function FocusCard({ cc }: { cc: CommandCenter }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const now = useNow();
  const left = useTimeLeftText();
  const item = focus(moments(cc, i18n.language), now);
  if (!item) {
    return (
      <Card kind="accent" className="lg:col-span-5" testId="cc-focus">
        <EmptyState compact icon="checkCircle" title={t("cc.focus.clear")}>{t("cc.focus.clearHint")}</EmptyState>
      </Card>
    );
  }
  const text = left(item.at, now)?.text ?? "";
  const pct = timeLeftPercent(item, now);
  const passed = new Date(item.at).getTime() < now.getTime();
  return (
    <article className="flex flex-col gap-6 rounded-3xl border border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to p-7 sm:flex-row sm:items-center lg:col-span-5" data-testid="cc-focus" data-kind={item.kind}>
      <ProgressRing value={pct} size={140} stroke={8} tone={passed ? "danger" : "accent"} label={`${t("cc.focus.timeLeft")}: ${text}`}>
        <span className="max-w-24 text-center text-md leading-tight text-title">{text}</span>
      </ProgressRing>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <span className="text-xs tracking-wide text-accent">{t("cc.focus.eyebrow")} · {t(`cc.focus.kind.${item.kind}`)}</span>
        <h2 className="font-display text-2xl font-semibold text-title [overflow-wrap:anywhere]"><bdi>{item.title}</bdi></h2>
        {item.detail && <p className="text-sm text-fg-2"><bdi>{item.kind === "tender" ? t(`tenders.dateKinds.${item.detail}`, { defaultValue: item.detail }) : item.detail}</bdi></p>}
        <p className="text-xs text-muted tabular-nums">{item.allDay ? f.day(item.at.slice(0, 10)) : f.date(item.at, true)}</p>
        <div className="mt-1 flex flex-wrap gap-2"><Link to={item.link} className={buttonClass("primary", "md")} data-testid="cc-focus-open">{t("cc.focus.open")}</Link></div>
      </div>
    </article>
  );
}

function TodayLine({ cc }: { cc: CommandCenter }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const now = useNow();
  const line = todayLine(moments(cc, i18n.language), now);
  return (
    <Card className="lg:col-span-7" title={t("cc.line.title")} subtitle={t("cc.line.count", { n: f.num(line.length) })} testId="cc-today-line">
      {line.length === 0 ? <EmptyState compact icon="calendar">{t("cc.line.empty")}</EmptyState> : (
        <DatedTimeline label={t("cc.line.title")} items={line.map((m) => ({
          key: m.key, state: m.state, when: m.allDay ? t("cc.line.allDay") : f.date(m.at, true).slice(-5),
          title: <Link to={m.link} className="hover:text-accent"><bdi>{m.title}</bdi></Link>, detail: t(`cc.focus.kind.${m.kind}`) }))} />
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
  const months = o.win_rate.months.map((m) => ({ key: m.month, label: f.lang === "fa" ? m.month.slice(5, 7) : m.month.slice(5, 7), value: m.won + m.lost }));
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label={t("cc.kpi.title")} data-testid="cc-kpis">
      <KpiTile label={t("cc.kpi.profit")} testId="kpi-profit" emphasis={Boolean(main)}
        value={main ? f.num(main.profit, 0) : "—"} unit={main ? <bdi dir="ltr">{main.currency}</bdi> : undefined}
        note={main ? `${periodLabel} · ${t("cc.kpi.deals", { n: f.num(period.deals) })}${rest.length ? ` · ${rest.map((r) => `${f.num(r.profit, 0)} ${r.currency}`).join("، ")}` : ""}` : t("cc.kpi.noClosed", { period: periodLabel })} />
      <KpiTile label={t("cc.kpi.winRate")} testId="kpi-win" value={o.win_rate.percent === null ? "—" : `${f.num(o.win_rate.percent, 0)}٪`.replace("٪", f.lang === "fa" ? "٪" : "%")}
        note={o.win_rate.decided ? t("cc.kpi.winNote", { won: f.num(o.win_rate.won), decided: f.num(o.win_rate.decided) }) : t("cc.kpi.noDecided")}>
        {o.win_rate.decided > 0 && <Bars label={t("cc.kpi.winRate")} items={months} highlight={months[months.length - 1]?.key} format={(n) => f.num(n)} height={44} />}
      </KpiTile>
      <KpiTile label={t("cc.kpi.tiedUp")} testId="kpi-tied" value={tied[0] ? f.num(tied[0].amount, 0) : "—"} unit={tied[0] ? <bdi dir="ltr">{tied[0].currency}</bdi> : undefined}
        note={tied.length ? `${t("cc.kpi.tiedCases", { n: f.num(o.tied_up.cases) })}${tied.length > 1 ? ` · ${tied.slice(1).map((r) => `${f.num(r.amount, 0)} ${r.currency}`).join("، ")}` : ""}` : t("cc.kpi.nothingTied")} />
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
        <CashFlow label={`${t("cc.cash.title")} (${shown.currency})`} format={(n) => `${f.num(n, 0)}`}
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
