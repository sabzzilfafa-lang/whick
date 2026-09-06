import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QueueBanner from "./QueueBanner";

export default function Layout() {
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const fluid = pathname.startsWith("/editor");
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <h1>{t("app.name")}</h1>
          <p>{t("app.tagline")}</p>
        </div>
        <nav>
          <NavLink to="/" className="nav-link" end>{t("nav.home")}</NavLink>
          <NavLink to="/albums" className="nav-link">{t("nav.albums")}</NavLink>
          <NavLink to="/profiles" className="nav-link">{t("nav.profiles")}</NavLink>
          <NavLink to="/editor" className="nav-link">{t("nav.editor")}</NavLink>
          <NavLink to="/studio" className="nav-link">{t("nav.studio")}</NavLink>
          <NavLink to="/analyze" className="nav-link">{t("nav.analyze")}</NavLink>
          <NavLink to="/search" className="nav-link">{t("nav.search")}</NavLink>
          <NavLink to="/settings" className="nav-link">{t("nav.settings")}</NavLink>
        </nav>
      </aside>
      <main className={fluid ? "main-content main-content-fluid" : "main-content"}>
        <QueueBanner />
        <Outlet />
      </main>
    </div>
  );
}
