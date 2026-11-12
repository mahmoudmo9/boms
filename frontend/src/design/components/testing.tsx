/** Test helpers for the component library (Vitest + Testing Library, jsdom). Not imported by the app.
 *
 * Each test file mocks the signed-in user with:
 *   vi.mock("../../lib/auth", () => ({ useAuth: () => ({ user: (globalThis as { __user?: unknown }).__user }) }));
 * and renders through `renderDs`, which sets the language, direction and calendar and provides a query client. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

import i18n from "../../i18n";

export type DsOptions = { lang?: "fa" | "en"; calendar?: "jalali" | "gregorian" };

export async function setLocale({ lang = "en", calendar }: DsOptions = {}): Promise<void> {
  await i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  (globalThis as { __user?: unknown }).__user = { language: lang, calendar: calendar ?? (lang === "fa" ? "jalali" : "gregorian"), theme: "light" };
}

export async function renderDs(ui: ReactElement, options: DsOptions = {}): Promise<RenderResult> {
  await setLocale(options);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<MemoryRouter><QueryClientProvider client={client}>{ui}</QueryClientProvider></MemoryRouter>);
}
