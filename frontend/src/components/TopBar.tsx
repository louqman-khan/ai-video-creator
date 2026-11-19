import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon } from "./Icon";
import { ThemeToggle } from "./ThemeToggle";

const TITLES: Record<string, string> = { "/": "Projects", "/new": "New project", "/setup": "Settings", "/account": "Account", "/terms": "Terms", "/privacy": "Privacy" };

/** The bar above every page: where you are (a breadcrumb) on the left; theme and who you are on the right. */
export function TopBar({ workspace, user }: { workspace: string; user: string | null }) {
  const { pathname } = useLocation();
  const here = TITLES[pathname] ?? "Page";
  const trail = pathname === "/" ? [here] : ["Projects", here];
  return (
    <header className="appbar">
      <nav className="crumbs" aria-label="Breadcrumb">
        <span className="crumb-root">{workspace}</span>
        {trail.map((t, i) => (
          <Fragment key={t}>
            <Icon name="chevron" size={14} />
            {i < trail.length - 1 ? <Link to="/">{t}</Link> : <span aria-current="page" className="crumb-here">{t}</span>}
          </Fragment>
        ))}
      </nav>
      <div className="appbar-right">
        <ThemeToggle />
        <span className="who" title={user ?? "This computer"}>
          <span className="avatar" aria-hidden="true">{(user ?? "Me").slice(0, 1).toUpperCase()}</span>
          <span className="who-name">{user ?? "This computer"}</span>
        </span>
      </div>
    </header>
  );
}
