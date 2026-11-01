/** Live "time left" badge (v0.6.0): one helper for the screening list, the listing panel, inquiry/case headers, the
 * command center and tender dates. Recomputed every minute so it never goes stale while the page is open. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { timeLeft, timeLeftMessage } from "../lib/timeLeft";
import { useFormat } from "../lib/prefs";
import { Badge } from "./ui";

let listeners = new Set<(d: Date) => void>();
let timer: ReturnType<typeof setInterval> | null = null;

/** The current time, updated every minute (one shared timer for every badge on the page). */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    listeners.add(setNow);
    if (!timer) timer = setInterval(() => { const d = new Date(); listeners.forEach((l) => l(d)); }, 60_000);
    return () => {
      listeners.delete(setNow);
      if (listeners.size === 0 && timer) { clearInterval(timer); timer = null; listeners = new Set(); }
    };
  }, []);
  return now;
}

export function useTimeLeftText() {
  const { t } = useTranslation();
  const f = useFormat();
  return (deadline: string | null | undefined, now: Date, estimate = false) => {
    const tl = timeLeft(deadline, now, estimate);
    if (!tl) return null;
    const { key, values } = timeLeftMessage(tl);
    const nums = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, k === "count" ? v : f.num(v as number)]));
    const text = t(key, nums);
    return { tl, text: estimate ? t("time.about", { text }) : text };
  };
}

export function TimeLeftBadge({ at, estimate = false, className }: { at: string | null | undefined; estimate?: boolean; className?: string }) {
  const now = useNow();
  const fmt = useTimeLeftText();
  const out = fmt(at, now, estimate);
  if (!out) return null;
  return <span className={className} data-testid="time-left" data-tone={out.tl.tone}><Badge tone={out.tl.tone}>{out.text}</Badge></span>;
}
