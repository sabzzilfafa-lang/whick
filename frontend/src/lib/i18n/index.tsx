import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { DICTS } from "./dicts";
import { LANGS, type Lang } from "./types";

/**
 * Suno Helper UI 다국어 (2026-09-09 재구축)
 * - 키 = 한국어 원문. t("홈") → 한국어 모드에선 원문 그대로, 타 언어는 사전 조회
 * - 사전에 없는 문장은 한국어 원문으로 남는다 (점진 확장) — 키 노출 버그 원천 차단
 * - 저장: localStorage("suno_lang") · 최초 1회 navigator.language 자동 감지
 */

const STORAGE_KEY = "suno_lang";

export { LANGS };
export type { Lang } from "./types";

function detectLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && LANGS.some((l) => l.code === saved)) return saved as Lang;
  } catch {
    /* localStorage 불가 환경 */
  }
  const nav = (navigator.language || "ko").toLowerCase();
  const base = nav.split("-")[0];
  return (LANGS.some((l) => l.code === base) ? base : "ko") as Lang;
}

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (ko: string) => string;
}

const Ctx = createContext<LangCtx>({
  lang: "ko",
  setLang: () => {},
  t: (ko) => ko,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => detectLang());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      /* 무시 */
    }
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);

  const t = useCallback(
    (ko: string) => {
      if (lang === "ko") return ko;
      return DICTS[lang]?.[ko] ?? ko; // 미번역 → 한국어 원문 유지
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLang() {
  return useContext(Ctx);
}

/** 언어 선택 셀렉트 — 사이드바·설정 공용 */
export function LangSelect({ className }: { className?: string }) {
  const { lang, setLang } = useLang();
  return (
    <select
      className={className || "lang-select"}
      value={lang}
      onChange={(e) => setLang(e.target.value as Lang)}
      aria-label="Language"
    >
      {LANGS.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  );
}
