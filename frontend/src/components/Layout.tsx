import { NavLink, Outlet, useLocation } from "react-router-dom";
import QueueBanner from "./QueueBanner";
import UpdateBanner from "./UpdateBanner";
import SidebarVersion from "./SidebarVersion";
import { useLang, LangSelect } from "../lib/i18n";

export default function Layout() {
  const { pathname } = useLocation();
  const { t } = useLang();
  const fluid = pathname.startsWith("/editor");
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-row">
            <img src="/whick-mark.png" alt="Whick" className="sidebar-logo-icon" />
            <h1>Suno Helper</h1>
          </div>
          <p>{t("수노 음악 제작 도우미")}</p>
        </div>
        <nav>
          <NavLink to="/" className="nav-link" end>{t("홈")}</NavLink>
          <NavLink to="/albums" className="nav-link">{t("앨범")}</NavLink>
          <NavLink to="/profiles" className="nav-link">{t("스타일 프리셋")}</NavLink>
          <NavLink to="/editor" className="nav-link">{t("영상 편집")}</NavLink>
          <NavLink to="/studio" className="nav-link">{t("유튜브 스튜디오")}</NavLink>
          <NavLink to="/analyze" className="nav-link">{t("취향 곡 분석")}</NavLink>
          <NavLink to="/search" className="nav-link">{t("검색")}</NavLink>
          <NavLink to="/settings" className="nav-link">{t("사용자 설정")}</NavLink>
        </nav>
        <LangSelect />
        <UpdateBanner />
        <SidebarVersion />
      </aside>
      <main className={fluid ? "main-content main-content-fluid" : "main-content"}>
        <QueueBanner />
        <Outlet />
        <footer className="app-footer">
          <img src="/whick-mark.png" alt="" className="app-footer-mark" />
          <a href="https://whick.org" target="_blank" rel="noreferrer" className="app-footer-link">
            whick.org
          </a>
        </footer>
      </main>
    </div>
  );
}
