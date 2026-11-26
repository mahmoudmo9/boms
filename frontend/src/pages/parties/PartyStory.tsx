import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Bdi, Button, Card, EmptyState, ErrorNote, KpiTile, ProgressRing } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { PartyDetail } from "../../lib/types";

/** v0.10.1 section 4.6 (ProParty): the party page reads like a story — who they are, how they performed, what
 * happened with them and which deals they are in. Everything here comes from GET /api/parties/{id}/scorecard. */

type Tile = { value: number | null; n: number; enough: boolean };
export interface Scorecard {
  on_time: Tile & { on_time?: number; avg_late_days?: number | null };
  inspection: Tile & { failed?: number };
  response_time: Tile;
  price_position: Tile & { cheapest?: number; compared?: number };
  min_sample: number;
  story: {
    since: string | null;
    counts: { rfqs: number; orders: number; claims: number };
    timeline: { kind: string; at: string; ref: string | null; amount: string | null; currency: string | null; case_id: string | null }[];
    deals: { case_id: string; title: string; status: string;
      margin: { actual: string | null; planned: string | null; expected: string | null; currency: string | null } }[];
  };
}

export function useScorecard(partyId: string) {
  return useQuery({ queryKey: ["party-scorecard", partyId], queryFn: () => api<Scorecard>(`/api/parties/${partyId}/scorecard`) });
}

export function initials(name: string | null | undefined): string {
  const words = (name ?? "").replace(/[^\p{L}\p{N}\s]/gu, " ").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}

export function PartyAvatar({ name }: { name: string | null | undefined }) {
  return (
    <span aria-hidden="true" data-testid="party-avatar"
      className="inline-grid size-14 shrink-0 place-items-center rounded-2xl border border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to font-display text-xl text-accent">
      {initials(name)}
    </span>
  );
}

/** «همکاری از فروردین ۱۴۰۵ · ۴ استعلام · ۲ سفارش · ۱ ادعا» */
export function PartySince({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const s = useScorecard(partyId).data?.story;
  if (!s || (!s.since && !s.counts.rfqs && !s.counts.orders && !s.counts.claims)) return null;
  return (
    <span data-testid="party-since" className="tabular-nums">
      {s.since && <>{t("party.story.since", { date: f.date(s.since) })} · </>}
      {t("party.story.counts", { rfqs: s.counts.rfqs, orders: s.counts.orders, claims: s.counts.claims })}
    </span>
  );
}

/** The four supplier tiles (0.3.1 KPI services) plus the ratings ring. A tile with too few data points says so. */
export function PartyKpis({ party, ratings }: { party: PartyDetail; ratings: { average: number | null; count: number } }) {
  const { t } = useTranslation();
  const f = useFormat();
  const sc = useScorecard(party.id).data;
  if (!sc) return null;
  const supplier = party.roles.some((r) => r.role === "supplier" || r.role === "manufacturer") || [sc.on_time, sc.inspection, sc.response_time, sc.price_position].some((x) => x.n > 0);
  const few = (x: Tile) => t("party.kpi.notEnough", { n: x.n, min: sc.min_sample });
  const hours = sc.response_time.value;
  const tiles = supplier ? [
    <KpiTile key="on" testId="kpi-on-time" label={t("party.kpi.onTime")} tone={sc.on_time.enough && (sc.on_time.value ?? 0) < 80 ? "warning" : "neutral"}
      value={sc.on_time.enough ? t("party.kpi.xOfY", { x: sc.on_time.on_time ?? 0, y: sc.on_time.n }) : "—"}
      note={!sc.on_time.enough ? few(sc.on_time) : sc.on_time.avg_late_days ? t("party.kpi.avgLate", { n: f.num(sc.on_time.avg_late_days, 1) }) : t("party.kpi.allOnTime")} />,
    <KpiTile key="insp" testId="kpi-inspection" label={t("party.kpi.inspection")} tone={sc.inspection.failed ? "warning" : "neutral"}
      value={sc.inspection.enough ? t("party.kpi.xOfY", { x: sc.inspection.n - (sc.inspection.failed ?? 0), y: sc.inspection.n }) : "—"}
      note={!sc.inspection.enough ? few(sc.inspection) : sc.inspection.failed ? t("party.kpi.failed", { count: sc.inspection.failed }) : t("party.kpi.allPassed")} />,
    <KpiTile key="resp" testId="kpi-response" label={t("party.kpi.response")}
      value={sc.response_time.enough && hours !== null ? (hours >= 48 ? f.num(hours / 24, 1) : f.num(hours, 0)) : "—"}
      unit={sc.response_time.enough && hours !== null ? t(hours >= 48 ? "party.kpi.days" : "party.kpi.hours") : undefined}
      note={!sc.response_time.enough ? few(sc.response_time) : t("party.kpi.responseNote", { count: sc.response_time.n })} />,
    <KpiTile key="price" testId="kpi-price" label={t("party.kpi.price")}
      value={sc.price_position.enough ? (sc.price_position.cheapest === sc.price_position.compared ? t("party.kpi.cheapest") : t("party.kpi.xOfY", { x: sc.price_position.cheapest ?? 0, y: sc.price_position.compared ?? 0 })) : "—"}
      note={!sc.price_position.enough ? few(sc.price_position) : t("party.kpi.priceNote", { x: sc.price_position.cheapest ?? 0, y: sc.price_position.compared ?? 0 })} />,
  ] : [];
  if (!tiles.length && ratings.average === null) return null;
  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch" data-testid="party-scores">
      {ratings.average !== null && (
        <article className="flex items-center gap-4 rounded-2xl border border-accent-line bg-linear-to-br from-card-accent-from to-card-accent-to px-5 py-4 lg:w-60" data-testid="party-rating">
          <ProgressRing value={(ratings.average / 5) * 100} size={76} label={t("party.scores.overall")}>
            <span className="text-lg text-title tabular-nums">{f.num(ratings.average, 1)}</span>
          </ProgressRing>
          <span className="flex flex-col gap-1 text-xs text-muted">
            <span>{t("party.scores.overall")}</span>
            <span className="tabular-nums">{t("party.kpi.outOf5")} · {t("party.scores.ratings", { n: f.num(ratings.count) })}</span>
          </span>
        </article>
      )}
      {tiles.length > 0 && <div className="grid flex-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{tiles}</div>}
    </div>
  );
}

const TONE: Record<string, string> = { claim: "bg-danger", payment_in: "bg-success", payment_out: "bg-accent", auto: "bg-info" };

/** v0.10.1 (0.4.3): one automatic role or stage change, with its cause and whether «برگرداندن» is still possible. */
export interface AutoChange { event_id: number; at: string; action: "stage_auto" | "role_auto"; role: string; old_stage?: string; new_stage?: string;
  stage?: string; rule: string; cause: { kind: string; code?: string | null; days?: number } & Record<string, unknown>; revertible: boolean; reverted: boolean }

export function useAutomaticChanges(partyId: string) {
  return useQuery({ queryKey: ["party-auto", partyId],
    queryFn: () => api<{ changes: AutoChange[]; suggest_lost: { quotes: number } | null }>(`/api/parties/${partyId}/automatic-changes`) });
}

/** «خودکار: سفارش خرید PO-1405-0007 صادر شد» */
export function autoCause(t: TFunction, c: AutoChange): string {
  return `${t("party.rules.auto")}: ${t(`party.rules.cause.${c.cause.kind}`, { code: c.cause.code ?? "", days: c.cause.days ?? "" })}`;
}

export function autoText(t: TFunction, c: AutoChange): string {
  const role = t(`parties.roles.${c.role}`);
  return c.action === "role_auto" ? t("party.rules.roleAdded", { role })
    : t("party.rules.stageMoved", { role, from: t(`funnel.stages.${c.role}.${c.old_stage}`), to: t(`funnel.stages.${c.role}.${c.new_stage}`) });
}

export function PartyTimeline({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const s = useScorecard(partyId).data?.story;
  const auto = useAutomaticChanges(partyId).data?.changes ?? [];
  const revert = useMutation({
    mutationFn: (id: number) => api(`/api/parties/${partyId}/automatic-changes/${id}/revert`, { method: "POST" }),
    onSuccess: () => { for (const key of [["party-auto", partyId], ["party", partyId], ["party-scorecard", partyId]]) void qc.invalidateQueries({ queryKey: key }); },
  });
  // the story's past events and the automatic stage changes (0.4.3) on one line, newest first
  type Entry = { at: string; story?: NonNullable<typeof s>["timeline"][number]; auto?: AutoChange };
  const entries: Entry[] = [...(s?.timeline ?? []).map((e) => ({ at: e.at, story: e })), ...auto.map((a) => ({ at: a.at, auto: a }))]
    .sort((a, b) => b.at.localeCompare(a.at)).slice(0, 16);
  return (
    <Card title={t("party.story.timeline")} testId="party-timeline">
      {entries.length === 0 ? <EmptyState>{t("party.story.noTimeline")}</EmptyState> : (
        <ol className="relative flex flex-col gap-5 ps-5 before:absolute before:inset-y-1.5 before:start-1 before:w-px before:bg-line">
          {entries.map((entry, i) => entry.auto ? (
            <li key={`auto-${entry.auto.event_id}`} className="relative flex flex-col gap-0.5" data-testid="timeline-auto">
              <span aria-hidden="true" className={`absolute -start-5 top-1.5 size-2.5 rounded-full ${TONE.auto}`} />
              <span className="text-xs text-muted tabular-nums">{f.date(entry.auto.at)}</span>
              <span className="text-sm"><Bdi>{autoText(t, entry.auto)}</Bdi></span>
              <span className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <Bdi>{autoCause(t, entry.auto)}</Bdi>
                {entry.auto.revertible && <Button size="sm" variant="ghost" busy={revert.isPending && revert.variables === entry.auto.event_id}
                  onClick={() => revert.mutate(entry.auto!.event_id)} data-testid="auto-revert">{t("party.rules.revert")}</Button>}
                {entry.auto.reverted && <Badge>{t("party.rules.reverted")}</Badge>}
              </span>
            </li>
          ) : (() => {
            const e = entry.story!;
            const text = t(`party.story.kind.${e.kind}`, {
              ref: e.ref ?? "", amount: e.amount !== null && e.currency ? f.compactMoney(e.amount, e.currency).text : "",
              claim: e.kind === "claim" && e.ref ? t(`execution.claims.kinds.${e.ref}`, { defaultValue: e.ref }) : "" }).replace(/ · $/, "");
            return (
              <li key={`${e.kind}-${e.at}-${i}`} className="relative flex flex-col gap-0.5">
                <span aria-hidden="true" className={`absolute -start-5 top-1.5 size-2.5 rounded-full ${TONE[e.kind] ?? "bg-accent-bright"}`} />
                <span className="text-xs text-muted tabular-nums">{f.date(e.at)}</span>
                <span className="text-sm">
                  {e.case_id ? <Link className="hover:text-accent hover:underline" to={`/cases/${e.case_id}`}><Bdi>{text}</Bdi></Link> : <Bdi>{text}</Bdi>}
                </span>
              </li>
            );
          })())}
        </ol>
      )}
      <ErrorNote error={revert.error} />
    </Card>
  );
}

export function PartyDeals({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const deals = useScorecard(partyId).data?.story.deals ?? [];
  const pct = (v: string | null) => (v === null ? null : f.num(Number(v), 0));
  return (
    <Card title={t("party.story.deals")} padded={false} testId="party-deals">
      {deals.length === 0 ? <EmptyState>{t("party.story.noDeals")}</EmptyState> : (
        <ul className="divide-y divide-line">
          {deals.map((d) => {
            const m = d.margin;
            const closed = d.status === "closed";
            return (
              <li key={d.case_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <Link to={`/cases/${d.case_id}`} className="min-w-0 flex-1 truncate hover:text-accent hover:underline"><Bdi>{d.title}</Bdi></Link>
                {closed && m.actual !== null && <span className="text-success tabular-nums">{t("party.story.profit", { n: pct(m.actual) })}</span>}
                {!closed && (
                  <span className="text-warning tabular-nums">
                    {t("party.story.inProgress")}
                    {(m.expected ?? m.planned) !== null && <> · {t(m.expected !== null ? "party.story.expected" : "party.story.planned", { n: pct(m.expected ?? m.planned) })}</>}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export function PartyContactsCard({ party, onOpen }: { party: PartyDetail; onOpen: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const active = party.contacts.filter((c) => c.status === "active");
  return (
    <Card title={t("parties.tabs.contacts")} padded={false} testId="party-contacts-card"
      actions={<button type="button" className="text-xs text-accent hover:underline" onClick={onOpen}>{t("party.story.all")}</button>}>
      {active.length === 0 ? <EmptyState>{t("party.story.noContacts")}</EmptyState> : (
        <ul className="divide-y divide-line">
          {active.slice(0, 5).map((c) => (
            <li key={c.id} className="flex items-center gap-2 px-4 py-2.5 text-sm">
              <Bdi className="font-medium">{(f.lang === "fa" ? c.name_fa || c.name_en : c.name_en || c.name_fa) ?? ""}</Bdi>
              {c.job_title && <span className="text-muted">· <Bdi>{c.job_title}</Bdi></span>}
              {c.is_primary && <Badge tone="accent" className="ms-auto">{t("party.story.primary")}</Badge>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function PartyDocumentsCard({ party, onOpen }: { party: PartyDetail; onOpen: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  return (
    <Card title={t("parties.documents")} padded={false} testId="party-documents-card"
      actions={<button type="button" className="text-xs text-accent hover:underline" onClick={onOpen}>{t("party.story.all")}</button>}>
      {party.documents.length === 0 ? <EmptyState>{t("parties.noDocuments")}</EmptyState> : (
        <ul className="divide-y divide-line">
          {party.documents.slice(0, 5).map((d) => (
            <li key={d.link_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <Link to={`/documents/${d.document_id}`} className="min-w-0 flex-1 truncate hover:text-accent hover:underline"><Bdi>{d.title}</Bdi></Link>
              <span className="text-xs text-muted tabular-nums">{f.bytes(d.size_bytes)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
