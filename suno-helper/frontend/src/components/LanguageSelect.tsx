import { useTranslation } from "react-i18next";
import { changeLang, SUPPORTED_LANGS } from "../i18n";

export function LanguageSelect() {
  const { i18n } = useTranslation();
  return (
    <select
      className="lang-select"
      value={i18n.language.startsWith("ko") ? "ko" : i18n.language}
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
