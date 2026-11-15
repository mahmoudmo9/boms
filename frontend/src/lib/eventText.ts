/** Generated event sentences (v0.10.1 section 1.1): «سفارش خرید PO-1405-0007 ثبت شد». Every action has a fa/en
 * template with ``{{subject}}``; the subject is the object's noun and code, linked to where it is shown. */
import type { EventItem, EventSubject } from "./types";

/** Child records of a case open on the case's tab. */
const CASE_TABS: Record<string, string> = {
  rfq: "rfqs", offer: "offers", cost_sheet: "costing", quote: "quotes", sales_order: "order", purchase_order: "purchase",
  shipment: "logistics", process: "purchase", tender: "tender", sales_invoice: "finance", purchase_invoice: "finance",
  payment_milestone: "finance", guarantee: "tender", line_item: "items",
};

export function subjectOf(e: EventItem): EventSubject {
  return e.subject ?? { type: e.entity_type, id: e.entity_id, code: null, name: null };
}

/** Where the subject is shown, or null. ``caseId`` is the case the event belongs to, when known. */
export function subjectHref(subject: EventSubject, e: EventItem, caseId?: string | null): string | null {
  const id = subject.id;
  if (!id) return null;
  switch (subject.type) {
    case "case": return `/cases/${id}`;
    case "party": return `/parties/${id}`;
    case "inquiry": return `/sourcing/inquiries/${id}`;
    case "product": return `/sourcing/catalog/${id}`;
    case "document": return `/documents/${id}`;
  }
  const owner = caseId ?? (e.entity_type === "case" ? e.entity_id : null);
  const tab = CASE_TABS[subject.type];
  return owner && tab ? `/cases/${owner}?tab=${tab}` : null;
}

/** The template split around the subject: ``[before, after]`` (``after`` is null when it has no subject slot). */
export function splitTemplate(template: string): [string, string | null] {
  const at = template.indexOf("{{subject}}");
  return at < 0 ? [template, null] : [template.slice(0, at), template.slice(at + "{{subject}}".length)];
}

/** The short label for a filter list: the template without its subject. */
export function shortLabel(template: string): string {
  return template.replace("{{subject}}", "").replace(/\s+/g, " ").trim();
}
