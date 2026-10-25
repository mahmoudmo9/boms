import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../../components/Bdi";
import { Button, Card, Checkbox, ErrorNote, Field, Input, Loading, PageHeader, Segmented } from "../../components/ui";
import { useToast } from "../../components/toast";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import type { SettingsResponse } from "../../lib/types";

function Row({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-b border-line py-3 last:border-b-0 sm:grid-cols-[14rem_1fr] sm:items-center">
      <div>
        <div className="text-sm font-medium">{label}</div>
        {hint && <div className="text-xs text-muted">{hint}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function DisplaySettings() {
  const { t } = useTranslation();
  const { user, updatePrefs } = useAuth();
  const [error, setError] = useState<unknown>(null);
  if (!user) return null;
  const change = (changes: Parameters<typeof updatePrefs>[0]) => {
    setError(null);
    updatePrefs(changes).catch(setError);
  };
  return (
    <Card title={t("settings.display")}>
      <Row label={t("settings.language")}>
        <Segmented value={user.language} label={t("settings.language")} onChange={(v) => change({ language: v })}
          options={[{ value: "fa", label: t("common.languageNames.fa") }, { value: "en", label: t("common.languageNames.en") }]} />
      </Row>
      <Row label={t("settings.calendar")}>
        <Segmented value={user.calendar} label={t("settings.calendar")} onChange={(v) => change({ calendar: v })}
          options={[{ value: "jalali", label: t("settings.calendars.jalali") }, { value: "gregorian", label: t("settings.calendars.gregorian") }]} />
      </Row>
      <Row label={t("settings.digits")}>
        <Segmented value={user.digits} label={t("settings.digits")} onChange={(v) => change({ digits: v })}
          options={[{ value: "fa", label: t("settings.digitsFa") }, { value: "latin", label: t("settings.digitsLatin") }]} />
      </Row>
      <Row label={t("settings.theme")}>
        <Segmented value={user.theme} label={t("settings.theme")} onChange={(v) => change({ theme: v })}
          options={[
            { value: "light", label: t("settings.themes.light") },
            { value: "dark", label: t("settings.themes.dark") },
            { value: "system", label: t("settings.themes.system") },
          ]} />
      </Row>
      <ErrorNote error={error} />
    </Card>
  );
}

function ProfileSettings() {
  const { t } = useTranslation();
  const toast = useToast();
  const { user, updatePrefs } = useAuth();
  const [username, setUsername] = useState(user?.username ?? "");
  const [idle, setIdle] = useState(String(user?.idle_lock_minutes ?? 30));
  const save = useMutation({
    mutationFn: () => updatePrefs({ username, idle_lock_minutes: Number(idle) }),
    onSuccess: () => toast(t("common.saved"), "success"),
  });
  return (
    <Card title={t("settings.profile")}>
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Row label={t("auth.username")}>
          <Input dir="ltr" className="max-w-xs" value={username} required maxLength={64} onChange={(e) => setUsername(e.target.value)} />
        </Row>
        <Row label={t("settings.idleLock")} hint={t("settings.idleLockHint")}>
          <Input dir="ltr" type="number" min={1} max={1440} className="w-24" value={idle} onChange={(e) => setIdle(e.target.value)} />
          <span className="text-sm text-muted">{t("settings.minutes")}</span>
        </Row>
        <ErrorNote error={save.error} />
        <div className="pt-3"><Button type="submit" variant="primary" busy={save.isPending}>{t("common.save")}</Button></div>
      </form>
    </Card>
  );
}

function PasswordSettings() {
  const { t } = useTranslation();
  const toast = useToast();
  const [form, setForm] = useState({ current: "", next: "", repeat: "" });
  const mismatch = form.repeat !== "" && form.next !== form.repeat;
  const save = useMutation({
    mutationFn: () => api("/api/me/password", { method: "POST", body: { current_password: form.current, new_password: form.next } }),
    onSuccess: () => {
      setForm({ current: "", next: "", repeat: "" });
      toast(t("settings.passwordChanged"), "success");
    },
  });
  return (
    <Card title={t("settings.password")}>
      <form className="grid max-w-md gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); if (!mismatch) save.mutate(); }}>
        <Field label={t("settings.currentPassword")} htmlFor="pw-current">
          <Input id="pw-current" type="password" dir="ltr" autoComplete="current-password" required value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} />
        </Field>
        <Field label={t("settings.newPassword")} htmlFor="pw-new" hint={t("settings.passwordRule")}>
          <Input id="pw-new" type="password" dir="ltr" autoComplete="new-password" required minLength={8} value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} />
        </Field>
        <Field label={t("settings.repeatPassword")} htmlFor="pw-repeat" error={mismatch ? t("settings.passwordMismatch") : undefined}>
          <Input id="pw-repeat" type="password" dir="ltr" autoComplete="new-password" required value={form.repeat} onChange={(e) => setForm({ ...form, repeat: e.target.value })} />
        </Field>
        <ErrorNote error={save.error} />
        <div><Button type="submit" variant="primary" busy={save.isPending} disabled={mismatch}>{t("settings.changePassword")}</Button></div>
      </form>
    </Card>
  );
}

function SystemSettings() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
  const [values, setValues] = useState<SettingsResponse["values"] | null>(null);
  const [archivePassword, setArchivePassword] = useState("");
  useEffect(() => {
    if (settings.data) setValues(settings.data.values);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/api/settings", { method: "PATCH", body: values }),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      toast(t("common.saved"), "success");
    },
  });
  const savePassword = useMutation({
    mutationFn: () => api("/api/settings/archive-password", { method: "POST", body: { password: archivePassword } }),
    onSuccess: () => {
      setArchivePassword("");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast(t("common.saved"), "success");
    },
  });

  if (settings.isLoading || !values || !settings.data) return <Loading />;
  const set = <K extends keyof SettingsResponse["values"]>(k: K, v: SettingsResponse["values"][K]) => setValues({ ...values, [k]: v });

  return (
    <Card title={t("settings.dataAndBackup")}>
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Row label={t("settings.dataFolder")} hint={t("settings.dataFolderHint")}>
          <Bdi ltr className="rounded bg-surface-2 px-2 py-1 font-mono text-xs">{settings.data.data_dir}</Bdi>
        </Row>
        <Row label={t("settings.backupTime")} hint={t("settings.backupTimeHint")}>
          <Input dir="ltr" type="time" className="w-32" required value={values["backup.time"]} onChange={(e) => set("backup.time", e.target.value)} />
        </Row>
        <Row label={t("settings.secondaryPath")} hint={t("settings.secondaryPathHint")}>
          <Input dir="ltr" className="max-w-md" placeholder="E:\BOMS-Backup" value={values["backup.secondary_path"] ?? ""} onChange={(e) => set("backup.secondary_path", e.target.value || null)} />
        </Row>
        <Row label={t("settings.archive")} hint={t("settings.archiveHint")}>
          <Checkbox label={t("settings.archiveEnabled")} checked={values["backup.archive_enabled"]} onChange={(v) => set("backup.archive_enabled", v)} />
        </Row>
        {values["backup.archive_enabled"] && (
          <Row label={t("settings.archivePath")} hint={t("settings.archivePathHint")}>
            <Input dir="ltr" className="max-w-md" value={values["backup.archive_path"] ?? ""} onChange={(e) => set("backup.archive_path", e.target.value || null)} />
          </Row>
        )}
        <Row label={t("settings.maxUpload")}>
          <Input dir="ltr" type="number" min={1} max={2048} className="w-24" value={values["upload.max_mb"]} onChange={(e) => set("upload.max_mb", Number(e.target.value))} />
          <span className="text-sm text-muted">MB</span>
        </Row>
        <Row label={t("settings.staleLeadDays")} hint={t("settings.staleLeadDaysHint")}>
          <Input dir="ltr" type="number" min={1} max={365} className="w-24" value={values["parties.stale_lead_days"]} onChange={(e) => set("parties.stale_lead_days", Number(e.target.value))} />
          <span className="text-sm text-muted">{t("settings.days")}</span>
        </Row>
        <ErrorNote error={save.error} />
        <div className="pt-3"><Button type="submit" variant="primary" busy={save.isPending}>{t("common.save")}</Button></div>
      </form>

      {values["backup.archive_enabled"] && (
        <div className="mt-4 border-t border-line pt-4">
          <Row
            label={t("settings.archivePassword")}
            hint={settings.data.archive_password_set ? t("settings.archivePasswordSet") : t("settings.archivePasswordNotSet")}
          >
            {settings.data.can_store_secrets ? (
              <form className="flex gap-2" onSubmit={(e: FormEvent) => { e.preventDefault(); savePassword.mutate(); }}>
                <Input type="password" dir="ltr" minLength={12} required className="w-56" value={archivePassword} onChange={(e) => setArchivePassword(e.target.value)} />
                <Button type="submit" busy={savePassword.isPending}>{t("settings.storePassword")}</Button>
              </form>
            ) : (
              <span className="text-sm text-muted">{t("settings.archivePasswordEnv")}</span>
            )}
          </Row>
          <ErrorNote error={savePassword.error} />
        </div>
      )}
      <p className="mt-4 text-xs text-muted">
        {t("settings.version")} <Bdi ltr>{settings.data.version}</Bdi>
      </p>
    </Card>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <PageHeader title={t("nav.settings")} />
      <DisplaySettings />
      <ProfileSettings />
      <PasswordSettings />
      <SystemSettings />
    </div>
  );
}
