/** «تأیید سند» (v0.9.0 section 6.3): paste the QR text (or type the code and the verification code) and see the record,
 * its version and its current status — an older version shows as superseded. */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { CodeChip } from "../../components/smart";
import { Badge, Button, Card, ErrorNote, Field, Input, PageHeader, Textarea } from "../../components/ui";
import { api } from "../../lib/api";

type Result = { valid: boolean; reason?: string; kind?: string | null; code?: string; version?: number; issue_date?: string; status?: string;
  current?: { link?: string; version?: number; status?: string } };

const TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = { issued: "success", draft: "warning", superseded: "warning", void: "danger" };

export function VerifyDocumentPage() {
  const { t } = useTranslation();
  const [payload, setPayload] = useState("");
  const [code, setCode] = useState("");
  const [vc, setVc] = useState("");
  const verify = useMutation({
    mutationFn: () => api<Result>("/api/verify-document", { method: "POST", body: payload.trim() ? { text: payload.trim() } : { code, verification_code: vc } }),
  });
  const r = verify.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("verify.title")} subtitle={t("verify.subtitle")} />
      <Card>
        <div className="flex flex-col gap-3">
          <Field label={t("verify.payload")} htmlFor="verify-payload" hint={t("verify.payloadHint")}>
            <Textarea id="verify-payload" dir="ltr" value={payload} onChange={(e) => setPayload(e.target.value)} placeholder="BOMS|PI-1405-0005|v2|2026-11-01|ABCDEFGHIJ" />
          </Field>
          <p className="text-xs text-muted">{t("verify.or")}</p>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t("verify.code")} htmlFor="verify-code"><Input id="verify-code" dir="ltr" className="w-56" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <Field label={t("verify.vc")} htmlFor="verify-vc"><Input id="verify-vc" dir="ltr" className="w-40" value={vc} onChange={(e) => setVc(e.target.value)} /></Field>
            <Button variant="primary" disabled={!payload.trim() && !(code && vc)} busy={verify.isPending} onClick={() => verify.mutate()} data-testid="verify-submit">{t("verify.check")}</Button>
          </div>
          <ErrorNote error={verify.error} />
        </div>
      </Card>
      {r && (
        <Card>
          <div className="flex flex-col gap-2 text-sm" data-testid="verify-result" data-valid={r.valid} data-status={r.status ?? ""}>
            {r.valid ? (
              <>
                <p className="flex flex-wrap items-center gap-2"><Badge tone="success">{t("verify.genuine")}</Badge> <CodeChip code={r.code} />
                  <span>{t("verify.version", { v: r.version })}</span> <span dir="ltr">{r.issue_date}</span></p>
                {r.status && <p>{t("verify.currentStatus")}: <Badge tone={TONE[r.status] ?? "neutral"}>{t(`verify.status.${r.status}`, { defaultValue: r.status })}</Badge></p>}
                {r.status === "superseded" && <p className="text-xs text-warning">{t("verify.supersededHint", { v: r.current?.version })}</p>}
                {r.current?.link && <Link className="text-accent underline" to={r.current.link}>{t("verify.open")}</Link>}
              </>
            ) : (
              <p><Badge tone="danger">{t(`verify.reason.${r.reason ?? "unreadable"}`)}</Badge></p>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
