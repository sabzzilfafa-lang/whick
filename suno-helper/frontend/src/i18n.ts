/** i18n 초기화 — 11개국어. 기본 한국어, localStorage 저장. */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import ko from "./i18n/ko.json";
import en from "./i18n/en.json";
import ja from "./i18n/ja.json";
import zh from "./i18n/zh.json";
import es from "./i18n/es.json";
import fr from "./i18n/fr.json";
import de from "./i18n/de.json";
import pt from "./i18n/pt.json";
import ru from "./i18n/ru.json";
import hi from "./i18n/hi.json";
import id from "./i18n/id.json";

export const SUPPORTED_LANGS = [
  { code: "ko", label: "한국어" },
  { code: "en", label: "English" },
  { code: "ja", label: "日本語" },
  { code: "zh", label: "中文" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
  { code: "de", label: "Deutsch" },
  { code: "pt", label: "Português" },
  { code: "ru", label: "Русский" },
  { code: "hi", label: "हिन्दी" },
  { code: "id", label: "Bahasa Indonesia" },
] as const;

const SUPPORTED_CODES = new Set<string>(SUPPORTED_LANGS.map((l) => l.code));

const STORAGE_KEY = "suno_helper_lang";

function detectLang(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED_CODES.has(saved)) return saved;
  } catch {
    /* ignore */
  }
  // 브라우저 언어 감지 (지원 언어만, 나머지는 한국어 폴백)
  const nav = (typeof navigator !== "undefined" ? navigator.language || "" : "")
    .toLowerCase()
    .slice(0, 2);
  return SUPPORTED_CODES.has(nav) ? nav : "ko";
}

i18n.use(initReactI18next).init({
  resources: {
    ko: { translation: ko },
    en: { translation: en },
    ja: { translation: ja },
    zh: { translation: zh },
    es: { translation: es },
    fr: { translation: fr },
    de: { translation: de },
    pt: { translation: pt },
    ru: { translation: ru },
    hi: { translation: hi },
    id: { translation: id },
  },
  lng: detectLang(),
  fallbackLng: "ko",
  interpolation: { escapeValue: false },
});

export function changeLang(code: string) {
  if (!SUPPORTED_CODES.has(code)) return;
  i18n.changeLanguage(code);
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    /* ignore */
  }
}

export default i18n;
