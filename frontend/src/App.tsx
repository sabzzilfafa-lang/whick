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

export default function App() {
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
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
