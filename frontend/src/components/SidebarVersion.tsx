import { useEffect, useState } from "react";
import { updateApi } from "../api";

/** 사이드바 최하단 현재 버전 표시 (2026-09-09) — /api/version의 현재 버전만 표시 (UpdateBanner와 무관하게 항상 노출) */
export default function SidebarVersion() {
  const [version, setVersion] = useState("");

  useEffect(() => {
    let alive = true;
    updateApi
      .check()
      .then((r) => {
        if (alive) setVersion(String(r?.version || "").replace(/^v/, ""));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  if (!version) return null;
  return (
    <div className="sidebar-version" title="Suno Helper version">
      v{version}
    </div>
  );
}
