/** i18n 초기화 — ko/en. 기본 한국어, localStorage 저장. */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import ko from "./i18n/ko.json";
import en from "./i18n/en.json";

export const SUPPORTED_LANGS = [
  { code: "ko", label: "한국어" },
  { code: "en", label: "English" },
] as const;

const STORAGE_KEY = "suno_helper_lang";

function detectLang(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "ko" || saved === "en") return saved;
  } catch {
    /* ignore */
  }
  const nav = typeof navigator !== "undefined" ? navigator.language || "" : "";
  return nav.toLowerCase().startsWith("ko") ? "ko" : "ko"; // 기본 한국어
}

i18n.use(initReactI18next).init({
  resources: {
    ko: { translation: ko },
    en: { translation: en },
  },
  lng: detectLang(),
  fallbackLng: "ko",
  interpolation: { escapeValue: false },
});

export function changeLang(code: string) {
  i18n.changeLanguage(code);
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    /* ignore */
  }
}

export default i18n;
