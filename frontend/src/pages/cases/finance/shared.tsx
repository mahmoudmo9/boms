/** Shared parts of the case «مالی» tab (v0.8.0): the case's finance data and a mutation runner that refreshes it. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../../lib/api";
import type { CaseFinance } from "../../../lib/finance";

export type Body = Record<string, unknown>;

export function useFinance(caseId: string) {
  return useQuery({ queryKey: ["finance", caseId], queryFn: () => api<CaseFinance>(`/api/cases/${caseId}/finance`) });
}

export function useFinanceRun(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, body, method = "POST" }: { path: string; body?: Body; method?: "POST" | "PATCH" | "DELETE" }) =>
      api<unknown>(path, { method, body }),
    onSuccess: () => {
      for (const key of [["finance", caseId], ["execution", caseId], ["case", caseId], ["close-checklist", caseId], ["case-tasks"], ["ratings", caseId], ["tasks"], ["command-center"]]) {
        void qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}
