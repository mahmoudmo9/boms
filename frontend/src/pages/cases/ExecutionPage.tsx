/** Workspace «اجرا و حمل» (v0.7.0): the execution items that need attention across all cases (the command center's
 * «اجرا» section on its own page). The work itself is done on each case's Order / Purchase / Logistics / Delivery tabs. */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ErrorNote, Loading, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { CommandCenter } from "../../lib/types";
import { ExecutionSection } from "../parties/CommandCenterPage";

export function ExecutionPage() {
  const { t } = useTranslation();
  const cc = useQuery({ queryKey: ["command-center"], queryFn: () => api<CommandCenter>("/api/command-center", { background: true }), refetchInterval: 60_000 });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("nav.execution")} subtitle={t("execution.page.subtitle")} />
      {cc.isLoading && <Loading />}
      <ErrorNote error={cc.error} />
      {cc.data?.execution && <ExecutionSection s={cc.data.execution} />}
    </div>
  );
}
