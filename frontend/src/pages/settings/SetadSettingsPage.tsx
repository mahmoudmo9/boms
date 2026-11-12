/** Settings -> Setad (v0.5.0): attachments folder, agent idle time, retention, warn keywords, dismiss reasons,
 * checklist questions, recording the site flow (diagnostics), clearing the attachments cache, purging old listings. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, ErrorNote, Field, Input, Modal, PageHeader, Textarea, useToast } from "../../design/components";
import { api } from "../../lib/api";
import { useFormat } from "../../lib/prefs";
import type { SettingsResponse } from "../../lib/types";
import { useAgent } from "../tenders/ConnectionBar";

const LISTS = ["setad.warn_keywords", "setad.dismiss_reasons", "setad.checklist"] as const;
const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

export function SetadSettingsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();
  const agent = useAgent();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const [values, setValues] = useState<Record<string, string> | null>(null);
  const [purging, setPurging] = useState(false);
  useEffect(() => {
    if (settings.data) {
      const v = settings.data.values as Record<string, unknown>;
      setValues({
        "setad.files_dir": (v["setad.files_dir"] as string | null) ?? "",
        "setad.agent_idle_minutes": String(v["setad.agent_idle_minutes"] ?? 60),
        "setad.retention_days": String(v["setad.retention_days"] ?? 180),
        ...Object.fromEntries(LISTS.map((k) => [k, ((v[k] as string[] | null) ?? []).join("\n")])),
      });
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: {
      "setad.files_dir": values!["setad.files_dir"].trim() || null,
      "setad.agent_idle_minutes": Number(values!["setad.agent_idle_minutes"]),
      "setad.retention_days": Number(values!["setad.retention_days"]),
      ...Object.fromEntries(LISTS.map((k) => [k, lines(values![k])])),
    } }),
    onSuccess: (data) => { queryClient.setQueryData(["settings"], data); toast(t("common.saved"), "success"); },
  });
  const record = useMutation({
    mutationFn: async (on: boolean) => {
      if (!agent.data?.alive) await api("/api/setad/agent/start", { method: "POST" });
      return api("/api/setad/commands", { method: "POST", body: { command: on ? "record_start" : "record_stop" } });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["setad-agent"] }),
  });
  const clear = useMutation({
    mutationFn: () => api<{ files: number }>("/api/setad/cache/clear", { method: "POST" }),
    onSuccess: (r) => toast(t("setadSettings.cleared", { n: f.num(r.files ?? 0) }), "success"),
  });
  const preview = useQuery({ queryKey: ["setad-retention"], queryFn: () => api<{ listings: number; retention_days: number }>("/api/setad/retention"), enabled: purging });
  const purge = useMutation({
    mutationFn: () => api<{ listings: number }>("/api/setad/retention/purge", { method: "POST" }),
    onSuccess: (r) => { setPurging(false); toast(t("setadSettings.purged", { n: f.num(r.listings ?? 0) }), "success"); void queryClient.invalidateQueries({ queryKey: ["listings"] }); },
  });
  if (!values) return null;
  const set = (key: string) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <PageHeader title={t("nav.sub.setad")} subtitle={t("setadSettings.subtitle")} />
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }} className="flex flex-col gap-4">
        <Card title={t("setadSettings.agent")}>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t("setadSettings.filesDir")} htmlFor="sd-files" hint={t("setadSettings.filesDirHint")}>
              <Input id="sd-files" dir="ltr" value={values["setad.files_dir"]} onChange={set("setad.files_dir")} placeholder="D:\\Setad" />
            </Field>
            <Field label={t("setadSettings.idleMinutes")} htmlFor="sd-idle">
              <Input id="sd-idle" type="number" min={5} max={1440} dir="ltr" value={values["setad.agent_idle_minutes"]} onChange={set("setad.agent_idle_minutes")} />
            </Field>
            <Field label={t("setadSettings.retentionDays")} htmlFor="sd-ret" hint={t("setadSettings.retentionHint")}>
              <Input id="sd-ret" type="number" min={30} max={3650} dir="ltr" value={values["setad.retention_days"]} onChange={set("setad.retention_days")} />
            </Field>
          </div>
        </Card>
        <Card title={t("setadSettings.screening")}>
          <div className="grid gap-3 sm:grid-cols-3">
            {LISTS.map((key) => (
              <Field key={key} label={t(`setadSettings.lists.${key.split(".")[1]}`)} htmlFor={`sd-${key}`} hint={t("setadSettings.onePerLine")}>
                <Textarea id={`sd-${key}`} dir="auto" rows={7} value={values[key]} onChange={set(key)} />
              </Field>
            ))}
          </div>
        </Card>
        <ErrorNote error={save.error} />
        <div><Button type="submit" variant="primary" busy={save.isPending}>{t("common.save")}</Button></div>
      </form>
      <Card title={t("setadSettings.maintenance")}>
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Button busy={record.isPending} onClick={() => record.mutate(!agent.data?.recording)}>
              {agent.data?.recording ? t("setadSettings.recordStop") : t("setadSettings.recordStart")}</Button>
            <span className="text-xs text-muted">{t("setadSettings.recordHint")}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button busy={clear.isPending} onClick={() => clear.mutate()}>{t("setadSettings.clearCache")}</Button>
            <span className="text-xs text-muted">{t("setadSettings.clearCacheHint")}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="danger" onClick={() => setPurging(true)}>{t("setadSettings.purge")}</Button>
            <span className="text-xs text-muted">{t("setadSettings.purgeHint")}</span>
          </div>
          <ErrorNote error={record.error || clear.error} />
        </div>
      </Card>
      {purging && (
        <Modal open title={t("setadSettings.purge")} onClose={() => setPurging(false)}
          footer={<><Button onClick={() => setPurging(false)}>{t("common.cancel")}</Button>
            <Button variant="danger" busy={purge.isPending} disabled={!preview.data?.listings} onClick={() => purge.mutate()}>{t("setadSettings.purge")}</Button></>}>
          {preview.data && <p className="text-sm" data-testid="purge-count">{t("setadSettings.purgeCount", { n: f.num(preview.data.listings), days: f.num(preview.data.retention_days) })}</p>}
          <ErrorNote error={preview.error || purge.error} />
        </Modal>
      )}
    </div>
  );
}
