import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router";

import { CommandPalette } from "../components/CommandPalette";
import { QuickLogProvider, useQuickLog } from "../pages/parties/QuickLog";
import { Icon } from "../components/Icon";
import { IconButton } from "../components/ui";
import { useAuth } from "../lib/auth";
import { toFaDigits } from "../lib/format";
import { WORKSPACES } from "../lib/nav";
import { useFormat } from "../lib/prefs";
import type { Theme } from "../lib/types";

const THEME_ORDER: Theme[] = ["light", "dark", "system"];
const THEME_ICON: Record<Theme, string> = { light: "sun", dark: "moon", system: "monitor" };

function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const location = useLocation();
  return (
    <aside
      className={`fixed inset-y-0 start-0 z-40 flex w-64 shrink-0 flex-col border-e border-line bg-surface transition-transform lg:static ${
        open ? "" : "max-lg:-translate-x-full max-lg:rtl:translate-x-full"
      }`}
    >
      <div className="flex h-14 items-center gap-2 border-b border-line px-4">
        <img src="/icons/icon.svg" alt="" className="h-7 w-7" />
        <span className="font-semibold tracking-wide">BOMS</span>
      </div>
      <nav className="flex-1 overflow-y-auto p-2" aria-label={t("nav.label")}>
        {WORKSPACES.map((ws) => {
          const inSection = location.pathname === ws.path || location.pathname.startsWith(`${ws.path}/`);
          return (
            <div key={ws.key}>
              <NavLink
                to={ws.children ? ws.children[0].path : ws.path}
                end={!ws.children}
                onClick={onNavigate}
                className={() =>
                  `flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm ${
                    inSection ? "bg-accent-soft font-medium text-accent" : "text-fg hover:bg-surface-2"
                  }`
                }
              >
                <Icon name={ws.icon} size={17} />
                <span className="flex-1 truncate">{t(`nav.${ws.key}`)}</span>
                {ws.phase && (
                  <span className="text-[11px] text-muted">
                    {t("nav.phaseShort", { phase: f.digits === "fa" ? toFaDigits(ws.phase) : ws.phase })}
                  </span>
                )}
              </NavLink>
              {ws.children && inSection && (
                <div className="my-1 ms-6 flex flex-col border-s border-line ps-2">
                  {ws.children.map((child) => {
                    const prefix = (path: string) => path.replace(/\/countries$/, "");
                    const others = ws.children!.filter((c) => c.path !== ws.path);
                    const inOther = others.some((c) => location.pathname.startsWith(prefix(c.path)));
                    // the section root (/settings, /parties) is active for its own pages that no other child claims
                    const active =
                      child.path === ws.path
                        ? !inOther && (location.pathname === ws.path || (ws.key === "parties" && location.pathname.startsWith(`${ws.path}/`)))
                        : location.pathname.startsWith(prefix(child.path));
                    return (
                      <NavLink
                        key={child.key}
                        to={child.path}
                        onClick={onNavigate}
                        className={`flex h-8 items-center rounded px-2 text-sm ${
                          active ? "font-medium text-accent" : "text-muted hover:text-fg"
                        }`}
                      >
                        {t(`nav.sub.${child.key}`)}
                      </NavLink>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}

function QuickLogButton() {
  const { t } = useTranslation();
  const quickLog = useQuickLog();
  return (
    <button
      type="button"
      onClick={() => quickLog.open()}
      title={`${t("quicklog.button")} (Ctrl+Shift+L)`}
      className="me-1 inline-flex h-8 items-center gap-1.5 rounded-md bg-accent px-2.5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
    >
      <Icon name="plus" size={15} />
      <span className="hidden md:inline">{t("quicklog.button")}</span>
    </button>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const { user, lock, logout, updatePrefs } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => setNavOpen(false), [location.pathname]);

  if (!user) return null;
  const nextTheme = THEME_ORDER[(THEME_ORDER.indexOf(user.theme) + 1) % THEME_ORDER.length];

  return (
    <QuickLogProvider>
    <div className="flex h-full">
      <Sidebar open={navOpen} onNavigate={() => setNavOpen(false)} />
      {navOpen && <div className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => setNavOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-3">
          <IconButton icon="menu" label={t("nav.menu")} className="lg:hidden" onClick={() => setNavOpen(true)} />
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="flex h-8 w-full max-w-md items-center gap-2 rounded-md border border-line-strong bg-surface-2 px-2.5 text-sm text-muted hover:border-accent"
          >
            <Icon name="search" size={16} />
            <span className="flex-1 text-start">{t("search.open")}</span>
            <kbd className="rounded border border-line bg-surface px-1.5 text-xs" dir="ltr">Ctrl K</kbd>
          </button>
          <div className="ms-auto flex items-center gap-1">
            <QuickLogButton />
            <button
              type="button"
              onClick={() => void updatePrefs({ language: user.language === "fa" ? "en" : "fa" })}
              className="h-8 rounded-md px-2 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg"
              title={t("settings.language")}
            >
              {user.language === "fa" ? t("common.languageShort.en") : t("common.languageShort.fa")}
            </button>
            <IconButton
              icon={THEME_ICON[user.theme]}
              label={`${t("settings.theme")}: ${t(`settings.themes.${user.theme}`)}`}
              onClick={() => void updatePrefs({ theme: nextTheme })}
            />
            <IconButton icon="lock" label={t("auth.lockNow")} onClick={() => void lock()} />
            <IconButton icon="logout" label={t("auth.logout")} onClick={() => void logout()} />
            <span className="ms-1 hidden text-sm text-muted sm:inline">
              <bdi>{user.username}</bdi>
            </span>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
    </QuickLogProvider>
  );
}
