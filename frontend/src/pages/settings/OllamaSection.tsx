/** v0.10.1 section 0.1.3: the Ollama part of the provider card — the models installed in Ollama (``/api/tags``) to pick
 * from, each marked local or cloud; «حداکثر طول متن» and how long the model stays loaded; where the model ran after a
 * test (``/api/ps``); the install steps and the warning about ``:cloud`` models. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Checkbox, ErrorNote, Field, InlineAlert, Input, Isolated, Status } from "../../design/components";
import { api } from "../../lib/api";
import { type OllamaModel, type Placement, placementView, type Provider } from "../../lib/ai";
import { useFormat } from "../../lib/prefs";
import type { SettingsResponse } from "../../lib/types";

export function OllamaSection({ p, placement, onChanged }: { p: Provider; placement: Placement | null | undefined; onChanged: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const list = useMutation({ mutationFn: () => api<(OllamaModel & { name: string })[]>(`/api/ai/providers/${p.id}/models/refresh`, { method: "POST" }),
    onSuccess: onChanged });
  const choose = useMutation({ mutationFn: (models: string[]) => api(`/api/ai/providers/${p.id}`, { method: "PATCH", body: { models } }), onSuccess: onChanged });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const values = settings.data?.values as Record<string, unknown> | undefined;
  const [ctx, setCtx] = useState<string | null>(null);
  const [keep, setKeep] = useState<string | null>(null);
  const saveOptions = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: {
      ...(ctx !== null ? { "ai.ollama.max_context": Number(ctx) } : {}), ...(keep !== null ? { "ai.ollama.keep_alive_minutes": Number(keep) } : {}) } }),
    onSuccess: (data) => { qc.setQueryData(["settings"], data); setCtx(null); setKeep(null); },
  });
  const installed = list.data ?? Object.entries(p.model_info ?? {}).map(([name, m]) => ({ ...m, name, local: p.model_local?.[name] ?? !m.cloud }));
  const where = placementView(placement);
  const toggle = (name: string, on: boolean) => choose.mutate(on ? [...new Set([...p.models, name])] : p.models.filter((m) => m !== name));
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line bg-surface-2 p-4" data-testid="ollama-section">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-title">{t("ai.ollama.installed")}</span>
        <Button size="sm" icon="refresh" busy={list.isPending} onClick={() => list.mutate()} data-testid="ollama-list">{t("ai.ollama.readList")}</Button>
      </div>
      {installed.length === 0 ? <p className="text-xs text-muted">{t("ai.ollama.noList")}</p> : (
        <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface" data-testid="ollama-models">
          {installed.map((m) => (
            <li key={m.name} className="flex flex-wrap items-center gap-3 px-3 py-1.5">
              <Checkbox label={<bdi dir="ltr" className="font-mono text-sm">{m.name}</bdi>} checked={p.models.includes(m.name)} onChange={(v) => toggle(m.name, v)} />
              <span className="text-xs text-muted">{[m.family, m.parameter_size, m.size ? f.bytes(m.size) : null].filter(Boolean).map((x, i) => <bdi key={i} dir="ltr" className="me-2">{x}</bdi>)}</span>
              <span className="ms-auto">{m.local ? <Status tone="success">{t("ai.settings.local")}</Status> : <Status tone="warning">{t("ai.settings.cloud")}</Status>}</span>
            </li>
          ))}
        </ul>
      )}
      {p.models.some((m) => p.model_local?.[m] === false) && <InlineAlert tone="warning">{t("ai.ollama.cloudChosen")}</InlineAlert>}
      {where && (
        <p className="flex flex-wrap items-center gap-2 text-sm" data-testid="ollama-placement">
          <span className="text-muted">{t("ai.ollama.ranOn")}</span>
          <Status tone={where.fits ? "success" : "warning"}>{where.fits ? t("ai.ollama.allGpu", { n: f.num(100) }) : t("ai.ollama.split", { gpu: f.num(where.gpu), cpu: f.num(where.cpu) })}</Status>
          {!where.fits && <span className="text-xs text-muted">{t("ai.ollama.doesNotFit")}</span>}
        </p>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("ai.ollama.maxContext")} htmlFor={`ol-ctx-${p.id}`} hint={t("ai.ollama.maxContextHint")}>
          <Input id={`ol-ctx-${p.id}`} dir="ltr" inputMode="numeric" className="w-32" value={ctx ?? String(values?.["ai.ollama.max_context"] ?? "")} onChange={(e) => setCtx(e.target.value)} />
        </Field>
        <Field label={t("ai.ollama.keepAlive")} htmlFor={`ol-keep-${p.id}`}>
          <Input id={`ol-keep-${p.id}`} dir="ltr" inputMode="numeric" className="w-24" value={keep ?? String(values?.["ai.ollama.keep_alive_minutes"] ?? "")} onChange={(e) => setKeep(e.target.value)} />
        </Field>
        <Button disabled={ctx === null && keep === null} busy={saveOptions.isPending} onClick={() => saveOptions.mutate()}>{t("common.save")}</Button>
      </div>
      <details className="text-xs text-muted">
        <summary className="cursor-pointer text-sm text-fg-2">{t("ai.ollama.helpTitle")}</summary>
        <ol className="mt-2 list-decimal ps-5 leading-6">
          {(["install", "pull", "run", "list"] as const).map((k) => <li key={k}><Isolated text={t(`ai.ollama.help.${k}`)} /></li>)}
        </ol>
        <p className="mt-2"><Isolated text={t("ai.ollama.recommend")} /></p>
        <p className="mt-1 text-warning">{t("ai.ollama.cloudWarning")}</p>
      </details>
      <ErrorNote error={list.error ?? choose.error ?? saveOptions.error} />
    </div>
  );
}
