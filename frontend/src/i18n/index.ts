import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import fa from "./fa.json";

export function storedLanguage(): "fa" | "en" {
  try {
    return localStorage.getItem("boms.lang") === "en" ? "en" : "fa";
  } catch {
    return "fa";
  }
}

void i18n.use(initReactI18next).init({
  resources: { fa: { translation: fa }, en: { translation: en } },
  lng: storedLanguage(),
  fallbackLng: false,
  interpolation: { escapeValue: false },
  returnNull: false,
  showSupportNotice: false,
});

export default i18n;
