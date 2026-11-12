/** v0.10.0 section 5: what `GET /api/suggest` proposes for a form once its party or product is chosen — each value with
 * its source («از PO-1405-0007»), accepted with Tab or a click while the field is empty (SuggestedValue). */
import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import type { Suggestion } from "./smart";

export type LastPrice = { unit_price: string; currency: string; date: string | null; supplier?: string };
export type Suggestions = Partial<{
  contact_id: Suggestion<string>; language: Suggestion<string>; currency: Suggestion<string>; payment_terms: Suggestion<string>;
  incoterm: Suggestion<string>; incoterm_place: Suggestion<string>; canonical_fa: Suggestion<string>; canonical_en: Suggestion<string>;
  hs_code: Suggestion<string>; unit_code: Suggestion<string>; last_purchase: Suggestion<LastPrice>; last_sale: Suggestion<LastPrice>; buyer_party_id: Suggestion<string>;
}>;

export function useSuggestions(context: "party" | "product" | "case", id: string | null | undefined, params: Record<string, string> = {}) {
  const q = useQuery({
    queryKey: ["suggest", context, id, params],
    queryFn: () => api<Suggestions>("/api/suggest", { query: { context, id: id!, ...params }, background: true }),
    enabled: !!id, staleTime: 60_000,
  });
  return id ? q.data ?? {} : {};
}
