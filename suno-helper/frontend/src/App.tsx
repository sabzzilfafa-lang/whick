import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import AlbumsPage from "./pages/AlbumsPage";
import AlbumDetailPage from "./pages/AlbumDetailPage";
import SongPage from "./pages/SongPage";
import ProfilesPage from "./pages/ProfilesPage";
import SettingsPage from "./pages/SettingsPage";
import AnalyzePage from "./pages/AnalyzePage";
import SearchPage from "./pages/SearchPage";
import StudioPage from "./pages/StudioPage";
import EditorPage from "./pages/EditorPage";
import WebLaunchGate from "./components/WebLaunchGate";

export default function App() {
  const [gateChecked, setGateChecked] = useState(false);
  const [gated, setGated] = useState(false);

  useEffect(() => {
    let alive = true;
    // 웹 실행 흐름(웹 대시보드의 실행 버튼 → suno-helper://)으로 열렸는지 확인.
    // 로컬 직접 접속(주소창에 127.0.0.1:8765 입력)은 차단한다.
    fetch("/api/local/status", { method: "GET" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!alive) return;
        const webInstall = !!(d && d.web_launch);
        const launchFromWeb =
          new URLSearchParams(window.location.search).get("launch") === "web";
        setGated(webInstall && !launchFromWeb);
        setGateChecked(true);
      })
      .catch(() => {
        // status 조회 실패 = 기동 직후 등 — 게이트 보류 (차단하지 않음)
        if (alive) {
          setGated(false);
          setGateChecked(true);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  if (!gateChecked) return null;
  if (gated) return <WebLaunchGate />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="albums" element={<AlbumsPage />} />
        <Route path="albums/:id" element={<AlbumDetailPage />} />
        <Route path="songs/:id" element={<SongPage />} />
        <Route path="profiles" element={<ProfilesPage />} />
        <Route path="analyze" element={<AnalyzePage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="studio" element={<StudioPage />} />
        <Route path="editor" element={<EditorPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
