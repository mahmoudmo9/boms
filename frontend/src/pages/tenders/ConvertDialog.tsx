/** "Convert to inquiry" (v0.5.0): shows what will be created (buyer match or suggestions, items with product
 * suggestions, attachments) and converts through the server; afterwards opens the new inquiry. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { Button, Checkbox, ErrorNote, Field, Loading, Modal, Select } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useFormat } from "../../lib/prefs";

interface PartyRef { id: string; name_fa: string | null; name_en: string | null; score?: number }
interface ConvertPreview {
  number: string; title: string; kind: string; status: string; inquiry_id: string | null;
  received_at: string | null; response_due_at: string | null; deadline_exact: boolean; required_price_validity: string | null;
  delivery_province: string | null; delivery_city: string | null; buyer_note: string; buyer_contact: string; detail_fetched: boolean;
  buyer: { name: string; match: PartyRef | null; suggestions: PartyRef[] };
  items: { position: number; name: string; quantity: string; unit_text: string | null; required_by: string | null; goods_code: string | null;
    product_suggestions: { id: string; name: string | null; score: number }[] }[];
  files: { total: number; downloaded: number; missing: { id: string; name: string; state: string }[] };
}

const partyName = (p: PartyRef) => p.name_fa || p.name_en || "—";

export function ConvertDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const preview = useQuery({ queryKey: ["listing-convert", id], queryFn: () => api<ConvertPreview>(`/api/listings/${id}/convert`) });
  const [buyer, setBuyer] = useState<string>("");          // "" = the exact match, "new" = create, else a party id
  const [confirmDuplicate, setConfirmDuplicate] = useState(false);
  const [products, setProducts] = useState<Record<number, string>>({});
  const [withoutMissing, setWithoutMissing] = useState(false);
  const [queued, setQueued] = useState(false);
  const download = useMutation({
    mutationFn: () => api("/api/setad/commands", { method: "POST", body: { command: "download_files", listing_ids: [id] } }),
    onSuccess: () => setQueued(true),
  });
  const convert = useMutation({
    mutationFn: () => {
      const p = preview.data!;
      const choice = buyer || (p.buyer.match ? "" : "new");
      return api<{ inquiry_id: string }>(`/api/listings/${id}/convert`, { method: "POST", body: {
        ...(choice === "new" ? { create_party: true, confirm_duplicate: confirmDuplicate } : choice ? { party_id: choice } : {}),
        products: Object.fromEntries(Object.entries(products).filter(([, v]) => v)),
        without_missing_files: withoutMissing,
      } });
    },
    onSuccess: (out) => {
      void queryClient.invalidateQueries({ queryKey: ["listings"] });
      void queryClient.invalidateQueries({ queryKey: ["listing", id] });
      navigate(`/sourcing/inquiries/${out.inquiry_id}`);
    },
  });
  const p = preview.data;
  const duplicate = convert.error instanceof ApiError && convert.error.code === "duplicate_party"
    ? (convert.error.details.duplicates as PartyRef[]) : null;
  const missing = p ? p.files.missing.length : 0;
  const choice = p ? (buyer || (p.buyer.match ? "" : "new")) : "";
  const blocked = !p || (missing > 0 && !withoutMissing) || (choice === "new" && duplicate !== null && !confirmDuplicate);
  return (
    <Modal open wide title={t("listings.convertTitle")} onClose={onClose}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" data-testid="convert-submit" disabled={blocked} busy={convert.isPending} onClick={() => convert.mutate()}>{t("listings.convert")}</Button></>}>
      {preview.isLoading && <Loading />}
      <ErrorNote error={preview.error} />
      {p && (
        <div className="flex flex-col gap-3 text-sm" data-testid="convert-dialog">
          <p dir="auto"><b>{p.title}</b> <span className="font-mono text-xs text-muted" dir="ltr">{p.number}</span></p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted">{t("listings.convertFields.kind")}</dt><dd>{t(`sourcing.inquiry.kinds.${p.kind}`)}</dd>
            <dt className="text-muted">{t("listings.convertFields.received")}</dt><dd className="tabular-nums">{p.received_at ? f.date(p.received_at, true) : "—"}</dd>
            <dt className="text-muted">{t("listings.convertFields.deadline")}</dt>
            <dd className="tabular-nums">{p.response_due_at ? f.date(p.response_due_at, true) : "—"}{p.response_due_at && !p.deadline_exact && <span className="text-xs text-muted"> ({t("listings.estimate")})</span>}</dd>
            <dt className="text-muted">{t("listings.convertFields.validity")}</dt><dd className="tabular-nums">{p.required_price_validity ? f.day(p.required_price_validity) : "—"}</dd>
            <dt className="text-muted">{t("listings.convertFields.delivery")}</dt><dd dir="auto">{[p.delivery_province, p.delivery_city].filter(Boolean).join("، ") || "—"}</dd>
          </dl>
          {!p.detail_fetched && <p className="rounded-md bg-warning-soft px-2.5 py-1.5 text-warning">{t("listings.noDetailYet")}</p>}

          <Field label={t("listings.buyer")} htmlFor="convert-buyer">
            <Select id="convert-buyer" value={choice} onChange={(e) => { setBuyer(e.target.value); setConfirmDuplicate(false); convert.reset(); }}>
              {p.buyer.match && <option value="">{t("listings.buyerMatch", { name: partyName(p.buyer.match) })}</option>}
              {p.buyer.suggestions.map((s) => <option key={s.id} value={s.id}>{t("listings.buyerSuggestion", { name: partyName(s) })}</option>)}
              <option value="new">{t("listings.buyerNew", { name: p.buyer.name })}</option>
            </Select>
          </Field>
          {duplicate && (
            <div className="rounded-md bg-warning-soft px-2.5 py-1.5 text-warning" role="alert">
              <p>{t("listings.duplicateParty")}: {duplicate.map(partyName).join("، ")}</p>
              <Checkbox label={t("listings.createAnyway")} checked={confirmDuplicate} onChange={setConfirmDuplicate} />
            </div>
          )}
          {p.buyer_contact && <p className="text-xs text-muted" dir="auto">{t("listings.contactToNotes")}: {p.buyer_contact}</p>}

          <div>
            <p className="mb-1 font-medium">{t("listings.convertItems", { n: f.num(p.items.length) })}</p>
            <ul className="flex flex-col gap-1.5">
              {p.items.map((i) => (
                <li key={i.position} className="flex flex-wrap items-center gap-2 rounded-md border border-line px-2 py-1.5">
                  <span className="min-w-0 flex-1" dir="auto">{i.name}</span>
                  <span className="tabular-nums text-muted">{f.num(i.quantity)} {i.unit_text}</span>
                  {i.goods_code && <span className="font-mono text-xs text-muted" dir="ltr">{i.goods_code}</span>}
                  {i.product_suggestions.length > 0 && (
                    <Select aria-label={t("listings.productFor", { n: f.num(i.position) })} className="w-auto max-w-56"
                      value={products[i.position] ?? ""} onChange={(e) => setProducts({ ...products, [i.position]: e.target.value })}>
                      <option value="">{t("listings.noProduct")}</option>
                      {i.product_suggestions.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </Select>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="font-medium">{t("listings.convertFiles", { done: f.num(p.files.downloaded), total: f.num(p.files.total) })}</p>
            {missing > 0 && (
              <div className="mt-1 flex flex-col gap-1.5 rounded-md bg-warning-soft px-2.5 py-1.5 text-warning">
                <p>{t("listings.filesMissing", { n: f.num(missing) })}</p>
                <span className="flex flex-wrap items-center gap-2">
                  <Button busy={download.isPending} disabled={queued} onClick={() => download.mutate()}>{t("listings.downloadThenConvert")}</Button>
                  {queued && <span>{t("listings.downloadQueued")}</span>}
                </span>
                <Checkbox label={t("listings.convertWithout")} checked={withoutMissing} onChange={setWithoutMissing} />
              </div>
            )}
          </div>
          <ErrorNote error={duplicate ? null : convert.error || download.error} />
        </div>
      )}
    </Modal>
  );
}
