/** Settings → «هوش مصنوعی» (v0.9.0): providers with status and «Test connection», keys in Credential Manager, prices,
 * routes per task with their privacy level, the monthly cap and spending, and «چه چیزی کجا رفت». */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, Checkbox, ErrorNote, Field, Input, Loading, PageHeader, Select } from "../../components/ui";
import { api } from "../../lib/api";
import { capTone, inputDescription, type CallRow, type Provider, type Route, type Usage } from "../../lib/ai";
import { useFormat } from "../../lib/prefs";

function CapCard() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const usage = useQuery({ queryKey: ["ai", "usage"], queryFn: () => api<Usage>("/api/ai/usage") });
  const [cap, setCap] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api("/api/settings", { method: "PATCH", body: { "ai.monthly_cap_usd": Number(cap) } }),
    onSuccess: () => { setCap(null); void qc.invalidateQueries({ queryKey: ["ai"] }); },
  });
  const u = usage.data;
  if (!u) return <Loading />;
  const tone = capTone(u);
  return (
    <Card title={t("ai.settings.cap.title")}>
      <div className="flex flex-col gap-3" data-testid="ai-cap" data-percent={u.percent}>
        <div className="h-2 w-full overflow-hidden rounded bg-surface-2">
          <div className={`h-full ${tone === "danger" ? "bg-danger" : tone === "warning" ? "bg-warning" : "bg-accent"}`} style={{ width: `${Math.min(u.percent, 100)}%` }} />
        </div>
        <p className="text-sm">{t("ai.settings.cap.spent", { spent: f.num(u.spent_usd), cap: f.num(u.cap_usd), percent: f.num(u.percent) })}
          {u.warning && <Badge tone={tone}>{t("ai.settings.cap.warning", { level: u.warning })}</Badge>}</p>
        <p className="text-xs text-muted">{t("ai.settings.cap.subscription", { count: u.subscription_calls })}</p>
        {!u.api_fallback_enabled && <p className="text-xs text-warning">{t("ai.settings.cap.disabled")}</p>}
        <div className="flex items-end gap-2">
          <Field label={t("ai.settings.cap.label")} htmlFor="ai-cap-input">
            <Input id="ai-cap-input" dir="ltr" className="w-32" inputMode="decimal" value={cap ?? u.cap_usd} onChange={(e) => setCap(e.target.value)} />
          </Field>
          <Button variant="primary" disabled={cap === null || Number.isNaN(Number(cap))} busy={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
        </div>
        <ErrorNote error={save.error} />
      </div>
    </Card>
  );
}

const MODEL_HINT: Record<string, string> = { claude_subscription: "claude-opus-5-5", anthropic_api: "claude-opus-5-5", openai_api: "gpt-…",
  gemini_api: "gemini-…", ollama: "qwen2.5-vl", openai_compatible: "model id" };

function ProviderRow({ p, onChanged }: { p: Provider; onChanged: () => void }) {
  const { t } = useTranslation();
  const [models, setModels] = useState(p.models.join(", "));
  const [baseUrl, setBaseUrl] = useState(p.base_url ?? "");
  const [key, setKey] = useState("");
  const [prices, setPrices] = useState<Record<string, { input: string; output: string }>>({});
  const patch = useMutation({ mutationFn: (body: Record<string, unknown>) => api(`/api/ai/providers/${p.id}`, { method: "PATCH", body }), onSuccess: onChanged });
  const test = useMutation({ mutationFn: () => api<{ status: string; detail: string; latency_ms: number }>(`/api/ai/providers/${p.id}/test`, { method: "POST" }), onSuccess: onChanged });
  const saveKey = useMutation({ mutationFn: () => api(`/api/ai/providers/${p.id}/key`, { method: "PUT", body: { value: key || null } }), onSuccess: () => { setKey(""); onChanged(); } });
  const savePrice = useMutation({
    mutationFn: (model: string) => api("/api/ai/prices", { method: "PUT", body: { provider_id: p.id, model, input_per_mtok: prices[model].input, output_per_mtok: prices[model].output } }),
    onSuccess: onChanged,
  });
  const modelList = models.split(/[,\s]+/).filter(Boolean);
  return (
    <li className="flex flex-col gap-2 rounded-md border border-line p-3" data-testid="ai-provider" data-kind={p.kind}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium"><bdi>{p.label}</bdi>
          <Badge tone={p.status === "ok" ? "success" : p.status === "error" ? "danger" : "neutral"}>{t(`ai.settings.status.${p.status}`)}</Badge>
          {p.local && <Badge tone="accent">{t("ai.settings.local")}</Badge>}
          {p.last_latency_ms !== null && <span className="text-xs text-muted">{t("ai.settings.latency", { ms: p.last_latency_ms })}</span>}
        </span>
        <span className="flex items-center gap-2">
          <Checkbox label={t("ai.settings.enabled")} checked={p.enabled} onChange={(v) => patch.mutate({ enabled: v })} />
          <Button busy={test.isPending} onClick={() => test.mutate()} data-testid="ai-test">{t("ai.settings.test")}</Button>
        </span>
      </div>
      {p.status_detail && <p className="text-xs text-muted"><bdi>{p.status_detail}</bdi></p>}
      {p.kind === "claude_subscription" && p.cli && (
        <p className="text-xs text-muted" data-testid="ai-cli">{p.cli.cli ? t("ai.settings.cliFound", { version: p.cli.sdk_version ?? "" }) : t("ai.settings.cliMissing")}</p>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("ai.settings.models")} htmlFor={`models-${p.id}`}>
          <Input id={`models-${p.id}`} dir="ltr" className="w-72" value={models} onChange={(e) => setModels(e.target.value)} placeholder={MODEL_HINT[p.kind] ?? ""} />
        </Field>
        {(p.kind === "ollama" || p.kind === "openai_compatible") && (
          <Field label={t("ai.settings.baseUrl")} htmlFor={`url-${p.id}`}>
            <Input id={`url-${p.id}`} dir="ltr" className="w-64" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </Field>
        )}
        <Button onClick={() => patch.mutate({ models: modelList, ...(baseUrl ? { base_url: baseUrl } : {}) })}>{t("common.save")}</Button>
      </div>
      {p.api && (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t("ai.settings.key")} hint={p.has_key ? t("ai.settings.keySet") : t("ai.settings.keyHint")} htmlFor={`key-${p.id}`}>
              <Input id={`key-${p.id}`} type="password" dir="ltr" className="w-72" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
            </Field>
            <Button busy={saveKey.isPending} onClick={() => saveKey.mutate()}>{t("ai.settings.saveKey")}</Button>
          </div>
          <ul className="flex flex-col gap-1">{p.models.map((m) => (
            <li key={m} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="w-48 font-mono" dir="ltr">{m}</span>
              <Input dir="ltr" className="w-24" aria-label={t("ai.settings.priceIn")} placeholder={t("ai.settings.priceIn")} value={prices[m]?.input ?? ""}
                onChange={(e) => setPrices({ ...prices, [m]: { input: e.target.value, output: prices[m]?.output ?? "" } })} />
              <Input dir="ltr" className="w-24" aria-label={t("ai.settings.priceOut")} placeholder={t("ai.settings.priceOut")} value={prices[m]?.output ?? ""}
                onChange={(e) => setPrices({ ...prices, [m]: { input: prices[m]?.input ?? "", output: e.target.value } })} />
              <Button variant="ghost" disabled={!prices[m]?.input || !prices[m]?.output} onClick={() => savePrice.mutate(m)}>{t("ai.settings.savePrice")}</Button>
              {p.missing_prices.includes(m) && <Badge tone="warning">{t("ai.settings.priceMissing")}</Badge>}
            </li>))}</ul>
        </>
      )}
      <ErrorNote error={patch.error ?? test.error ?? saveKey.error ?? savePrice.error} />
    </li>
  );
}

function RoutesCard({ providers }: { providers: Provider[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const routes = useQuery({ queryKey: ["ai", "routes"], queryFn: () => api<Route[]>("/api/ai/routes") });
  const patch = useMutation({
    mutationFn: ({ task, body }: { task: string; body: Record<string, unknown> }) => api(`/api/ai/routes/${task}`, { method: "PATCH", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ai", "routes"] }),
  });
  const modelsOf = (id: string | null) => providers.find((p) => p.id === id)?.models ?? [];
  return (
    <Card title={t("ai.settings.routes.title")}>
      <ul className="flex flex-col gap-2">{(routes.data ?? []).map((r) => (
        <li key={r.task} className="flex flex-wrap items-center gap-2 text-sm" data-testid="ai-route" data-task={r.task}>
          <span className="w-40">{t(`ai.tasks.${r.task}`, { defaultValue: r.task })}</span>
          {(["primary", "fallback"] as const).map((slot) => (
            <span key={slot} className="flex items-center gap-1">
              <Select aria-label={t(`ai.settings.routes.${slot}`)} className="w-44" value={r[`${slot}_provider_id`] ?? ""}
                onChange={(e) => patch.mutate({ task: r.task, body: { [`${slot}_provider_id`]: e.target.value || null, [`${slot}_model`]: modelsOf(e.target.value)[0] ?? null } })}>
                <option value="">{t(`ai.settings.routes.${slot}`)}: —</option>
                {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </Select>
              <Select aria-label={t("ai.settings.models")} className="w-44" value={r[`${slot}_model`] ?? ""}
                onChange={(e) => patch.mutate({ task: r.task, body: { [`${slot}_model`]: e.target.value || null } })}>
                <option value="">—</option>
                {modelsOf(r[`${slot}_provider_id`]).map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </span>
          ))}
          <Select aria-label={t("ai.settings.routes.privacy")} className="w-52" value={r.privacy}
            onChange={(e) => patch.mutate({ task: r.task, body: { privacy: e.target.value } })}>
            {(["cloud", "cloud_redacted", "local_only"] as const).map((p) => <option key={p} value={p}>{t(`ai.privacy.${p}`)}</option>)}
          </Select>
        </li>))}</ul>
      <ErrorNote error={patch.error} />
    </Card>
  );
}

function PrivacyLog() {
  const { t } = useTranslation();
  const f = useFormat();
  const [task, setTask] = useState("");
  const [status, setStatus] = useState("");
  const calls = useQuery({ queryKey: ["ai", "calls", task, status], queryFn: () => api<{ total: number; items: CallRow[] }>("/api/ai/calls", { query: { task, status } }) });
  return (
    <Card title={t("ai.settings.log.title")} actions={<>
      <Select aria-label={t("ai.settings.log.task")} className="w-44" value={task} onChange={(e) => setTask(e.target.value)}>
        <option value="">{t("ai.settings.log.allTasks")}</option>
        {["extraction", "party_parse", "drafting", "classification", "ping"].map((x) => <option key={x} value={x}>{t(`ai.tasks.${x}`, { defaultValue: x })}</option>)}
      </Select>
      <Select aria-label={t("ai.settings.log.status")} className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="">{t("ai.settings.log.allStatuses")}</option>
        {["ok", "error", "invalid_output", "cap_reached", "skipped"].map((x) => <option key={x} value={x}>{x}</option>)}
      </Select></>}>
      <p className="mb-2 text-xs text-muted">{t("ai.settings.log.hint")}</p>
      <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="ai-log"><thead><tr className="border-b border-line text-muted">
        {["at", "task", "provider", "input", "redactions", "tokens", "cost", "status"].map((h) => <th key={h} className="p-1.5 text-start">{t(`ai.settings.log.${h}`)}</th>)}
      </tr></thead><tbody>{(calls.data?.items ?? []).map((c) => {
        const d = inputDescription(c.input);
        return (
          <tr key={c.id} className="border-b border-line">
            <td className="p-1.5">{f.date(c.at, true)}</td>
            <td className="p-1.5">{t(`ai.tasks.${c.task}`, { defaultValue: c.task })}</td>
            <td className="p-1.5"><bdi>{c.provider}</bdi> <span className="font-mono text-muted" dir="ltr">{c.model}</span></td>
            <td className="p-1.5">{t("ai.settings.log.inputDesc", { files: d.files, pages: d.pages, characters: f.num(d.characters), images: d.images })}</td>
            <td className="p-1.5">{Object.entries(c.redactions).map(([k, n]) => `${k}×${n}`).join(" ") || "—"}</td>
            <td className="p-1.5" dir="ltr">{c.tokens_in ?? "—"} / {c.tokens_out ?? "—"}</td>
            <td className="p-1.5">{c.subscription ? t("ai.settings.log.subscription") : c.cost_usd ? `$${f.num(c.cost_usd)}` : "—"}</td>
            <td className="p-1.5"><Badge tone={c.status === "ok" ? "success" : c.status === "skipped" ? "neutral" : "danger"}>{c.status}</Badge></td>
          </tr>);
      })}</tbody></table></div>
    </Card>
  );
}

export function AiSettingsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => api<Provider[]>("/api/ai/providers") });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["ai"] });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("ai.settings.title")} subtitle={t("ai.settings.subtitle")} />
      <CapCard />
      <Card title={t("ai.settings.providers")}>
        {providers.isLoading ? <Loading /> : (
          <ul className="flex flex-col gap-2">{(providers.data ?? []).map((p) => <ProviderRow key={p.id} p={p} onChanged={refresh} />)}</ul>
        )}
      </Card>
      <RoutesCard providers={providers.data ?? []} />
      <PrivacyLog />
    </div>
  );
}
