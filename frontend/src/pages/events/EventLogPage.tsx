import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Pagination } from "../../components/DataTable";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, PageHeader, Select, Spinner } from "../../components/ui";
import { api, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { EventItem } from "../../lib/types";

const PAGE_SIZE = 50;

/** Translated label for an event action, falling back to the raw action key. */
function useActionLabel() {
  const { t, i18n } = useTranslation();
  return (action: string) => (i18n.exists(`events.actions.${action}`) ? t(`events.actions.${action}`) : action);
}

function useEntityLabel() {
  const { t, i18n } = useTranslation();
  return (type: string) => (i18n.exists(`events.entities.${type}`) ? t(`events.entities.${type}`) : type);
}

export function EventList({ items, compact = false }: { items: EventItem[]; compact?: boolean }) {
  const { t } = useTranslation();
  const f = useFormat();
  const actionLabel = useActionLabel();
  const entityLabel = useEntityLabel();
  const [open, setOpen] = useState<number | null>(null);
  if (items.length === 0) return <EmptyState>{t("events.empty")}</EmptyState>;
  return (
    <ol className="divide-y divide-line">
      {items.map((e) => (
        <li key={e.id} className="px-4 py-2.5 text-sm">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="tabular-nums text-muted">{f.date(e.occurred_at, true)}</span>
            {!compact && <Badge>{entityLabel(e.entity_type)}</Badge>}
            <span className="font-medium">{actionLabel(e.action)}</span>
            {!compact && e.entity_id && <Bdi ltr className="truncate text-xs text-muted">{e.entity_id}</Bdi>}
            <span className="ms-auto flex items-center gap-2 text-xs text-muted">
              <Bdi>{e.actor}</Bdi>
              <Badge tone="accent">{t(`events.sources.${e.source}`)}</Badge>
              {Object.keys(e.data).length > 0 && (
                <button type="button" className="text-accent hover:underline" onClick={() => setOpen(open === e.id ? null : e.id)}>
                  {open === e.id ? t("events.hideData") : t("events.showData")}
                </button>
              )}
            </span>
          </div>
          {open === e.id && (
            <pre dir="ltr" className="mt-2 max-h-64 overflow-auto rounded bg-surface-2 p-2 text-xs">{JSON.stringify(e.data, null, 2)}</pre>
          )}
        </li>
      ))}
    </ol>
  );
}

export function EventLogPage() {
  const { t } = useTranslation();
  const actionLabel = useActionLabel();
  const entityLabel = useEntityLabel();
  const [filters, setFilters] = useState<{ entity_type: string; action: string; from: Date | null; to: Date | null }>({
    entity_type: "",
    action: "",
    from: null,
    to: null,
  });
  const [page, setPage] = useState(1);
  const update = (changes: Partial<typeof filters>) => {
    setFilters({ ...filters, ...changes });
    setPage(1);
  };

  const facets = useQuery({
    queryKey: ["events", "facets"],
    queryFn: () => api<{ entity_types: string[]; actions: string[] }>("/api/events/facets"),
  });
  const to = filters.to ? new Date(filters.to.getFullYear(), filters.to.getMonth(), filters.to.getDate() + 1) : null;
  const events = useQuery({
    queryKey: ["events", filters, page],
    queryFn: () =>
      api<Page<EventItem>>("/api/events", {
        query: {
          entity_type: filters.entity_type,
          action: filters.action,
          from: filters.from?.toISOString(),
          to: to?.toISOString(),
          page,
          page_size: PAGE_SIZE,
        },
      }),
    placeholderData: keepPreviousData,
  });

  return (
    <div>
      <PageHeader title={t("nav.sub.events")} subtitle={t("events.subtitle")} />
      <Card padded={false}>
        <div className="flex flex-wrap items-end gap-3 border-b border-line p-3">
          <Field label={t("events.entityType")} htmlFor="ev-entity">
            <Select id="ev-entity" className="w-44" value={filters.entity_type} onChange={(e) => update({ entity_type: e.target.value })}>
              <option value="">{t("common.all")}</option>
              {facets.data?.entity_types.map((v) => <option key={v} value={v}>{entityLabel(v)}</option>)}
            </Select>
          </Field>
          <Field label={t("events.action")} htmlFor="ev-action">
            <Select id="ev-action" className="w-44" value={filters.action} onChange={(e) => update({ action: e.target.value })}>
              <option value="">{t("common.all")}</option>
              {facets.data?.actions.map((v) => <option key={v} value={v}>{actionLabel(v)}</option>)}
            </Select>
          </Field>
          <Field label={t("events.from")} htmlFor="ev-from">
            <DateInput id="ev-from" value={filters.from} onChange={(d) => update({ from: d })} />
          </Field>
          <Field label={t("events.to")} htmlFor="ev-to">
            <DateInput id="ev-to" value={filters.to} onChange={(d) => update({ to: d })} />
          </Field>
          <Button variant="ghost" onClick={() => update({ entity_type: "", action: "", from: null, to: null })}>
            {t("common.reset")}
          </Button>
          {events.isFetching && <Spinner />}
        </div>
        <ErrorNote error={events.error} />
        <EventList items={events.data?.items ?? []} />
        <Pagination page={page} pageSize={PAGE_SIZE} total={events.data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
