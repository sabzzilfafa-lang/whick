import { useEffect, useState } from "react";
import { updateApi, type UpdateInfo } from "../api";
import { useLang } from "../lib/i18n";

/** 새 버전 배너 — 기동 1회 /api/version 체크, 새 버전 있으면 사이드바 하단에 표시 (2026-09-09) */
export default function UpdateBanner() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const { t } = useLang();

  useEffect(() => {
    let alive = true;
    updateApi
      .check()
      .then((r) => {
        if (alive && r?.update) setInfo(r);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  if (!info?.update) return null;
  const u = info.update;

  return (
    <a
      className="update-banner"
      href={u.download_url || "https://whick.org/suno.html"}
      target="_blank"
      rel="noreferrer"
      title={u.notes || t("새 버전 다운로드")}
    >
      <span className="update-banner-dot" />
      <span className="update-banner-text">
        v{u.version} {t("업데이트 가능")}
        <small>
          {t("클릭하여 다운로드 · 현재")} v{u.current}
        </small>
      </span>
    </a>
  );
}
