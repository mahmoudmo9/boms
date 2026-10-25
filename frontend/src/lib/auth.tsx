/** Session state: login, idle lock (client + server), unlock, logout, preference updates. */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { api, authEvents } from "./api";
import { applyLanguage, applyTheme, storedTheme } from "./prefs";
import type { AuthState, User } from "./types";

type Status = "loading" | "nouser" | "anon" | "locked" | "ready" | "error";

interface AuthContextValue {
  status: Status;
  user: User | null;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  unlock: (password: string) => Promise<void>;
  lock: () => Promise<void>;
  logout: () => Promise<void>;
  updatePrefs: (changes: Partial<User>) => Promise<void>;
  reload: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const ACTIVITY_EVENTS = ["mousedown", "keydown", "wheel", "touchstart", "mousemove"] as const;
const KEEPALIVE_MS = 60_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const reload = useCallback(async () => {
    try {
      const state = await api<AuthState>("/api/auth/state", { background: true });
      setUsername(state.username);
      if (state.language) applyLanguage(state.language);
      applyTheme(state.user?.theme ?? state.theme ?? storedTheme());
      if (!state.user_exists) setStatus("nouser");
      else if (state.locked) setStatus("locked");
      else if (state.authenticated && state.user) {
        setUser(state.user);
        setStatus("ready");
      } else setStatus("anon");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const onAuth = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail === "locked") setStatus("locked");
      if (detail === "unauthenticated") {
        setUser(null);
        setStatus("anon");
        queryClient.clear();
      }
    };
    authEvents.addEventListener("auth", onAuth);
    return () => authEvents.removeEventListener("auth", onAuth);
  }, [queryClient]);

  useEffect(() => {
    if (user) {
      applyLanguage(user.language);
      applyTheme(user.theme);
    }
  }, [user]);

  const acceptUser = useCallback((u: User) => {
    setUser(u);
    setUsername(u.username);
    setStatus("ready");
  }, []);

  const login = useCallback(async (name: string, password: string) => {
    acceptUser(await api<User>("/api/auth/login", { method: "POST", body: { username: name, password } }));
  }, [acceptUser]);

  const unlock = useCallback(async (password: string) => {
    acceptUser(await api<User>("/api/auth/unlock", { method: "POST", body: { password } }));
  }, [acceptUser]);

  const lock = useCallback(async () => {
    await api("/api/auth/lock", { method: "POST" }).catch(() => undefined);
    setStatus("locked");
  }, []);

  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    queryClient.clear();
    setUser(null);
    setStatus("anon");
  }, [queryClient]);

  const updatePrefs = useCallback(async (changes: Partial<User>) => {
    setUser(await api<User>("/api/me", { method: "PATCH", body: changes }));
  }, []);

  // Idle lock on the client, plus a keep-alive so reading without clicking still counts as activity.
  const lastActivity = useRef(Date.now());
  const lastPing = useRef(Date.now());
  useEffect(() => {
    if (status !== "ready" || !user) return;
    lastActivity.current = Date.now();
    const mark = () => {
      lastActivity.current = Date.now();
    };
    ACTIVITY_EVENTS.forEach((ev) => window.addEventListener(ev, mark, { passive: true }));
    const timer = window.setInterval(() => {
      const now = Date.now();
      if (now - lastActivity.current > user.idle_lock_minutes * 60_000) {
        void lock();
      } else if (lastActivity.current > lastPing.current && now - lastPing.current > KEEPALIVE_MS) {
        lastPing.current = now;
        void api("/api/me").catch(() => undefined);
      }
    }, 10_000);
    return () => {
      ACTIVITY_EVENTS.forEach((ev) => window.removeEventListener(ev, mark));
      window.clearInterval(timer);
    };
  }, [status, user, lock]);

  return (
    <AuthContext.Provider value={{ status, user, username, login, unlock, lock, logout, updatePrefs, reload }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}
