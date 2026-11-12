/** The app shell (v0.10.0 section 3): the sidebar (modules, the current one marked, collapsible to icons, the BOMS
 * mark; modules not built yet keep their version tag) and the top bar (the search field that opens the command
 * palette, quick add, theme light / dark / system, language, lock, user). Global keys: Ctrl+K and «/» open the
 * palette, «?» the shortcut sheet. Below 1024 px the sidebar is a drawer. Live updates run for the whole app. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { Icon, IconButton, Kbd, Menu } from "../design/components";
import { useAuth } from "../lib/auth";
import { toFaDigits } from "../lib/format";
import { WORKSPACES, type Workspace } from "../lib/nav";
import { slashOpens } from "../lib/palette";
import { useFormat } from "../lib/prefs";
import type { Theme } from "../lib/types";
import { QuickLogProvider, useQuickLog } from "../pages/parties/QuickLog";
import { CommandPalette } from "./CommandPalette";
import { LiveUpdatesProvider, useLive } from "./LiveUpdates";
import { ShortcutSheet } from "./Shortcuts";

const THEME_ICON: Record<Theme, string> = { light: "sun", dark: "moon", system: "monitor" };
const COLLAPSE_KEY = "boms.nav.collapsed";
const readCollapsed = () => { try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; } };

function inSection(ws: Workspace, path: string) {
  return path === ws.path || path.startsWith(`${ws.path}/`) || Boolean(ws.children?.some((c) => path === c.path || path.startsWith(`${c.path}/`)));
}

function Sidebar({ open, collapsed, onToggle, onNavigate }: { open: boolean; collapsed: boolean; onToggle: () => void; onNavigate: () => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const location = useLocation();
  const narrow = collapsed && !open;
  return (
    <aside data-testid="sidebar" data-collapsed={narrow || undefined}
      className={`fixed inset-y-0 start-0 z-(--z-drawer) flex shrink-0 flex-col border-e border-rail-line bg-rail text-rail-fg transition-[width,transform] duration-200 ease-out lg:static ${narrow ? "w-(--rail-width-collapsed)" : "w-(--rail-width)"} ${open ? "" : "max-lg:-translate-x-full max-lg:rtl:translate-x-full"}`}>
      <div className={`flex h-(--topbar-height) shrink-0 items-center gap-3 border-b border-rail-line ${narrow ? "justify-center px-2" : "px-5"}`}>
        <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-linear-to-br from-accent-fill-from to-accent-fill-to font-display text-lg font-bold text-accent-fg">B</span>
        {!narrow && <span className="flex flex-col leading-tight"><span className="text-md font-bold tracking-wide text-rail-title">BOMS</span><span className="text-2xs text-rail-muted">{t("shell.tagline")}</span></span>}
      </div>
      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-4" aria-label={t("nav.label")}>
        <ul className="flex flex-col gap-0.5">
          {WORKSPACES.map((ws) => {
            const active = inSection(ws, location.pathname);
            const name = t(`nav.${ws.key}`);
            return (
              <li key={ws.key}>
                <NavLink to={ws.children ? ws.children[0].path : ws.path} end={!ws.children} onClick={onNavigate} title={narrow ? name : undefined}
                  aria-current={active ? "page" : undefined} data-testid={`nav-${ws.key}`}
                  className={`relative flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors duration-150 ${narrow ? "justify-center" : ""} ${active ? "bg-rail-active font-semibold text-rail-title before:absolute before:inset-y-2 before:start-0 before:w-0.75 before:rounded-2xl before:bg-rail-accent" : "text-rail-fg hover:bg-rail-active hover:text-rail-title"}`}>
                  <Icon name={ws.icon} size={18} className={active ? "text-rail-accent" : ""} />
                  {!narrow && <span className="flex-1 truncate">{name}</span>}
                  {!narrow && ws.phase && <span className="rounded-2xl border border-rail-line px-2 text-2xs text-rail-muted">{t("nav.phaseShort", { phase: f.digits === "fa" ? toFaDigits(ws.phase) : ws.phase })}</span>}
                  {narrow && <span className="sr-only">{name}</span>}
                </NavLink>
                {ws.children && active && !narrow && (
                  <ul className="my-1 ms-6 flex flex-col border-s border-rail-line ps-2.5">
                    {ws.children.map((child) => {
                      const prefix = (path: string) => path.replace(/\/countries$/, "");
                      const others = ws.children!.filter((c) => c.path !== ws.path);
                      const inOther = others.some((c) => location.pathname.startsWith(prefix(c.path)));
                      const on = child.path === ws.path
                        ? !inOther && (location.pathname === ws.path || (ws.key === "parties" && location.pathname.startsWith(`${ws.path}/`)))
                        : location.pathname.startsWith(prefix(child.path));
                      return (
                        <li key={child.key}>
                          <NavLink to={child.path} onClick={onNavigate} aria-current={on ? "page" : undefined}
                            className={`flex min-h-9 items-center rounded-md px-2.5 text-sm transition-colors duration-150 ${on ? "font-medium text-rail-accent" : "text-rail-muted hover:text-rail-title"}`}>
                            {t(`nav.sub.${child.key}`)}
                          </NavLink>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
      <div className={`flex shrink-0 border-t border-rail-line p-3 max-lg:hidden ${narrow ? "justify-center" : "justify-end"}`}>
        <button type="button" onClick={onToggle} aria-label={narrow ? t("shell.expand") : t("shell.collapse")} title={narrow ? t("shell.expand") : t("shell.collapse")}
          aria-expanded={!narrow} data-testid="nav-collapse"
          className="inline-flex size-10 cursor-pointer items-center justify-center rounded-lg text-rail-muted transition-colors duration-150 hover:bg-rail-active hover:text-rail-title">
          <Icon name="sidebar" size={18} />
        </button>
      </div>
    </aside>
  );
}

function LiveDot() {
  const { t } = useTranslation();
  const { transport } = useLive();
  const tone = transport === "stream" ? "bg-success" : transport === "polling" ? "bg-warning" : "bg-faint";
  return (
    <span className="relative inline-flex size-10 items-center justify-center" title={t(`shell.live.${transport}`)} data-testid="live" data-transport={transport}>
      <span aria-hidden className={`size-2 rounded-2xl ${tone}`} />
      <span className="sr-only">{t(`shell.live.${transport}`)}</span>
    </span>
  );
}

function TopBar({ onPalette, onMenu, onShortcuts }: { onPalette: () => void; onMenu: () => void; onShortcuts: () => void }) {
  const { t } = useTranslation();
  const { user, lock, logout, updatePrefs } = useAuth();
  const quickLog = useQuickLog();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <header className="flex h-(--topbar-height) shrink-0 items-center gap-2 border-b border-line bg-surface px-3 lg:px-5" data-testid="topbar">
      <IconButton icon="menu" label={t("nav.menu")} className="lg:hidden" onClick={onMenu} />
      <button type="button" onClick={onPalette} data-testid="open-palette" aria-haspopup="dialog"
        className="flex h-10 w-full max-w-md min-w-0 cursor-pointer items-center gap-2.5 rounded-xl border border-accent-line bg-sunken px-3.5 text-sm text-muted transition-colors duration-150 hover:border-accent hover:text-fg">
        <Icon name="search" size={16} className="text-accent" />
        <span className="min-w-0 flex-1 truncate text-start">{t("palette.open")}</span>
        <Kbd>Ctrl K</Kbd>
      </button>
      <div className="ms-auto flex items-center gap-1">
        <LiveDot />
        <Menu label={t("shell.quickAdd")} testId="quick-add" trigger={(p) => (
          <button type="button" {...p} data-testid="quick-add" title={t("shell.quickAdd")}
            className="relative me-1 inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg bg-linear-to-br from-accent-fill-from to-accent-fill-to px-3 text-sm font-semibold text-accent-fg after:absolute after:-inset-y-0.5 after:inset-x-0 hover:brightness-105">
            <Icon name="plus" size={15} /><span className="max-md:sr-only">{t("shell.quickAdd")}</span>
          </button>)}
          items={[
            { key: "log", label: t("quicklog.button"), icon: "inbox", hint: "Ctrl+Shift+L", onSelect: () => quickLog.open() },
            { key: "inquiry", label: t("palette.action.newInquiry"), icon: "plus", onSelect: () => navigate("/sourcing?new=1") },
            { key: "party", label: t("palette.action.newParty"), icon: "users", onSelect: () => navigate("/parties?new=1") },
            { key: "task", label: t("palette.action.newTask"), icon: "check", onSelect: () => navigate("/tasks?new=1") },
          ]} />
        <Menu label={t("settings.theme")} testId="theme" trigger={(p) => <IconButton icon={THEME_ICON[user.theme]} label={`${t("settings.theme")}: ${t(`settings.themes.${user.theme}`)}`} data-testid="theme" {...p} />}
          items={(["light", "dark", "system"] as Theme[]).map((theme) => ({ key: theme, label: t(`settings.themes.${theme}`), icon: THEME_ICON[theme], checked: user.theme === theme,
            onSelect: () => void updatePrefs({ theme }) }))} />
        <button type="button" onClick={() => void updatePrefs({ language: user.language === "fa" ? "en" : "fa" })} data-testid="language"
          lang={user.language === "fa" ? "en" : "fa"} aria-label={t("shell.switchLanguage", { language: t(`common.languageNames.${user.language === "fa" ? "en" : "fa"}`) })}
          className="inline-flex size-10 cursor-pointer items-center justify-center rounded-md text-sm font-semibold text-muted transition-colors duration-150 hover:bg-hover hover:text-fg">
          {user.language === "fa" ? t("common.languageShort.en") : t("common.languageShort.fa")}
        </button>
        <IconButton icon="keyboard" label={t("shortcuts.title")} onClick={onShortcuts} className="max-md:hidden" />
        <IconButton icon="lock" label={t("auth.lockNow")} onClick={() => void lock()} />
        <Menu label={t("shell.user")} testId="user" trigger={(p) => (
          <button type="button" {...p} data-testid="user" aria-label={`${t("shell.user")}: ${user.username}`}
            className="ms-1 inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg px-1.5 text-sm text-fg-2 transition-colors duration-150 hover:bg-hover">
            <span aria-hidden className="flex size-8 items-center justify-center rounded-2xl border border-accent-line bg-accent-soft text-xs font-semibold text-accent">{user.username.slice(0, 1).toUpperCase()}</span>
            <bdi className="max-sm:hidden">{user.username}</bdi>
          </button>)}
          items={[{ key: "settings", label: t("nav.settings"), icon: "settings", onSelect: () => navigate("/settings") },
            { key: "logout", label: t("auth.logout"), icon: "logout", danger: true, onSelect: () => void logout() }]} />
      </div>
    </header>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const location = useLocation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((v) => !v); return; }
      if (e.ctrlKey || e.metaKey || e.altKey || !slashOpens(e.target) || document.querySelector("[role=dialog][aria-modal=true]")) return;
      if (e.key === "/") { e.preventDefault(); setPaletteOpen(true); }
      else if (e.key === "?") { e.preventDefault(); setSheetOpen(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => setNavOpen(false), [location.pathname]);
  const toggle = () => setCollapsed((v) => { try { localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1"); } catch { /* ignore */ } return !v; });

  if (!user) return null;
  return (
    <LiveUpdatesProvider>
      <QuickLogProvider>
        <a href="#main" className="sr-only z-(--z-toast) rounded-md bg-surface-3 px-3 py-2 focus:not-sr-only focus:fixed focus:start-3 focus:top-3">{t("shell.skip")}</a>
        <div className="flex h-full">
          <Sidebar open={navOpen} collapsed={collapsed} onToggle={toggle} onNavigate={() => setNavOpen(false)} />
          {navOpen && <div className="fixed inset-0 z-(--z-rail) bg-overlay lg:hidden" onClick={() => setNavOpen(false)} aria-hidden />}
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar onPalette={() => setPaletteOpen(true)} onMenu={() => setNavOpen(true)} onShortcuts={() => setSheetOpen(true)} />
            <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto px-4 py-5 outline-none lg:px-8 lg:py-7">
              <div className="mx-auto w-full max-w-screen-3xl">
                <Outlet />
              </div>
            </main>
          </div>
          <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
          <ShortcutSheet open={sheetOpen} onClose={() => setSheetOpen(false)} />
        </div>
      </QuickLogProvider>
    </LiveUpdatesProvider>
  );
}
