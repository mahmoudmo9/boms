/** Login (username + password) and lock screen (password only). */
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Bdi } from "../components/Bdi";
import { Icon } from "../components/Icon";
import { Button, ErrorNote, Field, Input } from "../components/ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { applyLanguage } from "../lib/prefs";

function Frame({ children }: { children: React.ReactNode }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <img src="/icons/icon.svg" alt="" className="h-9 w-9" />
          <span className="text-xl font-semibold tracking-wide">BOMS</span>
        </div>
        <div className="rounded-lg border border-line bg-surface p-6 shadow-sm">{children}</div>
        <div className="mt-4 text-center">
          <button
            type="button"
            className="text-xs text-muted hover:text-fg"
            onClick={() => applyLanguage(i18n.language === "fa" ? "en" : "fa")}
          >
            {i18n.language === "fa" ? t("common.languageNames.en") : t("common.languageNames.fa")}
          </button>
        </div>
      </div>
    </div>
  );
}

function RateLimitAware({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error instanceof ApiError && error.status === 401) {
    return <ErrorNote error={{ code: "invalid_credentials" }} />;
  }
  if (error instanceof ApiError && error.code === "rate_limited") {
    return <p className="text-sm text-danger">{t("errors.rate_limited", { seconds: error.details.retry_after })}</p>;
  }
  return <ErrorNote error={error} />;
}

export function LoginPage() {
  const { t } = useTranslation();
  const { login, username: knownUsername } = useAuth();
  const [username, setUsername] = useState(knownUsername ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame>
      <h1 className="mb-4 text-base font-semibold">{t("auth.loginTitle")}</h1>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t("auth.username")} htmlFor="username">
          <Input id="username" dir="ltr" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus={!username} />
        </Field>
        <Field label={t("auth.password")} htmlFor="password">
          <Input id="password" type="password" dir="ltr" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus={!!username} />
        </Field>
        {error ? <RateLimitAware error={error} /> : null}
        <Button type="submit" variant="primary" busy={busy} className="mt-1 justify-center">
          {t("auth.login")}
        </Button>
      </form>
    </Frame>
  );
}

export function LockScreen() {
  const { t } = useTranslation();
  const { unlock, logout, username } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await unlock(password);
    } catch (err) {
      setError(err);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame>
      <div className="mb-4 flex items-center gap-2">
        <Icon name="lock" className="text-accent" />
        <h1 className="text-base font-semibold">{t("auth.lockedTitle")}</h1>
      </div>
      <p className="mb-4 text-sm text-muted">
        {t("auth.lockedText")} <Bdi className="font-medium text-fg">{username}</Bdi>
      </p>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t("auth.password")} htmlFor="unlock-password">
          <Input id="unlock-password" type="password" dir="ltr" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
        </Field>
        {error ? <RateLimitAware error={error} /> : null}
        <Button type="submit" variant="primary" busy={busy} className="justify-center">
          {t("auth.unlock")}
        </Button>
        <button type="button" onClick={() => void logout()} className="text-xs text-muted hover:text-fg">
          {t("auth.logout")}
        </button>
      </form>
    </Frame>
  );
}

export function NoUserPage() {
  const { t } = useTranslation();
  return (
    <Frame>
      <h1 className="mb-2 text-base font-semibold">{t("auth.noUserTitle")}</h1>
      <p className="text-sm text-muted">{t("auth.noUserText")}</p>
      <pre className="mt-3 rounded bg-surface-2 p-2 text-xs" dir="ltr">python -m app.cli create-user</pre>
    </Frame>
  );
}
