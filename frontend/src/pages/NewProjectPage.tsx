import { Link } from "react-router-dom";

// The upload form is task 3.3.
export function NewProjectPage() {
  return (
    <section>
      <div className="page-head">
        <h1>New project</h1>
      </div>
      <p className="muted">The upload form arrives in the next task.</p>
      <Link className="btn" to="/">
        Back to projects
      </Link>
    </section>
  );
}
