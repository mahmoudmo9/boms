/** Line items of an inquiry or case: table, item dialog (free specs rows, PDF text helper), import dialog. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../components/Bdi";
import { DateInput } from "../../components/DateInput";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, errorMessage, Field, IconButton, Input, Modal, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { fromDateString, toDateString } from "../../lib/followups";
import { useFormat } from "../../lib/prefs";
import { type ColumnMapping, type Delimiter, IMPORT_FIELDS, type ImportField, parsePasted, setColumnField, suggestMapping } from "../../lib/sourcing";
import type { ItemWarning, LineItem, LinkedDocument, Spec } from "../../lib/types";
import { CountrySelect } from "../parties/PartiesPage";
import { AttachedDocuments, CurrencySelect, IncotermSelect, ProductPicker, StatusBadge, UnitInput, useSpecKeys, useUnitLabel } from "./shared";

export interface ItemOwner {
  inquiry_id?: string;
  case_id?: string;
}

type ItemForm = Omit<LineItem, "id" | "inquiry_id" | "case_id" | "position" | "status" | "no_coverage_confirmed" | "no_coverage_reason" | "selected_offer_item_id" | "documents">;

const EMPTY: ItemForm = {
  name: "", description: null, product_id: null, quantity: null, unit_code: null, unit_text: null, target_price: null,
  target_currency: null, destination_country_iso2: null, incoterm: null, incoterm_place: null, required_by: null,
  packaging: null, hs_code: null, route: "unknown", notes: null, specs: [],
};

function SpecsEditor({ specs, onChange }: { specs: Spec[]; onChange: (s: Spec[]) => void }) {
  const { t } = useTranslation();
  const { keys, setQuery } = useSpecKeys();
  const set = (i: number, patch: Partial<Spec>) => onChange(specs.map((s, j) => (i === j ? { ...s, ...patch } : s)));
  return (
    <div className="flex flex-col gap-1.5">
      <datalist id="spec-keys">{keys.map((k) => <option key={k} value={k} />)}</datalist>
      {specs.map((s, i) => (
        <div key={i} className="flex gap-1.5">
          <Input className="w-40" list="spec-keys" dir="auto" aria-label={t("sourcing.item.specKey")} placeholder={t("sourcing.item.specKey")}
            value={s.key} onFocus={() => setQuery(s.key)} onChange={(e) => { set(i, { key: e.target.value }); setQuery(e.target.value); }} />
          <Input className="min-w-0 flex-1" dir="auto" aria-label={t("sourcing.item.specValue")} placeholder={t("sourcing.item.specValue")}
            value={s.value} onChange={(e) => set(i, { value: e.target.value })} />
          <Input className="w-20" dir="ltr" aria-label={t("sourcing.item.specUnit")} placeholder={t("sourcing.item.specUnit")}
            value={s.unit ?? ""} onChange={(e) => set(i, { unit: e.target.value || undefined })} />
          <IconButton icon="x" label={t("sourcing.item.removeSpec")} onClick={() => onChange(specs.filter((_, j) => j !== i))} />
        </div>
      ))}
      <div><Button icon="plus" onClick={() => onChange([...specs, { key: "", value: "" }])}>{t("sourcing.item.addSpec")}</Button></div>
    </div>
  );
}

/** Extracted text of an attached document; clicking a line copies it into the item (name, else description). */
function DocumentTextPanel({ documents, onLine }: { documents: LinkedDocument[]; onLine: (line: string) => void }) {
  const { t } = useTranslation();
  const [docId, setDocId] = useState(documents[0]?.document_id ?? "");
  const text = useQuery({
    queryKey: ["document-text", docId],
    queryFn: () => api<{ text: string; text_status: string }>(`/api/line-items/document-text/${docId}`),
    enabled: !!docId,
  });
  const lines = (text.data?.text ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
  return (
    <div className="flex min-h-0 flex-col gap-2">
      <Select aria-label={t("sourcing.item.documentText")} value={docId} onChange={(e) => setDocId(e.target.value)}>
        {documents.map((d) => <option key={d.link_id} value={d.document_id}>{d.title}</option>)}
      </Select>
      <p className="text-xs text-muted">{t("sourcing.item.copyLineHint")}</p>
      <ol className="max-h-80 overflow-y-auto rounded-md border border-line text-sm">
        {lines.length === 0 && <li className="p-2 text-muted">{text.isFetching ? "…" : t("sourcing.item.noText")}</li>}
        {lines.map((line, i) => (
          <li key={i}><button type="button" dir="auto" className="w-full px-2 py-1 text-start hover:bg-accent-soft" onClick={() => onLine(line)}>{line}</button></li>
        ))}
      </ol>
    </div>
  );
}

export function ItemDialog({ owner, item, ownerDocuments, onClose, onSaved }: {
  owner: ItemOwner;
  item: LineItem | null;
  ownerDocuments: LinkedDocument[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  // only the editable fields: the API rejects unknown ones (id, status, …)
  const [form, setForm] = useState<ItemForm>(() => (item
    ? { ...(Object.fromEntries(Object.keys(EMPTY).map((k) => [k, item[k as keyof ItemForm] ?? EMPTY[k as keyof ItemForm]])) as ItemForm), specs: item.specs ?? [] }
    : EMPTY));
  const set = (patch: Partial<ItemForm>) => setForm((f) => ({ ...f, ...patch }));
  const pdfs = ownerDocuments.filter((d) => d.mime_type === "application/pdf" || d.mime_type.startsWith("text/"));
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, specs: form.specs.filter((s) => s.key.trim()), name: form.name.trim() };
      return item
        ? api(`/api/line-items/${item.id}`, { method: "PATCH", body })
        : api("/api/line-items", { method: "POST", body: { ...owner, ...Object.fromEntries(Object.entries(body).filter(([, v]) => v !== null)) } });
    },
    onSuccess: () => { onSaved(); onClose(); },
  });
  const copyLine = (line: string) => {
    if (!form.name.trim()) set({ name: line });
    else set({ description: form.description ? `${form.description}\n${line}` : line });
  };
  return (
    <Modal open wide title={item ? t("sourcing.item.edit") : t("sourcing.item.add")} onClose={onClose}
      footer={<>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" type="submit" form="item-form" busy={save.isPending} disabled={!form.name.trim()}>{t("common.save")}</Button>
      </>}>
      <div className={`grid gap-4 ${pdfs.length ? "lg:grid-cols-[minmax(0,1fr)_16rem]" : ""}`}>
        <form id="item-form" className="grid max-h-[65vh] grid-cols-1 gap-3 overflow-y-auto pe-1 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          <div className="sm:col-span-2"><Field label={t("sourcing.item.name")} htmlFor="it-name"><Input id="it-name" dir="auto" autoFocus value={form.name} maxLength={1000} onChange={(e) => set({ name: e.target.value })} /></Field></div>
          <div className="sm:col-span-2"><Field label={t("sourcing.item.description")} htmlFor="it-desc"><Textarea id="it-desc" dir="auto" rows={2} value={form.description ?? ""} onChange={(e) => set({ description: e.target.value || null })} /></Field></div>
          <Field label={t("sourcing.item.quantity")} htmlFor="it-qty"><Input id="it-qty" dir="ltr" inputMode="decimal" value={form.quantity ?? ""} onChange={(e) => set({ quantity: e.target.value || null })} /></Field>
          <Field label={t("sourcing.item.unit")} htmlFor="it-unit"><UnitInput id="it-unit" code={form.unit_code} text={form.unit_text} onChange={set} /></Field>
          <Field label={t("sourcing.item.targetPrice")} htmlFor="it-price">
            <div className="flex gap-1.5"><Input id="it-price" dir="ltr" inputMode="decimal" value={form.target_price ?? ""} onChange={(e) => set({ target_price: e.target.value || null })} />
              <CurrencySelect value={form.target_currency} onChange={(v) => set({ target_currency: v })} /></div>
          </Field>
          <Field label={t("sourcing.item.destination")} htmlFor="it-dest"><CountrySelect id="it-dest" emptyLabel="—" value={form.destination_country_iso2 ?? ""} onChange={(v) => set({ destination_country_iso2: v || null })} /></Field>
          <Field label={t("sourcing.incoterm")} htmlFor="it-inco">
            <div className="flex gap-1.5"><IncotermSelect id="it-inco" value={form.incoterm} onChange={(v) => set({ incoterm: v })} />
              <Input dir="auto" aria-label={t("sourcing.incotermPlace")} placeholder={t("sourcing.incotermPlace")} value={form.incoterm_place ?? ""} onChange={(e) => set({ incoterm_place: e.target.value || null })} /></div>
          </Field>
          <Field label={t("sourcing.item.requiredBy")} htmlFor="it-due"><DateInput id="it-due" value={form.required_by ? fromDateString(form.required_by) : null} onChange={(d) => set({ required_by: d ? toDateString(d) : null })} /></Field>
          <Field label={t("sourcing.item.packaging")} htmlFor="it-pack"><Input id="it-pack" dir="auto" value={form.packaging ?? ""} onChange={(e) => set({ packaging: e.target.value || null })} /></Field>
          <Field label={t("sourcing.item.hsCode")} htmlFor="it-hs"><Input id="it-hs" dir="ltr" inputMode="numeric" value={form.hs_code ?? ""} onChange={(e) => set({ hs_code: e.target.value.replace(/[^\d]/g, "") || null })} /></Field>
          <Field label={t("sourcing.item.route")} htmlFor="it-route">
            <Select id="it-route" value={form.route} onChange={(e) => set({ route: e.target.value as ItemForm["route"] })}>
              {(["unknown", "domestic", "foreign", "both"] as const).map((r) => <option key={r} value={r}>{t(`sourcing.item.routes.${r}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("sourcing.item.product")} htmlFor="it-product"><ProductPicker id="it-product" value={form.product_id} onChange={(id) => set({ product_id: id })} /></Field>
          <div className="sm:col-span-2"><Field label={t("sourcing.item.specs")}><SpecsEditor specs={form.specs} onChange={(specs) => set({ specs })} /></Field></div>
          <div className="sm:col-span-2"><Field label={t("parties.notes")} htmlFor="it-notes"><Textarea id="it-notes" dir="auto" rows={2} value={form.notes ?? ""} onChange={(e) => set({ notes: e.target.value || null })} /></Field></div>
          {item && (
            <div className="sm:col-span-2"><Field label={t("sourcing.item.attachments")}>
              <AttachedDocuments compact documents={item.documents ?? []} linkPath={`/api/line-items/${item.id}/documents`} onChanged={onSaved} />
            </Field></div>
          )}
          <div className="sm:col-span-2"><ErrorNote error={save.error} /></div>
        </form>
        {pdfs.length > 0 && <DocumentTextPanel documents={pdfs} onLine={copyLine} />}
      </div>
    </Modal>
  );
}

interface PreviewRow {
  row: number;
  item: Record<string, unknown> & { name?: string; quantity?: string; specs: Spec[] };
  errors: { field: string; code: string; value?: string }[];
  warnings?: { code: string }[];
  keep: boolean;
}

export function ImportDialog({ owner, onClose, onSaved }: { owner: ItemOwner; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [delimiter, setDelimiter] = useState<Delimiter>("auto");
  const [rows, setRows] = useState<string[][] | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping[]>([]);
  const [skipHeader, setSkipHeader] = useState(false);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const acceptRows = (r: string[][]) => {
    const guess = suggestMapping(r);
    setRows(r);
    setMapping(guess.mapping);
    setSkipHeader(guess.hasHeader);
    setPreview(null);
  };
  const upload = async (file: File) => {
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api<{ rows: string[][] }>("/api/line-items/import/upload", { method: "POST", form });
      acceptRows(res.rows);
    } catch (err) { setError(err); }
  };
  const runPreview = useMutation({
    mutationFn: () => api<{ rows: Omit<PreviewRow, "keep">[] }>("/api/line-items/import/preview", {
      method: "POST", body: { rows, mapping, skip_header: skipHeader, ...owner },
    }),
    onSuccess: (res) => setPreview(res.rows.map((r) => ({ ...r, keep: r.errors.length === 0 }))),
  });
  const save = useMutation({
    mutationFn: () => api("/api/line-items/bulk", {
      method: "POST", body: { ...owner, items: preview!.filter((r) => r.keep).map((r) => r.item) },
    }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  const width = rows ? Math.max(...rows.map((r) => r.length)) : 0;
  const fieldOf = (column: number) => mapping.find((m) => m.column === column);
  const editItem = (i: number, patch: Partial<PreviewRow["item"]>) =>
    setPreview((p) => p!.map((r, j) => (i === j ? { ...r, item: { ...r.item, ...patch }, errors: r.errors.filter((e) => !(e.field in patch)) } : r)));

  return (
    <Modal open wide title={t("sourcing.import.title")} onClose={onClose}
      footer={<>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        {rows && <Button busy={runPreview.isPending} disabled={!mapping.some((m) => m.field === "name")} onClick={() => runPreview.mutate()}>{t("sourcing.import.preview")}</Button>}
        {preview && <Button variant="primary" busy={save.isPending} disabled={!preview.some((r) => r.keep && r.item.name)} onClick={() => save.mutate()}>
          {t("sourcing.import.save", { count: preview.filter((r) => r.keep).length })}</Button>}
      </>}>
      <div className="flex max-h-[65vh] flex-col gap-3 overflow-y-auto pe-1">
        {!rows && (
          <>
            <Field label={t("sourcing.import.paste")} htmlFor="imp-text" hint={t("sourcing.import.pasteHint")}>
              <Textarea id="imp-text" dir="auto" rows={8} value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <Select className="w-44" aria-label={t("sourcing.import.delimiter")} value={delimiter} onChange={(e) => setDelimiter(e.target.value as Delimiter)}>
                {(["auto", "tab", "comma", "semicolon", "lines"] as const).map((d) => <option key={d} value={d}>{t(`sourcing.import.delimiters.${d}`)}</option>)}
              </Select>
              <Button disabled={!text.trim()} onClick={() => acceptRows(parsePasted(text, delimiter))}>{t("sourcing.import.next")}</Button>
              <span className="text-sm text-muted">{t("sourcing.import.or")}</span>
              <label className="inline-flex h-8 cursor-pointer items-center rounded-md border border-line-strong px-3 text-sm hover:bg-surface-2">
                {t("sourcing.import.upload")}
                <input type="file" hidden accept=".xlsx,.csv,.txt" onChange={(e) => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ""; }} />
              </label>
            </div>
          </>
        )}
        {rows && (
          <>
            <div className="flex items-center gap-3">
              <Checkbox label={t("sourcing.import.skipHeader")} checked={skipHeader} onChange={(v) => { setSkipHeader(v); setPreview(null); }} />
              <button type="button" className="ms-auto text-xs text-accent hover:underline" onClick={() => { setRows(null); setPreview(null); }}>{t("sourcing.import.back")}</button>
            </div>
            <div className="shrink-0 overflow-x-auto rounded-md border border-line">
              <table className="w-full text-sm">
                <thead className="bg-surface-2">
                  <tr>
                    {Array.from({ length: width }, (_, c) => (
                      <th key={c} className="p-1.5 text-start align-top">
                        <Select className="w-36" aria-label={t("sourcing.import.columnField", { n: c + 1 })} value={fieldOf(c)?.field ?? ""}
                          onChange={(e) => { setMapping(setColumnField(mapping, c, e.target.value as ImportField | "", rows[0][c])); setPreview(null); }}>
                          <option value="">{t("sourcing.import.ignore")}</option>
                          {IMPORT_FIELDS.map((fld) => <option key={fld} value={fld}>{t(`sourcing.import.fields.${fld}`)}</option>)}
                        </Select>
                        {fieldOf(c)?.field === "spec" && (
                          <Input className="mt-1 w-36" dir="auto" aria-label={t("sourcing.item.specKey")} placeholder={t("sourcing.item.specKey")} value={fieldOf(c)?.spec_key ?? ""}
                            onChange={(e) => setMapping(setColumnField(mapping, c, "spec", e.target.value))} />
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 8).map((r, i) => (
                    <tr key={i} className={`border-t border-line ${i === 0 && skipHeader ? "text-muted line-through" : ""}`}>
                      {Array.from({ length: width }, (_, c) => <td key={c} className="max-w-48 truncate p-1.5" dir="auto">{r[c] ?? ""}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length > 8 && <p className="text-xs text-muted">{t("sourcing.import.moreRows", { count: rows.length - 8 })}</p>}
          </>
        )}
        {preview && (
          <div className="shrink-0 rounded-md border border-line">
            <p className="border-b border-line bg-surface-2 px-3 py-1.5 text-xs text-muted">{t("sourcing.import.previewHint")}</p>
            <ul className="divide-y divide-line">
              {preview.map((r, i) => (
                <li key={r.row} className={`flex flex-wrap items-center gap-2 px-3 py-1.5 text-sm ${r.errors.length ? "bg-danger-soft" : ""}`}>
                  <Checkbox label={<span className="tabular-nums text-muted">#{r.row}</span>} checked={r.keep} onChange={(v) => setPreview((p) => p!.map((x, j) => (i === j ? { ...x, keep: v } : x)))} />
                  <Input className="min-w-40 flex-1" dir="auto" aria-label={t("sourcing.item.name")} value={r.item.name ?? ""} onChange={(e) => editItem(i, { name: e.target.value })} />
                  <Input className="w-24" dir="ltr" aria-label={t("sourcing.item.quantity")} value={r.item.quantity ?? ""} onChange={(e) => editItem(i, { quantity: e.target.value || undefined })} />
                  <span className="text-xs text-muted"><Bdi>{String(r.item.unit_code ?? r.item.unit_text ?? "")}</Bdi></span>
                  {r.errors.map((e, k) => <Badge key={k} tone="danger">{t(`sourcing.import.errors.${e.code}`)}{e.value ? `: ${e.value}` : ""}</Badge>)}
                  {r.warnings?.map((_, k) => <Badge key={`w${k}`} tone="warning">{t("sourcing.item.duplicateName")}</Badge>)}
                </li>
              ))}
            </ul>
          </div>
        )}
        <ErrorNote error={error || runPreview.error || save.error} />
      </div>
    </Modal>
  );
}

/** Items table with add / import / edit / delete / cancel / no-coverage actions. */
export function ItemsCard({ owner, items, warnings, ownerDocuments, onChanged, inCase, title }: {
  owner: ItemOwner;
  items: LineItem[];
  warnings: ItemWarning[];
  ownerDocuments: LinkedDocument[];
  onChanged: () => void;
  inCase?: boolean;
  title?: string;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const unitLabel = useUnitLabel();
  const [editing, setEditing] = useState<LineItem | "new" | null>(null);
  const [importing, setImporting] = useState(false);
  const [action, setAction] = useState<{ item: LineItem; kind: "cancel" | "no_coverage" } | null>(null);
  const [reason, setReason] = useState("");
  const extractor = useQuery({ queryKey: ["sourcing", "extractor"], queryFn: () => api<{ configured: boolean }>("/api/line-items/extractor"), staleTime: Infinity });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/line-items/${id}`, { method: "DELETE" }), onSuccess: onChanged });
  const act = useMutation({
    mutationFn: () => api(`/api/line-items/${action!.item.id}/${action!.kind === "cancel" ? "cancel" : "no-coverage"}`, { method: "POST", body: { reason } }),
    onSuccess: () => { setAction(null); setReason(""); onChanged(); },
  });
  const clearNoCoverage = useMutation({ mutationFn: (id: string) => api(`/api/line-items/${id}/no-coverage`, { method: "DELETE" }), onSuccess: onChanged });
  const dup = new Set(warnings.map((w) => w.item_id));
  const openItem = async (item: LineItem) => setEditing(await api<LineItem>(`/api/line-items/${item.id}`));

  return (
    <Card padded={false} title={title ?? t("sourcing.items")} actions={<>
      <Button disabled={!extractor.data?.configured} title={t("sourcing.import.aiDisabled")}>{t("sourcing.import.ai")}</Button>
      <Button icon="upload" onClick={() => setImporting(true)}>{t("sourcing.import.button")}</Button>
      <Button variant="primary" icon="plus" onClick={() => setEditing("new")}>{t("sourcing.item.add")}</Button>
    </>}>
      {items.length === 0 ? <EmptyState>{t("sourcing.noItems")}</EmptyState> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line bg-surface-2 text-xs text-muted">
              <th className="w-10 p-2 text-start">#</th>
              <th className="p-2 text-start">{t("sourcing.item.name")}</th>
              <th className="p-2 text-start">{t("sourcing.item.quantity")}</th>
              <th className="p-2 text-start">{t("sourcing.item.hsCode")}</th>
              <th className="p-2 text-start">{t("sourcing.status.label")}</th>
              <th className="p-2" />
            </tr></thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} id={`item-${item.id}`} className={`border-b border-line align-top ${item.status === "cancelled" ? "opacity-60" : ""}`}>
                  <td className="p-2 tabular-nums text-muted">{f.num(item.position)}</td>
                  <td className="p-2">
                    <button type="button" className="text-start font-medium text-accent hover:underline" onClick={() => void openItem(item)}><Bdi>{item.name}</Bdi></button>
                    {dup.has(item.id) && <span className="ms-2"><Badge tone="warning">{t("sourcing.item.duplicateName")}</Badge></span>}
                    {item.specs.length > 0 && (
                      <div className="mt-0.5 text-xs text-muted" dir="auto">{item.specs.slice(0, 4).map((s) => `${s.key}: ${s.value}${s.unit ? ` ${s.unit}` : ""}`).join(" · ")}</div>
                    )}
                  </td>
                  <td className="p-2 whitespace-nowrap tabular-nums"><Bdi>{item.quantity ? `${f.num(item.quantity)} ${unitLabel(item.unit_code, item.unit_text)}` : ""}</Bdi></td>
                  <td className="p-2"><Bdi ltr className="font-mono text-xs">{item.hs_code ?? ""}</Bdi></td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1">
                      <StatusBadge group="item" status={item.status} />
                      {item.no_coverage_confirmed && <Badge tone="danger">{t("sourcing.noCoverage")}</Badge>}
                    </div>
                    {item.no_coverage_reason && <div className="mt-0.5 text-xs text-muted" dir="auto">{item.no_coverage_reason}</div>}
                  </td>
                  <td className="p-2">
                    <div className="flex flex-wrap justify-end gap-1">
                      {inCase && item.status !== "cancelled" && (item.no_coverage_confirmed
                        ? <Button variant="ghost" onClick={() => clearNoCoverage.mutate(item.id)}>{t("sourcing.clearNoCoverage")}</Button>
                        : <Button variant="ghost" onClick={() => setAction({ item, kind: "no_coverage" })}>{t("sourcing.markNoCoverage")}</Button>)}
                      {item.status !== "cancelled" && <Button variant="ghost" onClick={() => setAction({ item, kind: "cancel" })}>{t("sourcing.item.cancel")}</Button>}
                      <Button variant="ghost" onClick={() => remove.mutate(item.id)}>{t("delete.button")}</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {remove.error ? <p className="px-4 py-2 text-sm text-danger">{errorMessage(t, remove.error)}{remove.error && (remove.error as { code?: string }).code === "in_use" ? ` ${t("sourcing.item.cancelInstead")}` : ""}</p> : null}
      {editing && <ItemDialog owner={owner} item={editing === "new" ? null : editing} ownerDocuments={ownerDocuments} onClose={() => setEditing(null)} onSaved={onChanged} />}
      {importing && <ImportDialog owner={owner} onClose={() => setImporting(false)} onSaved={onChanged} />}
      {action && (
        <Modal open title={action.kind === "cancel" ? t("sourcing.item.cancel") : t("sourcing.markNoCoverage")} onClose={() => setAction(null)}
          footer={<><Button onClick={() => setAction(null)}>{t("common.cancel")}</Button>
            <Button variant="primary" disabled={!reason.trim()} busy={act.isPending} onClick={() => act.mutate()}>{t("common.save")}</Button></>}>
          <Field label={t("sourcing.reason")} htmlFor="item-reason"><Input id="item-reason" dir="auto" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <p className="mt-2 text-sm" dir="auto">{action.item.name}</p>
          <ErrorNote error={act.error} />
        </Modal>
      )}
    </Card>
  );
}
