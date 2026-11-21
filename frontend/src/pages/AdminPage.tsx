import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, ApiError, type ActivityRow, type AdminUser } from "../api/client";
import { Icon } from "../components/Icon";
import { useAuth } from "../store/auth";

const mb = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);
const day = (t: number | null) => (t ? new Date(t * 1000).toLocaleDateString() : "never");
const when = (t: number) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const message = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");

/** The operator's page (hosted sites, administrators only): who has an account, what they use, bonus credits, switching an account off. */
export function AdminPage() {
  const me = useAuth((s) => s.account);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [giving, setGiving] = useState<string | null>(null);   // the account whose "add credits" box is open
  const [amount, setAmount] = useState("5");
  const [query, setQuery] = useState("");
  const [watching, setWatching] = useState<AdminUser | null>(null);   // whose activity is shown (null: everybody)
  const [log, setLog] = useState<ActivityRow[] | null>(null);

  const loadLog = useCallback((u: AdminUser | null) => api.adminActivity(u?.id).then((r) => setLog(r), (e) => setError(message(e))), []);
  useEffect(() => {
    void loadLog(watching);
  }, [loadLog, watching]);

  const load = useCallback(() => api.adminUsers().then((u) => { setUsers(u); setError(null); }, (e) => setError(message(e))), []);
  useEffect(() => {
    void load();
  }, [load]);

  if (me && !(me.mode === "hosted" && me.user?.admin)) return <Navigate to="/" replace />;

  const give = async (e: FormEvent, u: AdminUser) => {
    e.preventDefault();
    const n = Number.parseInt(amount, 10);
    if (!Number.isFinite(n) || n === 0) return setError("Enter a whole number of credits (negative takes bonus credits back).");
    try {
      await api.adminGiveCredits(u.id, n);
      setNotice(`${n > 0 ? "Added" : "Took back"} ${Math.abs(n)} credit${Math.abs(n) === 1 ? "" : "s"} ${n > 0 ? "to" : "from"} ${u.email}.`);
      setGiving(null);
      setError(null);
      await load();
    } catch (er) {
      setError(message(er));
    }
  };
  const toggle = async (u: AdminUser) => {
    if (!u.disabled && !window.confirm(`Switch off ${u.email}? They are logged out at once and cannot log in until you switch the account on again.`)) return;
    try {
      await api.adminSetDisabled(u.id, !u.disabled);
      setNotice(`${u.email} is ${u.disabled ? "on" : "off"} again.`.replace("on again", "switched on").replace("off again", "switched off"));
      setError(null);
      await load();
    } catch (er) {
      setError(message(er));
    }
  };

  const shown = (users ?? []).filter((u) => u.email.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Operator</p>
          <h1>Accounts</h1>
          <p className="page-sub">Who is using the site, what they use, and bonus credits. Only administrators see this page.</p>
        </div>
      </div>
      {error && <p className="alert" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {users === null && !error && <p className="muted">Loading…</p>}
      {users && (
        <>
          <div className="toolbar">
            <label className="search">
              <Icon name="search" />
              <input type="text" placeholder="Find an account" aria-label="Find an account" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <span className="muted small">{shown.length} of {users.length} accounts</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Account</th><th>Credits this month</th><th>Projects</th><th>Storage</th><th>Last login</th><th><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {shown.map((u) => (
                  <tr key={u.id} className={u.disabled ? "row-off" : undefined}>
                    <td>
                      <strong>{u.email}</strong>
                      <span className="muted small">{u.role === "admin" ? "Administrator" : u.verified ? "Member" : "E-mail not confirmed"} · joined {day(u.created_at)}{u.disabled ? " · switched off" : ""}</span>
                    </td>
                    <td>
                      {u.credits.unlimited ? "Unlimited" : `${u.credits.used} used · ${u.credits.remaining} left`}
                      {!!u.credits.bonus && <span className="muted small"> (includes {u.credits.bonus} bonus)</span>}
                    </td>
                    <td>{u.projects}</td>
                    <td>{mb(u.storage_bytes)}</td>
                    <td>{day(u.last_login)}</td>
                    <td className="actions">
                      {giving === u.id ? (
                        <form className="inline-form" onSubmit={(e) => void give(e, u)}>
                          <label className="sr-only" htmlFor={`amt-${u.id}`}>Credits for {u.email}</label>
                          <input id={`amt-${u.id}`} type="number" value={amount} onChange={(e) => setAmount(e.target.value)} step={1} />
                          <button className="btn btn-primary" type="submit">Add</button>
                          <button className="btn" type="button" onClick={() => setGiving(null)}>Cancel</button>
                        </form>
                      ) : (
                        <>
                          {!u.credits.unlimited && <button className="btn" type="button" onClick={() => { setGiving(u.id); setAmount("5"); }} aria-label={`Add credits to ${u.email}`}>Add credits</button>}
                          <button className="btn btn-quiet" type="button" onClick={() => setWatching(watching?.id === u.id ? null : u)} aria-label={`Show what ${u.email} did`}>Activity</button>
                          {u.role !== "admin" && <button className="btn btn-quiet" type="button" onClick={() => void toggle(u)} aria-label={`${u.disabled ? "Switch on" : "Switch off"} ${u.email}`}>{u.disabled ? "Switch on" : "Switch off"}</button>}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="page-head" style={{ marginTop: 32 }}>
            <div>
              <h2>{watching ? `What ${watching.email} did` : "Recent activity"}</h2>
              <p className="page-sub">Sign-ins, projects, exports and edits, newest first. Page views and what people type are not recorded.</p>
            </div>
            {watching && <button className="btn" type="button" onClick={() => setWatching(null)}>Show everyone</button>}
            <button className="btn btn-quiet" type="button" onClick={() => void loadLog(watching)}>Refresh</button>
          </div>
          {log === null && <p className="muted">Loading…</p>}
          {log && log.length === 0 && <p className="muted">Nothing recorded yet.</p>}
          {log && log.length > 0 && (
            <div className="table-wrap">
              <table className="table" aria-label="Activity">
                <thead><tr><th>When</th>{!watching && <th>Account</th>}<th>What</th></tr></thead>
                <tbody>
                  {log.map((a) => (
                    <tr key={a.id}>
                      <td>{when(a.ts)}</td>
                      {!watching && <td>{a.email ?? "deleted account"}</td>}
                      <td>
                        {a.label}
                        {a.project_name && <span className="muted small"> · “{a.project_name}”</span>}
                        {a.detail && <span className="muted small"> · {a.detail}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
