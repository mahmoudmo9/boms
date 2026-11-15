import i18n, { type BackendModule } from "i18next";
import { initReactI18next } from "react-i18next";

import fa from "./fa.json";

export function storedLanguage(): "fa" | "en" {
  try {
    return localStorage.getItem("boms.lang") === "en" ? "en" : "fa";
  } catch {
    return "fa";
  }
}

const formats = new Map<string, Intl.NumberFormat>();
function numberFormat(lng: string | undefined): Intl.NumberFormat {
  const locale = lng === "fa" ? "fa-IR" : "en-US";
  let nf = formats.get(locale);
  if (!nf) { nf = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }); formats.set(locale, nf); }
  return nf;
}

/** Persian ships in the first load; English is a chunk of its own, loaded when it is chosen (v0.10.1 section 0.3.4).
 * changeLanguage("en") waits for it, so callers that await it see English at once. */
const lazyLanguages: BackendModule = {
  type: "backend",
  init() {},
  read(language, _namespace, callback) {
    if (language !== "en") return callback(null, language === "fa" ? fa : {});
    import("./en.json").then((m) => callback(null, m.default), (error: Error) => callback(error, null));
  },
};

/** Resolves once the stored language is ready; the app renders after it. */
export const i18nReady = i18n.use(lazyLanguages).use(initReactI18next).init({
  resources: { fa: { translation: fa } },
  partialBundledLanguages: true,
  lng: storedLanguage(),
  fallbackLng: false,
  // v0.10.1 section 3.3: a number passed to t() is formatted for the language (Persian digits and «٬» in fa), so a
  // count or a percentage never shows Latin digits in the Persian UI. Strings (already formatted) pass through.
  interpolation: {
    escapeValue: false,
    alwaysFormat: true,
    format: (value: unknown, _format: string | undefined, lng: string | undefined) =>
      typeof value === "number" && Number.isFinite(value) ? numberFormat(lng).format(value) : (value as string),
  },
  returnNull: false,
  showSupportNotice: false,
});

export default i18n;
