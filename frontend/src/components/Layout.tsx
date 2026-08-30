import { NavLink, Outlet, useLocation } from "react-router-dom";
import QueueBanner from "./QueueBanner";

export default function Layout() {
  const { pathname } = useLocation();
  const fluid = pathname.startsWith("/editor");
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <h1>Suno Helper</h1>
          <p>수노 음악 제작 도우미</p>
        </div>
        <nav>
          <NavLink to="/" className="nav-link" end>홈</NavLink>
          <NavLink to="/albums" className="nav-link">앨범</NavLink>
          <NavLink to="/profiles" className="nav-link">스타일 프리셋</NavLink>
          <NavLink to="/editor" className="nav-link">영상 편집</NavLink>
          <NavLink to="/studio" className="nav-link">유튜브 스튜디오</NavLink>
          <NavLink to="/analyze" className="nav-link">취향 곡 분석</NavLink>
          <NavLink to="/search" className="nav-link">검색</NavLink>
          <NavLink to="/settings" className="nav-link">사용자 설정</NavLink>
        </nav>
      </aside>
      <main className={fluid ? "main-content main-content-fluid" : "main-content"}>
        <QueueBanner />
        <Outlet />
      </main>
    </div>
  );
}
