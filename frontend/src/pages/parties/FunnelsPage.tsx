import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ErrorNote, Loading, PageHeader, Segmented, Select } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { FunnelBoard, FunnelCard } from "../../lib/types";
import { PartyName, stageLabel } from "./shared";

type FunnelRole = "buyer" | "supplier";

function Card({ card, role, stages }: { card: FunnelCard; role: FunnelRole; stages: string[] }) {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();
  const move = useMutation({
    mutationFn: (stage: string) => api(`/api/parties/${card.party_id}/roles/${role}/stage`, { method: "POST", body: { stage } }),
    onSuccess: () => {
      toast(t("parties.stageChanged"), "success");
      for (const key of ["funnel", "parties", "party", "command-center"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  return (
    <li className="rounded-md border border-line bg-surface p-2.5 text-sm shadow-sm">
      <PartyName fa={card.name_fa} en={card.name_en} dnc={card.do_not_contact} id={card.party_id} className="max-w-full" />
      <dl className="mt-1.5 flex flex-col gap-0.5 text-xs text-muted">
        <div className="flex gap-1"><dt>{t("funnel.lastInteraction")}:</dt><dd className="tabular-nums">{card.last_interaction_at ? f.date(card.last_interaction_at) : "—"}</dd></div>
        <div className="flex gap-1">
          <dt>{t("funnel.nextFollowup")}:</dt>
          <dd className="min-w-0 truncate">{card.next_followup ? <><span className="tabular-nums">{f.day(card.next_followup.due_on)}</span> <span dir="auto">{card.next_followup.action}</span></> : "—"}</dd>
        </div>
      </dl>
      <Select className="mt-2 h-7 text-xs" aria-label={t("funnel.moveTo")} value="" disabled={move.isPending}
        onChange={(e) => e.target.value && move.mutate(e.target.value)}>
        <option value="">{t("funnel.moveTo")}…</option>
        {stages.map((s) => <option key={s} value={s}>{stageLabel(t, role, s)}</option>)}
      </Select>
      <ErrorNote error={move.error} />
    </li>
  );
}

export function FunnelsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const [params, setParams] = useSearchParams();
  const role: FunnelRole = params.get("role") === "supplier" ? "supplier" : "buyer";
  const board = useQuery({ queryKey: ["funnel", role], queryFn: () => api<FunnelBoard>(`/api/parties/funnel/${role}`) });
  const codes = board.data?.stages.map((s) => s.code) ?? [];
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("funnel.title.board")} subtitle={t("funnel.subtitle")}
        actions={<Segmented value={role} label={t("funnel.role")} onChange={(v) => setParams({ role: v }, { replace: true })}
          options={[{ value: "buyer", label: t("parties.roles.buyer") }, { value: "supplier", label: t("parties.roles.supplier") }]} />} />
      {board.isLoading && <Loading />}
      <ErrorNote error={board.error} />
      {board.data && (
        <div className="overflow-x-auto pb-2">
          <div className="flex gap-3">
            {board.data.stages.map((stage) => (
              <section key={stage.code} aria-label={stageLabel(t, role, stage.code)}
                className={`flex w-60 shrink-0 flex-col rounded-lg border border-line ${stage.is_terminal ? "bg-surface-2" : "bg-bg"}`}>
                <header className="flex items-center justify-between border-b border-line px-3 py-2">
                  <h2 className="text-sm font-semibold">{stageLabel(t, role, stage.code)}</h2>
                  <span className="text-xs text-muted tabular-nums">{f.num(stage.cards.length)}</span>
                </header>
                <ul className="flex flex-col gap-2 p-2">
                  {stage.cards.map((card) => (
                    <Card key={card.party_id} card={card} role={role} stages={codes.filter((c) => c !== stage.code)} />
                  ))}
                  {stage.cards.length === 0 && <li className="px-1 py-3 text-center text-xs text-muted">{t("funnel.empty")}</li>}
                </ul>
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
