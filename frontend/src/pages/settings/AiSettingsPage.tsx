/** Settings → «هوش مصنوعی» (v0.9.0): providers with status and «Test connection», keys in Credential Manager, prices,
 * routes per task with their privacy level, the monthly cap and spending, and «چه چیزی کجا رفت». */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button, Card, Checkbox, EmptyState, ErrorNote, ErrorState, Field, Input, Loading, PageGrid, PageHeader, ProgressRing, Select, Stat, Status } from "../../design/components";
import { api } from "../../lib/api";
import { capTone, inputDescription, signInView, type CallRow, type ClaudeStatus, type Provider, type Route, type Usage } from "../../lib/ai";
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
    <Card title={t("ai.settings.cap.title")} kind="accent">
      <div className="flex flex-col gap-4" data-testid="ai-cap" data-percent={u.percent}>
        <div className="flex items-center gap-4">
          <ProgressRing value={u.percent} size={88} label={t("ai.settings.cap.title")} tone={tone === "danger" ? "danger" : tone === "warning" ? "warning" : "accent"}>
            <span className="text-sm font-semibold tabular-nums text-title">{f.num(Math.round(u.percent))}٪</span>
          </ProgressRing>
          <div className="grid min-w-0 flex-1 grid-cols-2 gap-3">
            <Stat label={t("ai.settings.cap.spentLabel")} value={<bdi dir="ltr">${f.num(u.spent_usd)}</bdi>} tone={tone === "neutral" ? undefined : tone} />
            <Stat label={t("ai.settings.cap.capLabel")} value={<bdi dir="ltr">${f.num(u.cap_usd)}</bdi>} />
          </div>
        </div>
        <p className="text-sm">{t("ai.settings.cap.spent", { spent: f.num(u.spent_usd), cap: f.num(u.cap_usd), percent: f.num(u.percent) })}
          {u.warning && <> <Status tone={tone}>{t("ai.settings.cap.warning", { level: u.warning })}</Status></>}</p>
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

/** v0.10.0 section 0.1.2: the Claude sign-in block. «ورود به Claude» opens a visible console on the PC that runs the
 * bundled CLI's sign-in and stays open; the status check and every AI call run the CLI with no window. */
function ClaudeSignIn({ onChanged }: { onChanged: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["ai", "claude"], queryFn: () => api<ClaudeStatus>("/api/ai/claude/status", { background: true }),
    refetchInterval: (q) => (q.state.data && !q.state.data.logged_in && q.state.data.cli ? 5000 : false) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["ai", "claude"] }); onChanged(); };
  const login = useMutation({ mutationFn: () => api("/api/ai/claude/login", { method: "POST" }), onSuccess: refresh });
  const logout = useMutation({ mutationFn: () => api("/api/ai/claude/logout", { method: "POST" }), onSuccess: refresh });
  const s = status.data;
  if (!s) return <Loading />;
  const view = signInView(s);
  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-line bg-surface-2 p-4 text-sm" data-testid="claude-signin" data-state={s.state}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-2">
          <Status tone={view.tone}>{t(`ai.settings.claude.state.${s.state}`)}</Status>
          {s.email && <bdi className="text-xs text-muted">{s.email}</bdi>}
        </span>
        <span className="flex items-center gap-2">
          {view.canLogin && <Button variant="primary" busy={login.isPending} onClick={() => login.mutate()} data-testid="claude-login">{t("ai.settings.claude.login")}</Button>}
          {view.canLogout && <Button busy={logout.isPending} onClick={() => logout.mutate()} data-testid="claude-logout">{t("ai.settings.claude.logout")}</Button>}
        </span>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">{t("ai.settings.claude.account")}</dt><dd data-testid="claude-account"><bdi>{s.account}</bdi></dd>
        <dt className="text-muted">{t("ai.settings.claude.storedIn")}</dt><dd className="[overflow-wrap:anywhere]"><bdi dir="ltr">{s.config_dir}</bdi></dd>
      </dl>
      {view.otherAccounts.length > 0 && (
        <p className="rounded-lg border border-warning bg-warning-soft p-2.5 text-xs" data-testid="claude-other-account">
          {t("ai.settings.claude.otherAccount", { others: view.otherAccounts.join("، "), account: s.account })}
        </p>
      )}
      {(s.state === "no_cli" || s.state === "no_sdk") && <p className="text-xs text-danger">{t("ai.settings.claude.missing")}</p>}
      {view.showSteps && (
        <ol className="list-decimal ps-5 text-xs leading-6 text-muted" data-testid="claude-steps">
          {(["open", "choose", "authorise", "paste", "close"] as const).map((k) => <li key={k}>{t(`ai.settings.claude.steps.${k}`)}</li>)}
        </ol>
      )}
      {view.showSteps && !s.can_open_console && <p className="text-xs text-warning">{t("ai.settings.claude.notOnThisPc")}</p>}
      {login.isSuccess && !s.logged_in && <p className="text-xs text-accent" data-testid="claude-opened">{t("ai.settings.claude.opened")}</p>}
      <p className="text-xs text-muted">{t("ai.settings.claude.help")}</p>
      <ErrorNote error={login.error ?? logout.error} />
    </div>
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
    <li className={`flex flex-col gap-3 rounded-2xl border bg-surface p-4 shadow-sm ${p.enabled ? "border-line" : "border-dashed border-line-strong"}`} data-testid="ai-provider" data-kind={p.kind}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-2"><bdi className="text-base font-semibold text-title">{p.label}</bdi>
          <Status tone={p.status === "ok" ? "success" : p.status === "error" ? "danger" : "neutral"}>{t(`ai.settings.status.${p.status}`)}</Status>
          {p.local ? <Badge tone="accent">{t("ai.settings.local")}</Badge> : <Badge>{t("ai.settings.cloud")}</Badge>}
          {p.last_latency_ms !== null && <span className="text-xs text-muted">{t("ai.settings.latency", { ms: p.last_latency_ms })}</span>}
        </span>
        <span className="flex items-center gap-2">
          <Checkbox label={t("ai.settings.enabled")} checked={p.enabled} onChange={(v) => patch.mutate({ enabled: v })} />
          <Button busy={test.isPending} onClick={() => test.mutate()} data-testid="ai-test">{t("ai.settings.test")}</Button>
        </span>
      </div>
      {p.status_detail && <p className="text-xs text-muted"><bdi>{p.status_detail}</bdi></p>}
      {p.kind === "claude_subscription" && <ClaudeSignIn onChanged={onChanged} />}
      {(p.kind === "ollama" || p.kind === "openai_compatible") && !p.local && (
        <p className="text-xs text-warning" data-testid="ai-cloud-note">{t("ai.settings.cloudNote")}</p>
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
      <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full text-sm">
        <thead className="bg-surface-2 text-xs text-muted"><tr>{(["task", "primary", "fallback", "privacy"] as const).map((h) =>
          <th key={h} scope="col" className="h-10 border-b border-line px-3.5 text-start font-medium whitespace-nowrap">{t(`ai.settings.routes.${h}`)}</th>)}</tr></thead>
        <tbody>{(routes.data ?? []).map((r) => (
        <tr key={r.task} className="border-b border-line last:border-b-0" data-testid="ai-route" data-task={r.task}>
          <th scope="row" className="px-3.5 py-2 text-start font-medium whitespace-nowrap">{t(`ai.tasks.${r.task}`, { defaultValue: r.task })}</th>
          {(["primary", "fallback"] as const).map((slot) => (
            <td key={slot} className="px-3.5 py-2"><span className="flex items-center gap-1">
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
            </span></td>
          ))}
          <td className="px-3.5 py-2"><Select aria-label={t("ai.settings.routes.privacy")} className="w-52" value={r.privacy}
            onChange={(e) => patch.mutate({ task: r.task, body: { privacy: e.target.value } })}>
            {(["cloud", "cloud_redacted", "local_only"] as const).map((p) => <option key={p} value={p}>{t(`ai.privacy.${p}`)}</option>)}
          </Select></td>
        </tr>))}</tbody></table></div>
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
      {calls.isLoading ? <Loading /> : !calls.data?.items.length ? <EmptyState compact icon="shield" title={t("ai.settings.log.empty")} /> : null}
      <div className={`overflow-x-auto rounded-xl border border-line ${calls.data?.items.length ? "" : "hidden"}`}><table className="w-full text-xs" data-testid="ai-log"><thead className="bg-surface-2 text-muted"><tr>
        {["at", "task", "provider", "input", "redactions", "tokens", "cost", "status"].map((h) => <th key={h} scope="col" className="h-9 border-b border-line px-3 text-start font-medium whitespace-nowrap">{t(`ai.settings.log.${h}`)}</th>)}
      </tr></thead><tbody>{(calls.data?.items ?? []).map((c) => {
        const d = inputDescription(c.input);
        return (
          <tr key={c.id} className="border-b border-line last:border-b-0 hover:bg-surface-2">
            <td className="px-3 py-2">{f.date(c.at, true)}</td>
            <td className="px-3 py-2">{t(`ai.tasks.${c.task}`, { defaultValue: c.task })}</td>
            <td className="px-3 py-2"><bdi>{c.provider}</bdi> <span className="font-mono text-muted" dir="ltr">{c.model}</span></td>
            <td className="px-3 py-2">{t("ai.settings.log.inputDesc", { files: d.files, pages: d.pages, characters: f.num(d.characters), images: d.images })}</td>
            <td className="px-3 py-2">{Object.entries(c.redactions).map(([k, n]) => `${k}×${n}`).join(" ") || "—"}</td>
            <td className="px-3 py-2" dir="ltr">{c.tokens_in ?? "—"} / {c.tokens_out ?? "—"}</td>
            <td className="px-3 py-2">{c.subscription ? t("ai.settings.log.subscription") : c.cost_usd ? `$${f.num(c.cost_usd)}` : "—"}</td>
            <td className="px-3 py-2"><Status tone={c.status === "ok" ? "success" : c.status === "skipped" ? "neutral" : "danger"}>{c.status}</Status></td>
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
    <div className="flex flex-col gap-5">
      <PageHeader title={t("ai.settings.title")} subtitle={t("ai.settings.subtitle")} />
      <PageGrid side={<CapCard />}>
        <section className="flex flex-col gap-3" aria-labelledby="ai-providers-h">
          <h2 id="ai-providers-h" className="text-lg font-semibold text-title">{t("ai.settings.providers")}</h2>
          {providers.isLoading ? <Loading /> : providers.error ? <ErrorState error={providers.error} onRetry={() => void providers.refetch()} /> : (
            <ul className="grid grid-cols-1 gap-4 2xl:grid-cols-2">{(providers.data ?? []).map((p) => <ProviderRow key={p.id} p={p} onChanged={refresh} />)}</ul>
          )}
        </section>
      </PageGrid>
      <RoutesCard providers={providers.data ?? []} />
      <PrivacyLog />
    </div>
  );
}
