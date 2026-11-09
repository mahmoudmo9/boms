/** Case tools (v0.9.0): «باز کردن پوشه» (the readable folder view, opened in Explorer on the PC that runs BOMS) and
 * «فقط محلی» (every AI task on the case runs only on local models). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { Button, Checkbox } from "./ui";

type Opened = { path: string; exists: boolean; opened: boolean };

function useOpenFolder(url: string) {
  const [shown, setShown] = useState<string | null>(null);
  const open = useMutation({ mutationFn: () => api<Opened>(url, { method: "POST" }), onSuccess: (r) => { if (!r.opened) setShown(r.path); } });
  return { open, shown, clear: () => setShown(null) };
}

export function CaseFolderButton({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const { open, shown } = useOpenFolder(`/api/cases/${caseId}/folder/open`);
  return (
    <span className="flex items-center gap-1">
      <Button icon="folder" busy={open.isPending} onClick={() => open.mutate()} data-testid="case-open-folder">{t("folder.open")}</Button>
      {shown && <span className="max-w-64 truncate text-xs text-muted" title={shown} data-testid="case-folder-path"><bdi dir="ltr">{t("folder.notWindows", { path: shown })}</bdi></span>}
    </span>
  );
}

export function DocumentFolderButton({ documentId }: { documentId: string }) {
  const { t } = useTranslation();
  const { open, shown } = useOpenFolder(`/api/documents/${documentId}/folder/open`);
  return (
    <span className="flex items-center gap-1">
      <Button variant="ghost" icon="folder" busy={open.isPending} onClick={() => open.mutate()}>{t("folder.open")}</Button>
      {shown && <span className="text-xs text-muted"><bdi dir="ltr">{shown}</bdi></span>}
    </span>
  );
}

export function CaseLocalOnly({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const privacy = useQuery({ queryKey: ["ai", "case-privacy", caseId], queryFn: () => api<{ local_only: boolean }>(`/api/ai/cases/${caseId}/privacy`) });
  const set = useMutation({
    mutationFn: (v: boolean) => api(`/api/ai/cases/${caseId}/privacy`, { method: "PUT", body: { local_only: v } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ai", "case-privacy", caseId] }),
  });
  return <Checkbox label={t("ai.caseLocalOnly")} checked={Boolean(privacy.data?.local_only)} onChange={(v) => set.mutate(v)} />;
}
