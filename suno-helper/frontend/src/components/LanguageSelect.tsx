import { useTranslation } from "react-i18next";
import { changeLang, SUPPORTED_LANGS } from "../i18n";

export function LanguageSelect() {
  const { i18n } = useTranslation();
  const current = i18n.language.slice(0, 2);
  const value = SUPPORTED_LANGS.some((l) => l.code === current) ? current : "ko";
  return (
    <select
      className="lang-select"
      value={value}
      onChange={(e) => changeLang(e.target.value)}
      aria-label="Language"
    >
      {SUPPORTED_LANGS.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  );
}
