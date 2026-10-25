import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useParams, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DataTable, Pagination } from "../../components/DataTable";
import { Badge, Button, Card, Checkbox, ErrorNote, Field, Input, Modal, PageHeader, Segmented, Select } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Country, Currency, Unit } from "../../lib/types";

type Kind = "countries" | "currencies" | "units";
type Row = Country | Currency | Unit;
const KINDS: Kind[] = ["countries", "currencies", "units"];
const UNIT_KINDS = ["count", "weight", "length", "area", "volume", "time", "other"];
const PAGE_SIZE = 50;

const keyOf = (kind: Kind, row: Row) => (kind === "countries" ? (row as Country).iso2 : (row as Currency | Unit).code);

type FormValues = Record<string, string | boolean>;

function emptyForm(kind: Kind): FormValues {
  if (kind === "countries") return { iso2: "", iso3: "", name_fa: "", name_en: "", sort_order: "100", active: true };
  if (kind === "currencies") return { code: "", name_fa: "", name_en: "", symbol: "", minor_units: "2", active: true };
  return { code: "", name_fa: "", name_en: "", kind: "count", base_factor: "1", active: true };
}

function toForm(kind: Kind, row: Row): FormValues {
  const values: FormValues = {};
  Object.entries(emptyForm(kind)).forEach(([k]) => {
    const v = (row as unknown as Record<string, unknown>)[k];
    values[k] = typeof v === "boolean" ? v : v === null || v === undefined ? "" : String(v);
  });
  return values;
}

function toPayload(kind: Kind, values: FormValues, editing: boolean) {
  const payload: Record<string, unknown> = { ...values };
  if (kind === "countries") payload.sort_order = Number(values.sort_order);
  if (kind === "currencies") {
    payload.minor_units = values.minor_units === "" ? null : Number(values.minor_units);
    payload.symbol = values.symbol || null;
  }
  if (editing) {
    delete payload.iso2;
    delete payload.code;
  }
  return payload;
}

function EditDialog({ kind, row, onClose }: { kind: Kind; row: Row | null | "new"; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const editing = row !== "new" && row !== null;
  const [values, setValues] = useState<FormValues>(() => (editing ? toForm(kind, row as Row) : emptyForm(kind)));
  const set = (k: string, v: string | boolean) => setValues((old) => ({ ...old, [k]: v }));

  const mutation = useMutation({
    mutationFn: () =>
      editing
        ? api(`/api/basedata/${kind}/${keyOf(kind, row as Row)}`, { method: "PATCH", body: toPayload(kind, values, true) })
        : api(`/api/basedata/${kind}`, { method: "POST", body: toPayload(kind, values, false) }),
    onSuccess: () => {
      toast(t("common.saved"), "success");
      void queryClient.invalidateQueries({ queryKey: ["basedata", kind] });
      onClose();
    },
  });

  const text = (name: string, label: string, opts: { ltr?: boolean; disabled?: boolean; required?: boolean; pattern?: string } = {}) => (
    <Field label={label} htmlFor={`bd-${name}`}>
      <Input
        id={`bd-${name}`}
        dir={opts.ltr ? "ltr" : undefined}
        value={String(values[name] ?? "")}
        disabled={opts.disabled}
        required={opts.required ?? true}
        pattern={opts.pattern}
        onChange={(e) => set(name, e.target.value)}
      />
    </Field>
  );

  return (
    <Modal
      open
      title={editing ? t("basedata.editTitle") : t("basedata.addTitle")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" busy={mutation.isPending} type="submit" form="basedata-form">{t("common.save")}</Button>
        </>
      }
    >
      <form
        id="basedata-form"
        className="grid grid-cols-2 gap-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        {kind === "countries" && (
          <>
            {text("iso2", t("basedata.iso2"), { ltr: true, disabled: editing, pattern: "[A-Za-z]{2}" })}
            {text("iso3", t("basedata.iso3"), { ltr: true, pattern: "[A-Za-z]{3}" })}
          </>
        )}
        {kind !== "countries" && text("code", t("basedata.code"), {
          ltr: true, disabled: editing, pattern: kind === "currencies" ? "[A-Za-z]{3}" : "[a-z0-9_]{1,16}",
        })}
        {kind === "units" && (
          <Field label={t("basedata.kind")} htmlFor="bd-kind">
            <Select id="bd-kind" value={String(values.kind)} onChange={(e) => set("kind", e.target.value)}>
              {UNIT_KINDS.map((k) => <option key={k} value={k}>{t(`basedata.unitKinds.${k}`)}</option>)}
            </Select>
          </Field>
        )}
        {kind === "currencies" && <div />}
        {text("name_fa", t("basedata.nameFa"))}
        {text("name_en", t("basedata.nameEn"), { ltr: true })}
        {kind === "countries" && text("sort_order", t("basedata.sortOrder"), { ltr: true, pattern: "[0-9]+" })}
        {kind === "currencies" && (
          <>
            {text("symbol", t("basedata.symbol"), { required: false })}
            {text("minor_units", t("basedata.minorUnits"), { ltr: true, required: false, pattern: "[0-6]" })}
          </>
        )}
        {kind === "units" && text("base_factor", t("basedata.baseFactor"), { ltr: true, pattern: "[0-9]+(\\.[0-9]{1,12})?" })}
        <div className="col-span-2">
          <Checkbox label={t("basedata.active")} checked={Boolean(values.active)} onChange={(v) => set("active", v)} />
        </div>
        <div className="col-span-2"><ErrorNote error={mutation.error} /></div>
      </form>
    </Modal>
  );
}

export function BaseDataPage() {
  const { kind: rawKind } = useParams();
  const kind: Kind = KINDS.includes(rawKind as Kind) ? (rawKind as Kind) : "countries";
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [active, setActive] = useState<"all" | "true" | "false">("all");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Row | "new" | null>(null);

  const query = useQuery({
    queryKey: ["basedata", kind, q, active, page],
    queryFn: () =>
      api<Page<Row>>(`/api/basedata/${kind}`, {
        query: { q, active: active === "all" ? null : active, page, page_size: PAGE_SIZE },
      }),
    placeholderData: keepPreviousData,
  });

  const toggle = useMutation({
    mutationFn: (row: Row) => api(`/api/basedata/${kind}/${keyOf(kind, row)}`, { method: "PATCH", body: { active: !row.active } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["basedata", kind] }),
  });

  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => {
    const code: ColumnDef<Row, unknown> = {
      id: "code",
      header: t("basedata.code"),
      cell: ({ row }) => <Bdi ltr className="font-mono text-xs font-semibold">{keyOf(kind, row.original)}</Bdi>,
    };
    const names: ColumnDef<Row, unknown>[] = [
      { id: "name_fa", header: t("basedata.nameFa"), cell: ({ row }) => row.original.name_fa },
      { id: "name_en", header: t("basedata.nameEn"), cell: ({ row }) => <Bdi>{row.original.name_en}</Bdi> },
    ];
    const extra: ColumnDef<Row, unknown>[] =
      kind === "countries"
        ? [{ id: "iso3", header: t("basedata.iso3"), cell: ({ row }) => <Bdi ltr className="font-mono text-xs">{(row.original as Country).iso3}</Bdi> }]
        : kind === "currencies"
          ? [
              { id: "symbol", header: t("basedata.symbol"), cell: ({ row }) => <Bdi>{(row.original as Currency).symbol ?? ""}</Bdi> },
              { id: "minor", header: t("basedata.minorUnits"), cell: ({ row }) => f.num((row.original as Currency).minor_units ?? "") },
            ]
          : [
              { id: "kind", header: t("basedata.kind"), cell: ({ row }) => t(`basedata.unitKinds.${(row.original as Unit).kind}`) },
              { id: "factor", header: t("basedata.baseFactor"), cell: ({ row }) => <Bdi ltr className="tabular-nums">{f.num((row.original as Unit).base_factor, 12)}</Bdi> },
            ];
    return [
      code,
      ...names,
      ...extra,
      {
        id: "active",
        header: t("basedata.status"),
        cell: ({ row }) => <Badge tone={row.original.active ? "success" : "neutral"}>{row.original.active ? t("basedata.active") : t("basedata.inactive")}</Badge>,
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button variant="ghost" icon="edit" onClick={() => setEditing(row.original)}>{t("common.edit")}</Button>
            <Button variant="ghost" onClick={() => toggle.mutate(row.original)}>
              {row.original.active ? t("basedata.deactivate") : t("basedata.activate")}
            </Button>
          </div>
        ),
      },
    ];
  }, [kind, t, f, toggle]);

  return (
    <div>
      <PageHeader
        title={t("nav.sub.basedata")}
        subtitle={t("basedata.subtitle")}
        actions={<Button variant="primary" icon="plus" onClick={() => setEditing("new")}>{t("basedata.add")}</Button>}
      />
      <div className="mb-3 flex gap-1 border-b border-line">
        {KINDS.map((k) => (
          <NavLink
            key={k}
            to={`/settings/basedata/${k}`}
            onClick={() => setPage(1)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${k === kind ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}
          >
            {t(`basedata.kinds.${k}`)}
          </NavLink>
        ))}
      </div>
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input
            key={kind + q}
            type="search"
            className="max-w-xs"
            placeholder={t("basedata.searchPlaceholder")}
            defaultValue={q}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setParams((e.target as HTMLInputElement).value ? { q: (e.target as HTMLInputElement).value } : {}, { replace: true });
                setPage(1);
              }
            }}
          />
          <Segmented
            value={active}
            label={t("basedata.status")}
            onChange={(v) => {
              setActive(v);
              setPage(1);
            }}
            options={[
              { value: "all", label: t("common.all") },
              { value: "true", label: t("basedata.active") },
              { value: "false", label: t("basedata.inactive") },
            ]}
          />
        </div>
        <ErrorNote error={query.error || toggle.error} />
        <DataTable columns={columns} data={query.data?.items ?? []} loading={query.isFetching} rowKey={(r) => keyOf(kind, r)} />
        <Pagination page={page} pageSize={PAGE_SIZE} total={query.data?.total ?? 0} onPage={setPage} />
      </Card>
      {editing && <EditDialog key={kind} kind={kind} row={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
