/** Quick triage (v0.10.0, reference ProTriage): the same Setad listings and the same actions as the table, one
 * listing at a time as a card: S star, R reviewing, D dismiss (with a reason), arrows for the next / previous one,
 * a progress counter. Shows what BOMS has: time left, items, attachments, buyer and the buyer's description. The
 * mockup's match score and «از سابقهٔ خودت» panel are not built (v0.11.0). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useNow, useTimeLeftText } from "../../components/TimeLeft";
import { Button, Card, Chip, EmptyState, ErrorNote, ErrorState, Kbd, Loading, ProgressBar, Skeleton, Status } from "../../design/components";
import { isRtl } from "../../design/dom";
import { api } from "../../lib/api";
import { filtersFromParams, filtersToParams, queryBody } from "../../lib/listings";
import { useFormat } from "../../lib/prefs";
import { advance, progress, triageCommand } from "../../lib/triage";
import type { ListingDetail, ListingRow } from "../../lib/types";
import { DismissDialog } from "./ListingPanel";

type ListingPage = { items: ListingRow[]; total: number };
const BATCH = 100;      // the smallest page the listings API serves

function Fact({ label, value, accent }: { label: string; value: React.ReactNode; accent?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 px-6 py-4">
      <span className="text-xs text-muted">{label}</span>
      <span className={`text-2xl font-light tabular-nums ${accent ? "text-accent" : "text-title"}`}>{value}</span>
    </div>
  );
}

export function TriagePage() {
  const { t } = useTranslation();
  const f = useFormat();
  const now = useNow();
  const left = useTimeLeftText();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const filters = useMemo(() => filtersFromParams(params), [params]);
  const [index, setIndex] = useState(0);
  const [decided, setDecided] = useState<Map<string, string>>(new Map());
  const [dismissing, setDismissing] = useState(false);
  const list = useQuery({
    queryKey: ["listings", "triage", filters],
    queryFn: () => api<ListingPage>("/api/listings/query", { method: "POST", body: queryBody(filters, 1, BATCH, "deadline", "asc") }),
    placeholderData: keepPreviousData, staleTime: Infinity,          // the batch stays put while you decide
  });
  const items = list.data?.items ?? [];
  const current = items[Math.min(index, Math.max(items.length - 1, 0))];
  const detail = useQuery({ queryKey: ["listing", current?.id], queryFn: () => api<ListingDetail>(`/api/listings/${current!.id}`), enabled: Boolean(current) });
  const screen = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/api/listings/${id}/screen`, { method: "POST", body }),
    onSuccess: (_d, { id, body }) => {
      setDecided((m) => new Map(m).set(id, String(body.action)));
      setDismissing(false);
      void qc.invalidateQueries({ queryKey: ["listing", id] });
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "listings" && q.queryKey[1] !== "triage" });
      setIndex((i) => advance(i, items.length, 1));
    },
  });
  const p = progress(new Set(decided.keys()), items.map((r) => r.id));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (dismissing || e.ctrlKey || e.metaKey || e.altKey || !current) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.closest("input, textarea, select, [role=dialog]") || el.isContentEditable)) return;
      const cmd = triageCommand(e.key, isRtl(document.body));
      if (!cmd) return;
      e.preventDefault();
      if (cmd === "next") setIndex((i) => advance(i, items.length, 1));
      else if (cmd === "previous") setIndex((i) => advance(i, items.length, -1));
      else if (cmd === "dismiss") setDismissing(true);
      else if (!screen.isPending) screen.mutate({ id: current.id, body: { action: cmd } });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const back = `/tenders?${filtersToParams(filters).toString()}`;
  const counts = { starred: [...decided.values()].filter((v) => v === "star").length, reviewing: [...decided.values()].filter((v) => v === "reviewing").length,
    dismissed: [...decided.values()].filter((v) => v === "dismiss").length };
  if (list.isLoading) return <Loading rows={6} />;
  if (list.error) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  const d = detail.data;
  const tl = current?.deadline ? left(current.deadline, now, !current.deadline_exact && current.source === "setad_purchase") : null;
  return (
    <div className="flex flex-col gap-5" data-testid="triage">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <h1 className="font-display text-3xl font-semibold text-title">{t("triage.title")}</h1>
        <span className="text-sm text-muted">{t("triage.total", { n: f.num(list.data?.total ?? 0) })}</span>
        <div className="flex min-w-60 flex-1 items-center gap-3" data-testid="triage-progress">
          <ProgressBar label={t("triage.progress")} value={p.percent} className="max-w-sm" />
          <span className="shrink-0 text-sm text-accent tabular-nums">{t("triage.position", { n: f.num(items.length ? Math.min(index, items.length - 1) + 1 : 0), total: f.num(items.length) })}</span>
        </div>
        <span className="flex items-center gap-3 text-xs text-muted">
          <span>{t("triage.counts.starred", { n: f.num(counts.starred) })}</span><span>{t("triage.counts.reviewing", { n: f.num(counts.reviewing) })}</span>
          <span>{t("triage.counts.dismissed", { n: f.num(counts.dismissed) })}</span>
        </span>
        <Link to={back} className="text-sm text-accent hover:underline" data-testid="triage-back">{t("triage.back")}</Link>
      </header>
      {!current ? (
        <Card><EmptyState icon="checkCircle" title={t("triage.emptyTitle")} action={<Link to={back} className="text-sm text-accent hover:underline">{t("triage.back")}</Link>}>{t("triage.empty")}</EmptyState></Card>
      ) : (
        <article className="overflow-hidden rounded-3xl border border-line-strong bg-surface shadow-md" data-testid="triage-card" data-listing={current.id} aria-live="polite">
          <div className="flex flex-col gap-3 px-7 pt-7 pb-5">
            <div className="flex flex-wrap items-center gap-2">
              {decided.has(current.id) && <Status tone="success">{t(`triage.decided.${decided.get(current.id)}`)}</Status>}
              <Status tone={current.status === "starred" ? "warning" : current.status === "dismissed" ? "neutral" : current.status === "converted" ? "success" : "info"}>{t(`listings.status.${current.status}`)}</Status>
              {current.warn.map((w) => <Chip key={w}>{t("triage.keyword", { word: w })}</Chip>)}
              <bdi dir="ltr" className="font-mono text-xs text-muted">{current.external_no}</bdi>
            </div>
            <h2 className="font-display text-3xl leading-snug font-semibold text-title" dir="auto">{current.title}</h2>
            <p className="text-sm text-muted"><bdi>{current.organization}</bdi>{current.province ? <> · <bdi>{current.province}{current.city ? `، ${current.city}` : ""}</bdi></> : null}</p>
          </div>
          <div className="grid grid-cols-2 divide-line border-y border-line lg:grid-cols-4 lg:divide-x rtl:lg:divide-x-reverse">
            <Fact label={t("triage.timeLeft")} value={tl?.text ?? "—"} accent />
            <Fact label={t("triage.items")} value={d?.detail?.items.rows.length != null ? f.num(d.detail.items.rows.length) : "—"} />
            <Fact label={t("triage.attachments")} value={d ? f.num(d.files.length || d.detail?.attachments?.length || current.documents.total || 0) : "—"} />
            <Fact label={t("triage.docPrice")} value={current.document_price == null ? "—" : Number(current.document_price) === 0 ? t("listings.free") : f.num(current.document_price, 0)} />
          </div>
          <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <section className="flex flex-col gap-2 px-7 py-6">
              <h3 className="text-xs tracking-wide text-accent">{t("triage.buyerNote")}</h3>
              {detail.isLoading ? <Skeleton lines={3} /> : d?.detail?.buyer_note || d?.listing.description
                ? <p className="text-sm leading-7 whitespace-pre-line text-fg" dir="auto">{d?.detail?.buyer_note || d?.listing.description}</p>
                : <p className="text-sm text-muted">{t("triage.noNote")}</p>}
            </section>
            <section className="flex flex-col gap-2 border-line px-7 py-6 lg:border-s">
              <h3 className="text-xs tracking-wide text-accent">{t("triage.itemsList")}</h3>
              {detail.isLoading ? <Skeleton lines={4} /> : (d?.detail?.items.rows ?? []).length === 0 ? <p className="text-sm text-muted">{t("triage.noItems")}</p> : (
                <ul className="flex flex-col gap-1.5 text-sm">{(d?.detail?.items.rows ?? []).slice(0, 8).map((row, i) => <li key={i} className="truncate" dir="auto">{row.filter(Boolean).slice(0, 3).join(" · ")}</li>)}</ul>
              )}
            </section>
          </div>
        </article>
      )}
      {current && (
        <div className="flex flex-wrap items-center justify-center gap-3" data-testid="triage-actions">
          <Button size="lg" variant="ghost" onClick={() => setDismissing(true)} data-testid="triage-dismiss"><Kbd>D</Kbd> {t("listings.dismiss")}</Button>
          <Button size="lg" onClick={() => screen.mutate({ id: current.id, body: { action: "reviewing" } })} busy={screen.isPending && screen.variables?.body.action === "reviewing"} data-testid="triage-reviewing"><Kbd>R</Kbd> {t("listings.reviewing")}</Button>
          <Button size="lg" variant="primary" onClick={() => screen.mutate({ id: current.id, body: { action: "star" } })} busy={screen.isPending && screen.variables?.body.action === "star"} data-testid="triage-star"><Kbd onAccent>S</Kbd> ★ {t("triage.starNext")}</Button>
          <Button size="lg" variant="ghost" onClick={() => setIndex((i) => advance(i, items.length, 1))} data-testid="triage-next">{t("triage.next")} <Kbd>{f.lang === "fa" ? "←" : "→"}</Kbd></Button>
        </div>
      )}
      <ErrorNote error={screen.error} />
      {dismissing && current && <DismissDialog onClose={() => setDismissing(false)} busy={screen.isPending} error={screen.error}
        onConfirm={(reason) => screen.mutate({ id: current.id, body: { action: "dismiss", reason } })} />}
    </div>
  );
}
