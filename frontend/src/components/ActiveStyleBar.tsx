import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MusicProfile, api } from "../api";

export default function ActiveStyleBar() {
  const [active, setActive] = useState<MusicProfile | null>(null);

  const load = () => api.getActiveProfile().then(setActive);

  useEffect(() => {
    load();
    const handler = () => load();
    window.addEventListener("style-preset-changed", handler);
    return () => window.removeEventListener("style-preset-changed", handler);
  }, []);

  if (!active) {
    return (
      <div className="active-style-bar empty">
        <span>오늘의 스타일이 선택되지 않았습니다</span>
        <Link to="/profiles" className="btn btn-sm btn-secondary">스타일 선택</Link>
      </div>
    );
  }

  return (
    <div className="active-style-bar">
      <span className="active-style-emoji">{active.emoji || "🎵"}</span>
      <div className="active-style-info">
        <strong>현재 스타일: {active.name}</strong>
        <span>
          {[active.genre, active.mood, active.tempo_bpm && `${active.tempo_bpm} BPM`]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <Link to="/profiles" className="btn btn-sm btn-secondary">변경</Link>
    </div>
  );
}

export function notifyStyleChanged() {
  window.dispatchEvent(new Event("style-preset-changed"));
}
