import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { type DragEvent, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { Bdi } from "../../components/Bdi";
import { DataTable, Pagination, type SortState } from "../../components/DataTable";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card, ErrorNote, errorMessage, Input, PageHeader, Select, Spinner } from "../../components/ui";
import { api, ApiError, type Page } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { DocumentDetail, DocumentItem } from "../../lib/types";

const PAGE_SIZE = 25;
const TYPE_FILTERS = ["", "application/pdf", "image/", "text/", "application/"] as const;

type UploadState =
  | { name: string; status: "uploading" }
  | { name: string; status: "done"; id: string }
  | { name: string; status: "duplicate"; id: string; title: string }
  | { name: string; status: "error"; error: unknown };

export function textStatusTone(status: DocumentItem["text_status"]) {
  return status === "done" ? "success" : status === "failed" ? "danger" : status === "pending" ? "warning" : "neutral";
}

export function DocumentsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const q = params.get("q") ?? "";
  const mime = params.get("type") ?? "";
  const page = Number(params.get("page") ?? 1);
  const sort: SortState = { id: params.get("sort") ?? "uploaded_at", desc: params.get("order") !== "asc" };

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };

  const query = useQuery({
    queryKey: ["documents", q, mime, page, sort.id, sort.desc],
    queryFn: () =>
      api<Page<DocumentItem>>("/api/documents", {
        query: { q, mime, page, page_size: PAGE_SIZE, sort: sort.id, order: sort.desc ? "desc" : "asc" },
      }),
    placeholderData: keepPreviousData,
  });

  const uploadFiles = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      setUploads((list) => [{ name: file.name, status: "uploading" }, ...list.filter((u) => u.name !== file.name)]);
      const form = new FormData();
      form.append("file", file);
      let result: UploadState;
      try {
        const doc = await api<DocumentDetail>("/api/documents", { method: "POST", form });
        result = { name: file.name, status: "done", id: doc.id };
      } catch (err) {
        if (err instanceof ApiError && err.code === "duplicate_document") {
          result = { name: file.name, status: "duplicate", id: String(err.details.id), title: String(err.details.title) };
        } else {
          result = { name: file.name, status: "error", error: err };
        }
      }
      setUploads((list) => list.map((u) => (u.name === file.name ? result : u)));
    }
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files);
  };

  const columns = useMemo<ColumnDef<DocumentItem, unknown>[]>(
    () => [
      {
        id: "title",
        header: t("documents.title"),
        cell: ({ row }) => (
          <Link to={`/documents/${row.original.id}`} className="font-medium text-accent hover:underline">
            {row.original.title}
          </Link>
        ),
      },
      {
        id: "original_filename",
        header: t("documents.filename"),
        cell: ({ row }) => <Bdi className="text-muted">{row.original.original_filename}</Bdi>,
      },
      { id: "type", header: t("documents.type"), cell: ({ row }) => <Bdi className="text-xs text-muted">{row.original.mime_type}</Bdi> },
      { id: "size_bytes", header: t("documents.size"), cell: ({ row }) => <span className="tabular-nums">{f.bytes(row.original.size_bytes)}</span> },
      { id: "uploaded_at", header: t("documents.uploadedAt"), cell: ({ row }) => <span className="tabular-nums">{f.date(row.original.uploaded_at, true)}</span> },
      {
        id: "text",
        header: t("documents.text"),
        cell: ({ row }) =>
          row.original.text_status === "none" ? null : (
            <Badge tone={textStatusTone(row.original.text_status)}>{t(`documents.textStatus.${row.original.text_status}`)}</Badge>
          ),
      },
    ],
    [t, f],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragging(false);
      }}
      onDrop={onDrop}
      className="relative"
    >
      <PageHeader
        title={t("nav.documents")}
        subtitle={t("documents.subtitle")}
        actions={
          <>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => {
                if (e.target.files) void uploadFiles(Array.from(e.target.files));
                e.target.value = "";
              }} />
            <Button variant="primary" icon="upload" onClick={() => fileInput.current?.click()}>
              {t("documents.upload")}
            </Button>
          </>
        }
      />

      <button
        type="button"
        onClick={() => fileInput.current?.click()}
        className={`mb-4 flex w-full flex-col items-center gap-1 rounded-lg border-2 border-dashed px-4 py-5 text-sm ${
          dragging ? "border-accent bg-accent-soft text-accent" : "border-line-strong bg-surface text-muted hover:border-accent"
        }`}
      >
        <Icon name="upload" size={22} />
        {t("documents.dropHere")}
      </button>

      {uploads.length > 0 && (
        <Card className="mb-4" title={t("documents.uploads")} actions={<Button variant="ghost" onClick={() => setUploads([])}>{t("common.clear")}</Button>}>
          <ul className="flex flex-col gap-1.5 text-sm">
            {uploads.map((u) => (
              <li key={u.name} className="flex items-center gap-2">
                {u.status === "uploading" && <Spinner size={14} />}
                {u.status === "done" && <Icon name="check" size={15} className="text-success" />}
                {(u.status === "duplicate" || u.status === "error") && <Icon name="alert" size={15} className={u.status === "error" ? "text-danger" : "text-warning"} />}
                <Bdi className="font-medium">{u.name}</Bdi>
                <span className="text-muted">
                  {u.status === "uploading" && t("documents.uploading")}
                  {u.status === "done" && (
                    <Link className="text-accent hover:underline" to={`/documents/${u.id}`}>{t("documents.uploaded")}</Link>
                  )}
                  {u.status === "duplicate" && (
                    <>
                      {t("documents.duplicate")}{" "}
                      <Link className="text-accent hover:underline" to={`/documents/${u.id}`}>{u.title}</Link>
                    </>
                  )}
                  {u.status === "error" && <span className="text-danger">{errorMessage(t, u.error)}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input
            type="search"
            className="max-w-xs"
            placeholder={t("documents.searchPlaceholder")}
            defaultValue={q}
            onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })}
            onBlur={(e) => e.target.value !== q && set({ q: e.target.value })}
          />
          <Select className="w-44" value={mime} onChange={(e) => set({ type: e.target.value })} aria-label={t("documents.type")}>
            {TYPE_FILTERS.map((v) => (
              <option key={v} value={v}>{t(`documents.types.${v.replace(/\W/g, "") || "all"}`)}</option>
            ))}
          </Select>
        </div>
        {query.error ? <div className="p-3"><ErrorNote error={query.error} /></div> : null}
        <DataTable
          columns={columns}
          data={query.data?.items ?? []}
          loading={query.isFetching}
          rowKey={(d) => d.id}
          sortable={["title", "original_filename", "size_bytes", "uploaded_at"]}
          sort={sort}
          onSortChange={(s) => set({ sort: s.id, order: s.desc ? "desc" : "asc" })}
          empty={t("documents.empty")}
        />
        <Pagination page={page} pageSize={PAGE_SIZE} total={query.data?.total ?? 0} onPage={(p) => set({ page: String(p) })} />
      </Card>
    </div>
  );
}
