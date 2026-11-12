/** Quick triage of Setad listings (v0.10.0, reference ProTriage): one listing at a time, decided with the keyboard.
 * Same listings and the same actions as the table (star, reviewing, dismiss with a reason, next). Pure logic. */

export type TriageCommand = "star" | "reviewing" | "dismiss" | "next" | "previous" | null;

/** S star, R reviewing, D dismiss, arrows move (logical: the next listing is ArrowLeft in RTL). Case-insensitive,
 * also on a Persian keyboard layout (س = S, ق = R, ی = D on the standard Persian layout). */
export function triageCommand(key: string, rtl: boolean): TriageCommand {
  const k = key.toLowerCase();
  if (k === "s" || k === "س") return "star";
  if (k === "r" || k === "ق") return "reviewing";
  if (k === "d" || k === "ی") return "dismiss";
  if (key === (rtl ? "ArrowLeft" : "ArrowRight") || key === "ArrowDown" || key === "j") return "next";
  if (key === (rtl ? "ArrowRight" : "ArrowLeft") || key === "ArrowUp" || key === "k") return "previous";
  return null;
}

/** After deciding a listing the next one comes up; at the end the position stays (the page loads more or says done). */
export function advance(index: number, count: number, step: 1 | -1): number {
  if (count === 0) return 0;
  return Math.max(0, Math.min(count - 1, index + step));
}

/** The listings decided in this session over the listings shown. */
export function progress(decided: Set<string>, ids: string[]): { done: number; total: number; percent: number } {
  const done = ids.filter((id) => decided.has(id)).length;
  return { done, total: ids.length, percent: ids.length ? Math.round((done / ids.length) * 100) : 0 };
}
