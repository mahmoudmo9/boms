/** Time left until a deadline at the precision that matters (v0.6.0, SetadSuite «۳ روز و ۲۱ ساعت»). Pure and
 * unit-tested; components/TimeLeft.tsx renders it in both languages and recomputes it every minute.
 *
 * - 2 days or more: whole days from the exact time («۳ روز»);
 * - under 2 days: days and hours («۱ روز و ۲۱ ساعت»);
 * - under 1 day: hours and minutes (red);
 * - under 1 hour: minutes;
 * - passed: how long ago («۲ ساعت پیش»), in minutes, hours or days. */

export type TimeLeftKind = "days" | "daysHours" | "hoursMinutes" | "minutes" | "passed";
export type TimeTone = "success" | "warning" | "danger" | "neutral";

export interface TimeLeft {
  kind: TimeLeftKind;
  days: number;
  hours: number;
  minutes: number;
  /** passed: how long ago, in the largest unit */
  ago: { unit: "minutes" | "hours" | "days"; n: number } | null;
  tone: TimeTone;
  estimate: boolean;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function timeLeft(deadline: string | Date | null | undefined, now: Date = new Date(), estimate = false): TimeLeft | null {
  if (!deadline) return null;
  const at = typeof deadline === "string" ? new Date(deadline) : deadline;
  if (Number.isNaN(at.getTime())) return null;
  const ms = at.getTime() - now.getTime();
  if (ms < 0) {
    const past = -ms;
    const ago = past < HOUR ? { unit: "minutes" as const, n: Math.max(1, Math.floor(past / MINUTE)) }
      : past < DAY ? { unit: "hours" as const, n: Math.floor(past / HOUR) }
        : { unit: "days" as const, n: Math.floor(past / DAY) };
    return { kind: "passed", days: 0, hours: 0, minutes: 0, ago, tone: "neutral", estimate };
  }
  const days = Math.floor(ms / DAY);
  const hours = Math.floor((ms % DAY) / HOUR);
  const minutes = Math.floor((ms % HOUR) / MINUTE);
  const kind: TimeLeftKind = ms >= 2 * DAY ? "days" : ms >= DAY ? "daysHours" : ms >= HOUR ? "hoursMinutes" : "minutes";
  const tone: TimeTone = ms < DAY ? "danger" : ms < 3 * DAY ? "warning" : "success";
  return { kind, days, hours, minutes, ago: null, tone, estimate };
}

/** i18n key and values for a TimeLeft (numbers are formatted by the caller). */
export function timeLeftMessage(tl: TimeLeft): { key: string; values: Record<string, number | string> } {
  if (tl.kind === "passed") return { key: `time.passedAgo.${tl.ago!.unit}`, values: { count: tl.ago!.n, n: tl.ago!.n } };
  return { key: `time.left.${tl.kind}`, values: { count: tl.days, d: tl.days, h: tl.hours, m: tl.minutes } };
}

/** SetadSuite's detail pages append «(باقی‌مانده هنگام دریافت: ۱۴ روز و ۱ ساعت)» to deadlines: drop it (the live
 * badge replaces it). */
export function stripRemainingRemark(text: string): string {
  return text.replace(/\s*[(（]\s*باقی[‌ ]?مانده[^)）]*[)）]\s*/g, " ").trim();
}
