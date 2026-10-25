/** Supplier capability tags (HS chapters/headings, ISIC sections/divisions, free tags) on the party Overview. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../components/Bdi";
import { Icon } from "../../components/Icon";
import { Button, Card, ErrorNote, Input, Segmented, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { Capability, RefCode } from "../../lib/types";

/** Title in the user's language; a missing Persian title falls back to English with a small marker. */
function CodeTitle({ code }: { code: RefCode }) {
  const f = useFormat();
  const { t } = useTranslation();
  const persian = f.lang === "fa" && code.title_fa;
  return (
    <>
      <Bdi className="truncate">{persian ? code.title_fa : code.title_en}</Bdi>
      {f.lang === "fa" && !code.title_fa && <span className="shrink-0 text-xs text-muted">({t("sourcing.capabilities.untranslated")})</span>}
    </>
  );
}

function CodeLabel({ code }: { code: RefCode }) {
  return <span className="inline-flex min-w-0 max-w-full items-center gap-1"><Bdi ltr className="shrink-0 font-mono text-xs">{code.code}</Bdi> <CodeTitle code={code} /></span>;
}

function CodeBrowser({ kind, taken, onPick }: { kind: "hs" | "isic"; taken: Set<string>; onPick: (code: string) => void }) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [parent, setParent] = useState<RefCode | null>(null);
  const codes = useQuery({
    queryKey: ["capabilities", "codes", kind, q, parent?.code],
    queryFn: () => api<RefCode[]>("/api/capabilities/codes", { query: { kind, q, parent: q ? undefined : parent?.code, limit: 60 } }),
  });
  return (
    <div className="flex flex-col gap-2">
      <Input type="search" placeholder={t(`sourcing.capabilities.search_${kind}`)} value={q} onChange={(e) => setQ(e.target.value)} />
      {!q && parent && (
        <button type="button" className="inline-flex items-center gap-1 self-start text-xs text-accent hover:underline" onClick={() => setParent(null)}>
          <Icon name="chevronStart" size={12} /> {t("sourcing.capabilities.top")}
        </button>
      )}
      {!q && parent && <p className="text-sm font-medium"><CodeLabel code={parent} /></p>}
      <ul className="max-h-64 divide-y divide-line overflow-y-auto rounded-md border border-line text-sm">
        {codes.isFetching && <li className="p-2"><Spinner size={14} /></li>}
        {(codes.data ?? []).map((c) => (
          <li key={c.code} className="flex items-center gap-2 px-2.5 py-1.5">
            <span className="min-w-0 flex-1">
              {q && c.parent && <span className="block truncate text-xs text-muted"><CodeLabel code={c.parent} /> ›</span>}
              <CodeLabel code={c} />
            </span>
            {!q && !c.parent_code && <Button variant="ghost" onClick={() => setParent(c)}>{t("sourcing.capabilities.open")}</Button>}
            <Button icon="plus" disabled={taken.has(c.code)} onClick={() => onPick(c.code)}>{t("common.add")}</Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CapabilitiesCard({ partyId }: { partyId: string }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<"hs" | "isic" | "tag">("hs");
  const [tag, setTag] = useState("");
  const [adding, setAdding] = useState(false);
  const caps = useQuery({ queryKey: ["capabilities", partyId], queryFn: () => api<Capability[]>(`/api/capabilities/party/${partyId}`) });
  const add = useMutation({
    mutationFn: (body: Record<string, string>) => api(`/api/capabilities/party/${partyId}`, { method: "POST", body }),
    onSuccess: () => { setTag(""); void caps.refetch(); },
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/capabilities/${id}`, { method: "DELETE" }), onSuccess: () => void caps.refetch() });
  const rows = caps.data ?? [];
  const label = (c: Capability) => {
    if (c.kind === "tag") return <Bdi className="truncate">{c.tag_text}</Bdi>;
    if (!c.info || ("unknown" in c.info && c.info.unknown)) return <><Bdi ltr className="font-mono text-xs">{c.code}</Bdi> <span className="text-xs text-muted">({t("sourcing.capabilities.unknownCode")})</span></>;
    const info = c.info as RefCode;
    return <span className="inline-flex min-w-0 max-w-full items-center gap-1"><Bdi ltr className="shrink-0 font-mono text-xs">{c.kind === "isic" && info.parent_code ? `${info.parent_code}${info.code}` : info.code}</Bdi> <CodeTitle code={info} /></span>;
  };
  return (
    <Card title={t("sourcing.capabilities.title")} actions={<Button icon={adding ? "x" : "plus"} onClick={() => setAdding(!adding)}>{adding ? t("common.close") : t("common.add")}</Button>}>
      {rows.length === 0 && !adding && <p className="text-sm text-muted">{t("sourcing.capabilities.empty")}</p>}
      <div className="flex flex-col gap-2">
        {(["hs", "isic", "tag"] as const).map((k) => rows.some((c) => c.kind === k) && (
          <div key={k} className="flex flex-wrap items-center gap-1.5">
            <span className="w-14 text-xs font-medium text-muted">{t(`sourcing.capabilities.kinds.${k}`)}</span>
            {rows.filter((c) => c.kind === k).map((c) => (
              <span key={c.id} className="inline-flex max-w-full items-center gap-1 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-sm">
                <span className="inline-flex min-w-0 max-w-[28rem] items-center gap-1 overflow-hidden">{label(c)}</span>
                <button type="button" aria-label={t("common.remove")} className="text-muted hover:text-danger" onClick={() => remove.mutate(c.id)}><Icon name="x" size={12} /></button>
              </span>
            ))}
          </div>
        ))}
      </div>
      {adding && (
        <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
          <Segmented value={kind} label={t("sourcing.capabilities.kind")} onChange={setKind}
            options={(["hs", "isic", "tag"] as const).map((k) => ({ value: k, label: t(`sourcing.capabilities.kinds.${k}`) }))} />
          {kind === "tag" ? (
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (tag.trim()) add.mutate({ kind: "tag", tag_text: tag }); }}>
              <Input dir="auto" aria-label={t("sourcing.capabilities.tag")} placeholder={t("sourcing.capabilities.tagPlaceholder")} value={tag} onChange={(e) => setTag(e.target.value)} />
              <Button type="submit" icon="plus" busy={add.isPending}>{t("common.add")}</Button>
            </form>
          ) : (
            <CodeBrowser key={kind} kind={kind} taken={new Set(rows.filter((c) => c.kind === kind).map((c) => c.code ?? ""))} onPick={(code) => add.mutate({ kind, code })} />
          )}
        </div>
      )}
      <ErrorNote error={add.error || remove.error || caps.error} />
    </Card>
  );
}
