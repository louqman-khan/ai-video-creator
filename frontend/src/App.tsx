import { Link, Route, Routes } from "react-router-dom";
import { EditorPage } from "./pages/EditorPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";

export function App() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          AI Video Creator
        </Link>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/new" element={<NewProjectPage />} />
          <Route path="/projects/:id" element={<EditorPage />} />
          <Route path="*" element={<p className="muted">Page not found. <Link to="/">Back to projects</Link></p>} />
        </Routes>
      </main>
    </>
  );
}
