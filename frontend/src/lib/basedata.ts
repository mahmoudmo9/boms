/** Base data used by the smart fields: countries, currencies, units and the Incoterms® 2020 rules (cached). */
import { useQuery } from "@tanstack/react-query";

import { api, type Page } from "./api";
import type { Country, Currency, Unit } from "./types";

export const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"] as const;

/** Currencies the owner uses most, first in every currency list. */
export const COMMON_CURRENCIES = ["USD", "EUR", "AED", "CNY", "IRR", "TRY", "RUB", "INR"];

export function useCountries() {
  return useQuery({
    queryKey: ["basedata", "countries", "all-active"],
    queryFn: () => api<Page<Country>>("/api/basedata/countries", { query: { active: true, page_size: 500 } }),
    staleTime: 5 * 60_000,
  });
}

export function useCurrencies() {
  return useQuery({
    queryKey: ["basedata", "currencies", "active"],
    queryFn: () => api<Page<Currency>>("/api/basedata/currencies", { query: { active: true, page_size: 500 } }),
    staleTime: 5 * 60_000,
  });
}

export function useUnits() {
  return useQuery({
    queryKey: ["basedata", "units", "active"],
    queryFn: () => api<Page<Unit>>("/api/basedata/units", { query: { active: true, page_size: 500 } }),
    staleTime: 5 * 60_000,
  });
}

export function useIncoterms() {
  return useQuery({
    queryKey: ["reference", "incoterms"],
    queryFn: () => api<{ code: string; name_en: string; name_fa: string }[]>("/api/reference/incoterms"),
    staleTime: Infinity,
  });
}

/** Common currencies first (in their order), then the rest as listed. */
export function sortCurrencies<T extends { code: string }>(rows: T[]): T[] {
  return [...rows.filter((c) => COMMON_CURRENCIES.includes(c.code)).sort((a, b) => COMMON_CURRENCIES.indexOf(a.code) - COMMON_CURRENCIES.indexOf(b.code)),
    ...rows.filter((c) => !COMMON_CURRENCIES.includes(c.code))];
}
