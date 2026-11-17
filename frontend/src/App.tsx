import { useEffect } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AccountPage, ForgotPage, LegalPage, LoginPage, ResetPage, SignupPage, VerifyPage } from "./pages/AuthPages";
import { EditorPage } from "./pages/EditorPage";
import { NewProjectPage } from "./pages/NewProjectPage";
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

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">AI Video Creator</Link>
        {hosted && user && (
          <nav className="topbar-user" aria-label="Account">
            <Link to="/account">{user.email}</Link>
            <button className="btn" type="button" onClick={() => void logout()}>Log out</button>
          </nav>
        )}
      </header>
      <main className="container">
        {hosted && !user ? (
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/verify" element={<VerifyPage />} />
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
            {hosted && <Route path="/terms" element={<LegalPage kind="terms" />} />}
            {hosted && <Route path="/privacy" element={<LegalPage kind="privacy" />} />}
            {hosted && <Route path="/login" element={<Navigate to="/" replace />} />}
            <Route path="*" element={<p className="muted">Page not found. <Link to="/">Back to projects</Link></p>} />
          </Routes>
        )}
      </main>
    </>
  );
}
