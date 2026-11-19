import { useEffect } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Icon } from "./components/Icon";
import { TopBar } from "./components/TopBar";
import { SetupCard } from "./components/SetupCard";
import { CreditsCard } from "./components/CreditsCard";
import { RecentProjects } from "./components/RecentProjects";
import { useProjects } from "./store/projects";

function ProjectCount() {
  const n = useProjects((s) => s.projects.length);
  return n > 0 ? <span className="count">{n}</span> : null;
}
import { AccountPage, ForgotPage, LegalPage, LoginPage, ResetPage, SignupPage } from "./pages/AuthPages";
import { EditorPage } from "./pages/EditorPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { AdminPage } from "./pages/AdminPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SetupPage } from "./pages/SetupPage";
import { useAuth } from "./store/auth";

export function App() {
  const { account, error, load, expire, logout } = useAuth();
  const location = useLocation();

  useEffect(() => {
    void load();
    window.addEventListener("avc:unauthorized", expire);
    return () => window.removeEventListener("avc:unauthorized", expire);
  }, [load, expire]);

  if (!account) {
    return <main className="container">{error ? <p className="alert" role="alert">{error}</p> : <p className="muted">Loading…</p>}</main>;
  }
  const hosted = account.mode === "hosted";
  const user = account.user;
  const inEditor = /^\/projects\//.test(location.pathname);
  const showNav = !hosted || !!user;

  const routes =
    hosted && !user ? (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot" element={<ForgotPage />} />
        <Route path="/reset" element={<ResetPage />} />
        <Route path="/terms" element={<LegalPage kind="terms" />} />
        <Route path="/privacy" element={<LegalPage kind="privacy" />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
      </Routes>
    ) : (
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/new" element={<NewProjectPage />} />
        {!hosted && <Route path="/setup" element={<SetupPage />} />}
        <Route path="/projects/:id" element={<EditorPage />} />
        {hosted && <Route path="/account" element={<AccountPage />} />}
        {hosted && user?.admin && <Route path="/admin" element={<AdminPage />} />}
        {hosted && <Route path="/terms" element={<LegalPage kind="terms" />} />}
        {hosted && <Route path="/privacy" element={<LegalPage kind="privacy" />} />}
        {hosted && <Route path="/login" element={<Navigate to="/" replace />} />}
        <Route path="*" element={<p className="muted">Page not found. <Link to="/">Back to projects</Link></p>} />
      </Routes>
    );

  const authPage = /^\/(login|signup|forgot|reset|verify)\b/.test(location.pathname);
  if (!showNav && authPage) return <div className="shell shell-bare shell-auth">{routes}</div>;
  if (!showNav) {
    return (
      <div className="shell shell-bare">
        <header className="topbar"><Link to="/" className="brand"><span className="brand-mark" aria-hidden="true" />AI Video Creator</Link></header>
        <main className="container">{routes}</main>
      </div>
    );
  }
  return (
    <div className={`shell${inEditor ? " shell-editor" : ""}`}>
      {!inEditor && (
        <aside className="sidebar">
          <Link to="/" className="brand"><span className="brand-mark" aria-hidden="true" />AI Video Creator</Link>
          <div className="workspace">
            <span className="workspace-mark" aria-hidden="true">{hosted ? (user?.email ?? "W").slice(0, 1).toUpperCase() : "L"}</span>
            <span><strong>{hosted ? "Your workspace" : "Local workspace"}</strong><span className="muted">{hosted ? "Personal" : "This computer"}</span></span>
          </div>
          <nav className="side-nav" aria-label="Main">
            <span className="side-label">Workspace</span>
            <NavLink to="/" end><Icon name="grid" />Projects<ProjectCount /></NavLink>
            <NavLink to="/new"><Icon name="plus" />New project</NavLink>
            {!hosted && <NavLink to="/setup"><Icon name="settings" />Settings</NavLink>}
            {hosted && user?.admin && <NavLink to="/admin"><Icon name="user" />Accounts</NavLink>}
          </nav>
          <RecentProjects />
          {!hosted && <SetupCard />}
          {hosted && <CreditsCard />}
          {hosted && user && (
            <div className="profile">
              <NavLink to="/account" className="profile-link" title="Your account">
                <span className="profile-avatar" aria-hidden="true">{(user.email ?? "?").slice(0, 1).toUpperCase()}</span>
                <span className="profile-text">
                  <span className="profile-email">{user.email}</span>
                  <span className="profile-role">{user.admin ? "Administrator" : "Your account"}</span>
                </span>
              </NavLink>
              <button className="profile-out" type="button" onClick={() => void logout()}><Icon name="logout" size={16} />Log out</button>
            </div>
          )}
        </aside>
      )}
      <main className={inEditor ? "editor-main" : "shell-main"}>
        {inEditor ? routes : (
          <>
            <TopBar workspace={hosted ? "Your workspace" : "Local workspace"} user={user?.email ?? null} />
            <div className="container">{routes}</div>
          </>
        )}
      </main>
    </div>
  );
}
