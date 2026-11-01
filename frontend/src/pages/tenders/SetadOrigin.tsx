/** "From Setad «number»" on an inquiry or case (v0.5.0), with the deadline-change banner: a later fetch moved the
 * deadline on Setad; "Apply" moves the inquiry's response deadline and the follow-ups planned around it. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Button, ErrorNote } from "../../components/ui";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";

export interface SetadOriginInfo {
  listing_id: string;
  number: string;
  url: string | null;
  source?: string;
  deadline_change: { old: string | null; new: string } | null;
}

export function SetadOrigin({ inquiryId }: { inquiryId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const queryClient = useQueryClient();
  const origin = useQuery({
    queryKey: ["setad-origin", inquiryId],
    queryFn: () => api<SetadOriginInfo | null>(`/api/listings/by-inquiry/${inquiryId}`),
  });
  const apply = useMutation({
    mutationFn: () => api<{ followups_moved: unknown[] }>(`/api/listings/by-inquiry/${inquiryId}/apply-deadline`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["setad-origin", inquiryId] });
      void queryClient.invalidateQueries({ queryKey: ["inquiry", inquiryId] });
      void queryClient.invalidateQueries({ queryKey: ["case"] });
    },
  });
  const o = origin.data;
  if (!o) return null;
  const change = o.deadline_change;
  return (
    <div className="flex flex-col gap-2" data-testid="setad-origin">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs text-accent">{t("setad.fromSetad", { number: `\u2068${o.number}\u2069` })}</span>
        <Link className="text-accent hover:underline" to={`/tenders?${o.source ? `source=${o.source}&` : ""}include_old=1&listing=${o.listing_id}`}>{t("setad.openListing")}</Link>
        {o.url && <a className="text-accent hover:underline" href={o.url} target="_blank" rel="noreferrer">{t("setad.openOnSetad")}</a>}
      </p>
      {change && (
        <div role="alert" data-testid="deadline-changed" className="flex flex-wrap items-center gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning">
          <b>{t("setad.deadlineChanged")}</b>
          <span className="tabular-nums">{change.old ? f.date(change.old, true) : "—"} → {f.date(change.new, true)}</span>
          <Button variant="primary" busy={apply.isPending} onClick={() => apply.mutate()}>{t("setad.applyDeadline")}</Button>
        </div>
      )}
      <ErrorNote error={apply.error} />
    </div>
  );
}
