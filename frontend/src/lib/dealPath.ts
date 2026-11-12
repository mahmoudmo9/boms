/** The deal path of a case (v0.10.0, reference ProCase): استعلام ← پیشنهاد ← سفارش ← حمل ← تحویل ← بستن, read from
 * the line items' statuses and the case status (no new data). Pure, tested without a browser. */
import type { ItemStatus } from "./types";

export type PathStep = "inquiry" | "offer" | "order" | "shipment" | "delivery" | "close";
export const PATH: PathStep[] = ["inquiry", "offer", "order", "shipment", "delivery", "close"];

const RANK: Record<ItemStatus, number> = { uncovered: 0, rfq_sent: 0, has_offer: 1, selected: 1, sold: 2, delivered: 4, closed: 5, cancelled: -1 };

/** How far the case has come: the index of the step being worked on (0..5), 6 when closed. */
export function reached(statuses: ItemStatus[], caseStatus: string, hasShipment = false): number {
  if (caseStatus === "closed") return PATH.length;
  const live = statuses.filter((s) => s !== "cancelled");
  if (live.length === 0) return 0;
  const best = Math.max(...live.map((s) => RANK[s]));
  if (best >= 4) return live.every((s) => RANK[s] >= 4) ? 5 : 4;      // everything delivered: closing is next
  if (best === 2) return hasShipment ? 3 : 2;                          // sold: ordering, then shipping
  return best === 1 ? 1 : 0;
}

export function pathSteps(statuses: ItemStatus[], caseStatus: string, hasShipment = false): { key: PathStep; state: "done" | "current" | "upcoming" }[] {
  const at = reached(statuses, caseStatus, hasShipment);
  return PATH.map((key, i) => ({ key, state: i < at ? "done" : i === at ? "current" : "upcoming" }));
}

/** Share of the path done, for the progress ring. */
export function pathPercent(statuses: ItemStatus[], caseStatus: string, hasShipment = false): number {
  return Math.round((reached(statuses, caseStatus, hasShipment) / PATH.length) * 100);
}
