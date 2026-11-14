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
  interpolation: { escapeValue: false },
  returnNull: false,
  showSupportNotice: false,
});

export default i18n;
