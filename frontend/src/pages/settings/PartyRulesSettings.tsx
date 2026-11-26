/** v0.10.1 (0.4.3) Settings › طرف‌های تجاری: the automatic role and stage rules, one switch each, the days before a
 * party turns dormant, and the one-time «بازمحاسبهٔ مراحل» — a preview of what the rules would change on the existing
 * data, changed only when the owner confirms. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Bdi, Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Switch, useToast } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import { stageLabel } from "../parties/shared";

export const PARTY_RULES = ["roles", "buyer_inquiry", "buyer_contacted", "buyer_in_conversation", "buyer_quoted", "buyer_won",
  "supplier_contacted", "supplier_responded", "supplier_in_use", "supplier_qualified", "dormant"] as const;

type Proposal = { party_id: string; party_name_fa: string | null; party_name_en: string | null; role: string; from: string | null; to: string;
  added: boolean; cause: { kind: string; code: string | null } | null };
type Recompute = { proposed: Proposal[]; count: number; applied: number; confirmed: boolean };

export function PartyRulesSettings() {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<{ values: Record<string, unknown> }>("/api/settings") });
  const values = settings.data?.values ?? {};
  const [days, setDays] = useState<string | null>(null);
  const [preview, setPreview] = useState<Recompute | null>(null);
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<{ values: Record<string, unknown> }>("/api/settings", { method: "PATCH", body }),
    onSuccess: (data) => { qc.setQueryData(["settings"], data); toast(t("common.saved"), "success"); },
  });
  const load = useMutation({ mutationFn: () => api<Recompute>("/api/parties/rules/recompute"), onSuccess: setPreview });
  const apply = useMutation({
    mutationFn: () => api<Recompute>("/api/parties/rules/recompute", { method: "POST" }),
    onSuccess: (r) => { setPreview(null); toast(t("settings.partyRules.applied", { count: r.applied }), "success"); void qc.invalidateQueries({ queryKey: ["parties"] }); },
  });
  const currentDays = days ?? String(values["parties.dormant_days"] ?? 180);
  return (
    <Card title={t("settings.partyRules.title")} subtitle={t("settings.partyRules.hint")} testId="party-rules">
      <ul className="flex flex-col">
        {PARTY_RULES.map((rule) => (
          <li key={rule} className="border-b border-line last:border-0">
            <Switch label={t(`settings.partyRules.rules.${rule}`)} checked={values[`parties.rules.${rule}`] !== false}
              onChange={(v) => patch.mutate({ [`parties.rules.${rule}`]: v })} />
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label={t("settings.partyRules.dormantDays")} htmlFor="st-dormant">
          <Input id="st-dormant" dir="ltr" type="number" min={1} max={3650} className="w-28" value={currentDays} onChange={(e) => setDays(e.target.value)} />
        </Field>
        <Button disabled={days === null} busy={patch.isPending} onClick={() => { patch.mutate({ "parties.dormant_days": Number(currentDays) }); setDays(null); }}>{t("common.save")}</Button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button icon="refresh" busy={load.isPending} onClick={() => load.mutate()} data-testid="recompute-preview">{t("settings.partyRules.recompute")}</Button>
        <span className="text-xs text-muted">{t("settings.partyRules.recomputeHint")}</span>
      </div>
      <ErrorNote error={patch.error || load.error || apply.error} />
      {preview && (
        <Modal open size="lg" title={t("settings.partyRules.recompute")} subtitle={t("settings.partyRules.preview", { count: preview.count })} onClose={() => setPreview(null)}
          footer={<><Button onClick={() => setPreview(null)}>{t("common.cancel")}</Button>
            <Button variant="primary" disabled={!preview.count} busy={apply.isPending} onClick={() => apply.mutate()} data-testid="recompute-confirm">{t("settings.partyRules.confirm")}</Button></>}>
          {preview.count === 0 ? <EmptyState>{t("settings.partyRules.noChanges")}</EmptyState> : (
            <ul className="flex max-h-96 flex-col divide-y divide-line overflow-y-auto" data-testid="recompute-list">
              {preview.proposed.map((p) => (
                <li key={`${p.party_id}-${p.role}`} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                  <Bdi className="font-medium">{(f.lang === "fa" ? p.party_name_fa || p.party_name_en : p.party_name_en || p.party_name_fa) ?? ""}</Bdi>
                  <Badge>{t(`parties.roles.${p.role}`)}</Badge>
                  {p.added && <Badge tone="accent">{t("settings.partyRules.newRole")}</Badge>}
                  <span className="text-muted">{p.from ? stageLabel(t, p.role, p.from) : "—"} ← <b className="text-fg">{stageLabel(t, p.role, p.to)}</b></span>
                  {p.cause && <span className="text-xs text-muted">{t(`party.rules.cause.${p.cause.kind}`, { code: p.cause.code ?? "" })}</span>}
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </Card>
  );
}
