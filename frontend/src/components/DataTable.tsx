/** Server-paginated table on TanStack Table. Sorting is reported upward; the server sorts. */
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useTranslation } from "react-i18next";

import { useFormat } from "../lib/prefs";
import { Icon } from "./Icon";
import { EmptyState, Spinner } from "./ui";

export interface SortState {
  id: string;
  desc: boolean;
}

interface Props<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  loading?: boolean;
  sort?: SortState;
  onSortChange?: (s: SortState) => void;
  sortable?: string[];
  rowKey: (row: T) => string;
  empty?: string;
}

export function DataTable<T>({ columns, data, loading, sort, onSortChange, sortable = [], rowKey, empty }: Props<T>) {
  const { t } = useTranslation();
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel(), getRowId: rowKey, manualSorting: true });
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-line bg-surface-2">
              {group.headers.map((header) => {
                const canSort = sortable.includes(header.column.id) && onSortChange;
                const active = sort?.id === header.column.id;
                return (
                  <th key={header.id} className="h-9 px-3 text-start text-xs font-medium whitespace-nowrap text-muted">
                    {canSort ? (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:text-fg"
                        onClick={() => onSortChange!({ id: header.column.id, desc: active ? !sort!.desc : false })}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {active && <span aria-hidden>{sort!.desc ? "▼" : "▲"}</span>}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="border-b border-line last:border-b-0 hover:bg-surface-2">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="h-10 px-3 align-middle">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && data.length === 0 && <EmptyState>{empty ?? t("common.noResults")}</EmptyState>}
      {loading && (
        <div className="absolute inset-0 flex items-start justify-center bg-surface/50 pt-10">
          <Spinner />
        </div>
      )}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-3 py-2 text-xs text-muted">
      <span className="tabular-nums">{t("common.range", { from: f.num(from), to: f.num(to), total: f.num(total) })}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t("common.previous")}
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          className="inline-flex h-7 w-7 items-center justify-center rounded hover:bg-surface-2 disabled:opacity-40"
        >
          <Icon name="chevronStart" size={15} />
        </button>
        <span className="tabular-nums">{t("common.pageOf", { page: f.num(page), pages: f.num(pages) })}</span>
        <button
          type="button"
          aria-label={t("common.next")}
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
          className="inline-flex h-7 w-7 items-center justify-center rounded hover:bg-surface-2 disabled:opacity-40"
        >
          <Icon name="chevron" size={15} />
        </button>
      </div>
    </div>
  );
}
