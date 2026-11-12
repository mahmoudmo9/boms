/** «بستن» (v0.8.0): the close checklist with every open obligation together, a reason per remaining problem, the
 * confirmation that open tasks / follow-ups are cancelled; once closed, «بازگشایی» with a reason and the ratings. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, Checkbox, ErrorNote, Field, Input, Select } from "../../../design/components";
import { api } from "../../../lib/api";
import { unexplained, type Checklist } from "../../../lib/finance";
import { ReasonDialog } from "../execution/shared";
import { useFinanceRun } from "./shared";

export function ChecklistView({ check, reasons, onReason }: { check: Checklist; reasons: Record<string, string>; onReason?: (code: string, v: string) => void }) {
  const { t } = useTranslation();
  if (check.problems.length === 0) return <p className="text-sm text-success" data-testid="checklist-passes">{t("finance.close.passes")}</p>;
  return (
    <ul className="flex flex-col gap-2" data-testid="checklist">
      {check.problems.map((p) => (
        <li key={p.code} className="flex flex-wrap items-center gap-2 rounded-md bg-warning-soft px-3 py-2 text-sm" data-problem={p.code}>
          <span className="min-w-56 flex-1">{t(`finance.close.problems.${p.code}`)}</span>
          {onReason && <Input className="w-72" dir="auto" aria-label={`${t("finance.reason")} — ${t(`finance.close.problems.${p.code}`)}`}
            value={reasons[p.code] ?? ""} onChange={(e) => onReason(p.code, e.target.value)} />}
        </li>))}
    </ul>
  );
}

const CRITERIA = { supplier: ["quality", "timeliness", "communication", "price"], customer: ["quality", "timeliness", "communication", "payment_behavior"] } as const;

function Ratings({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const data = useQuery({ queryKey: ["ratings", caseId], queryFn: () => api<{ rateable: { party_id: string; role: "supplier" | "customer" }[];
    ratings: { party_id: string; role: string; [k: string]: unknown }[] }>(`/api/cases/${caseId}/ratings`) });
  const [scores, setScores] = useState<Record<string, Record<string, string>>>({});
  if (!data.data) return null;
  return (
    <div className="flex flex-col gap-2" data-testid="ratings">
      <h3 className="text-sm font-medium">{t("finance.ratings.title")}</h3>
      {data.data.rateable.map((r) => {
        const key = `${r.party_id}-${r.role}`;
        const saved = data.data.ratings.find((x) => x.party_id === r.party_id && x.role === r.role);
        const value = (c: string) => scores[key]?.[c] ?? (saved?.[c] != null ? String(saved[c]) : "");
        return (
          <div key={key} className="flex flex-wrap items-end gap-2 rounded-md border border-line px-3 py-2" data-rating={r.role}>
            <Badge>{t(`finance.ratings.roles.${r.role}`)}</Badge>
            {CRITERIA[r.role].map((c) => (
              <Field key={c} label={t(`finance.ratings.criteria.${c}`)} htmlFor={`rt-${key}-${c}`}>
                <Select id={`rt-${key}-${c}`} className="w-20" value={value(c)} onChange={(e) => setScores({ ...scores, [key]: { ...scores[key], [c]: e.target.value } })}>
                  <option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select>
              </Field>))}
            <Field label={t("finance.ratings.note")} htmlFor={`rt-${key}-note`}><Input id={`rt-${key}-note`} className="w-56" dir="auto" maxLength={300}
              value={scores[key]?.note ?? (saved?.note as string) ?? ""} onChange={(e) => setScores({ ...scores, [key]: { ...scores[key], note: e.target.value } })} /></Field>
            <Button data-testid="rating-save" onClick={() => run.mutate({ path: `/api/cases/${caseId}/ratings`, body: { party_id: r.party_id, role: r.role,
              ...Object.fromEntries(CRITERIA[r.role].filter((c) => value(c)).map((c) => [c, Number(value(c))])),
              note: scores[key]?.note ?? (saved?.note as string) ?? null } })}>{t("common.save")}</Button>
            {saved && <Badge tone="success">{t("finance.ratings.saved")}</Badge>}
          </div>);
      })}
      <ErrorNote error={run.error} />
    </div>
  );
}

export function CloseCard({ caseId, closed }: { caseId: string; closed: boolean }) {
  const { t } = useTranslation();
  const run = useFinanceRun(caseId);
  const check = useQuery({ queryKey: ["close-checklist", caseId], enabled: !closed, queryFn: () => api<Checklist>(`/api/cases/${caseId}/close-checklist`) });
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const [reopening, setReopening] = useState(false);
  if (closed) {
    return (
      <Card title={t("finance.close.closedTitle")}>
        <div className="flex flex-col gap-3" data-testid="closed-card">
          <p className="text-sm text-muted">{t("finance.close.readOnly")}</p>
          <span><Button data-testid="reopen" onClick={() => setReopening(true)}>{t("finance.close.reopen")}</Button></span>
          <Ratings caseId={caseId} />
          {reopening && <ReasonDialog title={t("finance.close.reopen")} label={t("finance.reason")} busy={run.isPending} error={run.error}
            onClose={() => setReopening(false)} onSave={(reason) => void run.mutateAsync({ path: `/api/cases/${caseId}/reopen`, body: { reason } }).then(() => setReopening(false))} />}
        </div>
      </Card>);
  }
  if (!check.data) return null;
  const c = check.data;
  const missing = unexplained(c.problems, reasons);
  const open = c.to_cancel.tasks.length + c.to_cancel.followups.length;
  return (
    <Card title={<span className="flex items-center gap-2">{t("finance.close.title")}
      <Badge tone={c.passes ? "success" : "warning"}>{c.passes ? t("finance.close.ready") : t("finance.close.problemsN", { n: c.problems.length })}</Badge></span>}>
      <div className="flex flex-col gap-3" data-testid="close-card">
        <ChecklistView check={c} reasons={reasons} onReason={(code, v) => setReasons({ ...reasons, [code]: v })} />
        {c.notes.map((n, i) => <p key={i} className="text-xs text-muted">{t(`finance.close.notes.${n.code}`)}</p>)}
        {open > 0 && <Checkbox label={t("finance.close.confirmCancel", { n: open })} checked={confirm} onChange={setConfirm} />}
        <span><Button variant="primary" data-testid="close-deal" disabled={missing.length > 0 || (open > 0 && !confirm)} busy={run.isPending}
          onClick={() => run.mutate({ path: `/api/cases/${caseId}/close`, body: { reasons: Object.fromEntries(Object.entries(reasons).filter(([, v]) => v.trim())),
            confirm_cancel_open: confirm } })}>{t("finance.close.button")}</Button></span>
        <ErrorNote error={run.error} />
      </div>
    </Card>
  );
}
