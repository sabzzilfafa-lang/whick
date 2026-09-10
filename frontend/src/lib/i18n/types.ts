/** i18n 공통 타입 — 키는 한국어 원문 그 자체 (2026-09-09 재구축) */
export const LANGS = [
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

export type Lang = (typeof LANGS)[number]["code"];

/** 한국어 원문 → 번역문 매핑. 없는 키는 한국어 원문으로 fallback */
export type Dict = Record<string, string>;
