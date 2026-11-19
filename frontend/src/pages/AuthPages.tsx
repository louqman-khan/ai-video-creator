import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ConfirmBox } from "../components/ConfirmBox";
import { Icon } from "../components/Icon";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { useT } from "../i18n";
import { useAuth } from "../store/auth";
import { creditsText, plural, resetLabel } from "../credits";

const message = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");

/** Every sign-in page: a calm brand side with what the product does, and the form beside it (stacked on a phone). English or Urdu (right to left). */
function Card({ title, children }: { title: string; children: ReactNode }) {
  const { t, lang, dir } = useT();
  return (
    <div className="auth-split" dir={dir} lang={lang}>
      <aside className="auth-brand" aria-label="About AI Video Creator">
        <Link to="/" className="brand" dir="ltr"><span className="brand-mark" aria-hidden="true" />AI Video Creator</Link>
        <div className="auth-pitch">
          <p className="eyebrow">{t("Your studio, in motion")}</p>
          <p className="auth-headline">{t("Turn the words in your head into a video people can watch.")}</p>
          <ul className="auth-points">
            <li><Icon name="check" size={16} />{t("Start from a script or a recording")}</li>
            <li><Icon name="check" size={16} />{lang === "ur" ? t("Captions in English and اردو, shaped correctly") : <>Captions in English and <span dir="rtl" lang="ur">اردو</span>, shaped correctly</>}</li>
            <li><Icon name="check" size={16} />{t("Pictures found and timed for you")}</li>
            <li><Icon name="check" size={16} />{t("A full editor when you want control")}</li>
          </ul>
        </div>
        <p className="auth-sample" dir="rtl" lang="ur">ہر کہانی ایک منظر سے شروع ہوتی ہے</p>
      </aside>
      <main className="auth-form">
        <div className="auth-top"><LanguageSwitch /></div>
        <section className="auth-card">
          <h1>{t(title)}</h1>
          {children}
        </section>
      </main>
    </div>
  );
}

function Field({ id, label, type = "text", value, onChange, autoComplete, hint, required = true }: {
  id: string; label: string; type?: string; value: string; onChange: (v: string) => void; autoComplete?: string; hint?: string; required?: boolean;
}) {
  const { t } = useT();
  return (
    <div className="field">
      <label className="label" htmlFor={id}>{t(label)}</label>
      <input id={id} type={type} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} required={required}
        aria-describedby={hint ? `${id}-hint` : undefined} spellCheck={false} dir={type === "email" || type === "password" ? "ltr" : undefined} />
      {hint && <small id={`${id}-hint`} className="muted">{t(hint)}</small>}
    </div>
  );
}

export function LoginPage() {
  const { t } = useT();
  const load = useAuth((s) => s.load);
  const navigate = useNavigate();
  const loc = useLocation();
  const next = (loc.state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const signups = useAuth((s) => s.account?.signups);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setUnconfirmed(false);
    try {
      await api.login({ email, password });
      await load();
      navigate(next, { replace: true });
    } catch (er) {
      setError(message(er));
      setUnconfirmed(er instanceof ApiError && er.status === 403);   // the address has not been confirmed yet: offer the code box
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Log in">
      <form onSubmit={submit} className="form" noValidate>
        <Field id="email" label="E-mail" type="email" value={email} onChange={setEmail} autoComplete="username" />
        <Field id="password" label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
        {confirmed && <p className="notice" role="status">{t(confirmed)}</p>}
        {error && <p className="alert" role="alert">{t(error)}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy || !email || !password}>{busy ? t("Logging in…") : t("Log in")}</button>
      </form>
      {unconfirmed && !confirmed && <ConfirmBox email={email} onDone={(m) => { setConfirmed(m); setUnconfirmed(false); setError(null); }} />}
      <p className="small"><Link to="/forgot">{t("Forgot your password?")}</Link>{signups !== "closed" && <> · <Link to="/signup">{t("Create an account")}</Link></>}</p>
    </Card>
  );
}

export function SignupPage() {
  const { t, lang } = useT();
  const signups = useAuth((s) => s.account?.signups);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [terms, setTerms] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (signups === "closed") return <Card title="Sign-ups are closed"><p>{t("New accounts cannot be created at the moment.")}</p><p><Link to="/login">{t("Log in")}</Link></p></Card>;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDone((await api.signup({ email, password, invite, terms, lang })).message);
    } catch (er) {
      setError(message(er));
    } finally {
      setBusy(false);
    }
  };
  if (confirmed) return <Card title="E-mail confirmed"><p role="status">{t(confirmed)}</p><p><Link className="btn btn-primary" to="/login">{t("Go to log in")}</Link></p></Card>;
  if (done) {
    return (
      <Card title="Check your e-mail">
        <p role="status" className="sr-only">{t(done)}</p>
        <ConfirmBox email={email.trim().toLowerCase()} onDone={setConfirmed} onOtherAddress={() => setDone(null)} />
        <p className="small"><Link to="/login">{t("Go to log in")}</Link></p>
      </Card>
    );
  }
  return (
    <Card title="Create an account">
      <form onSubmit={submit} className="form" noValidate>
        <Field id="email" label="E-mail" type="email" value={email} onChange={setEmail} autoComplete="email" />
        <Field id="password" label="Password" type="password" value={password} onChange={setPassword} autoComplete="new-password" hint="At least 10 characters. A few random words is a good password." />
        {signups === "invite" && <Field id="invite" label="Invitation code" value={invite} onChange={setInvite} autoComplete="off" />}
        <label className="check">
          <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
          {lang === "ur"
            ? <span>میں <Link to="/terms" target="_blank">استعمال کی شرائط</Link> اور <Link to="/privacy" target="_blank">رازداری کی پالیسی</Link> سے متفق ہوں۔</span>
            : <span>I accept the <Link to="/terms" target="_blank">terms of use</Link> and the <Link to="/privacy" target="_blank">privacy policy</Link>.</span>}
        </label>
        {error && <p className="alert" role="alert">{t(error)}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy || !email || !password || !terms}>{busy ? t("Creating…") : t("Create account")}</button>
      </form>
      <p className="small">{t("Already have an account?")} <Link to="/login">{t("Log in")}</Link></p>
    </Card>
  );
}

export function VerifyPage() {
  const { t } = useT();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      setState({ ok: true, text: (await api.verifyEmail(token)).message });
    } catch (e) {
      setState({ ok: false, text: message(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Confirm your e-mail address">
      {!state && <button className="btn btn-primary" type="button" disabled={busy || !token} onClick={() => void go()}>{busy ? t("Confirming…") : t("Confirm my address")}</button>}
      {!token && <p className="alert" role="alert">{t("This link is incomplete. Open the whole link from the e-mail.")}</p>}
      {state && <p role={state.ok ? "status" : "alert"} className={state.ok ? "" : "alert"}>{t(state.text)}</p>}
      {state?.ok && <p><Link className="btn btn-primary" to="/login">{t("Log in")}</Link></p>}
    </Card>
  );
}

export function ForgotPage() {
  const { t, lang } = useT();
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setDone((await api.forgotPassword(email, lang)).message);
    } catch (er) {
      setError(message(er));
    }
  };
  return (
    <Card title="Reset your password">
      {done ? <p role="status">{t(done)}</p> : (
        <form onSubmit={submit} className="form" noValidate>
          <Field id="email" label="E-mail" type="email" value={email} onChange={setEmail} autoComplete="email" />
          {error && <p className="alert" role="alert">{t(error)}</p>}
          <button className="btn btn-primary" type="submit" disabled={!email}>{t("Send me a link")}</button>
        </form>
      )}
      <p className="small"><Link to="/login">{t("Back to log in")}</Link></p>
    </Card>
  );
}

export function ResetPage() {
  const { t } = useT();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setDone((await api.resetPassword(token, password)).message);
    } catch (er) {
      setError(message(er));
    }
  };
  return (
    <Card title="Choose a new password">
      {done ? <><p role="status">{t(done)}</p><p><Link className="btn btn-primary" to="/login">{t("Log in")}</Link></p></> : (
        <form onSubmit={submit} className="form" noValidate>
          <Field id="password" label="New password" type="password" value={password} onChange={setPassword} autoComplete="new-password" hint="At least 10 characters." />
          {!token && <p className="alert" role="alert">{t("This link is incomplete. Open the whole link from the e-mail.")}</p>}
          {error && <p className="alert" role="alert">{t(error)}</p>}
          <button className="btn btn-primary" type="submit" disabled={!password || !token}>{t("Change password")}</button>
        </form>
      )}
    </Card>
  );
}

const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`);

export function AccountPage() {
  const account = useAuth((s) => s.account);
  const load = useAuth((s) => s.load);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  if (!account?.user) return <Navigate to="/login" replace />;
  const u = account.usage;
  const remove = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.deleteAccount(password);
      await load();
    } catch (er) {
      setError(message(er));
    }
  };
  return (
    <section>
      <div className="page-head"><h1>Your account</h1></div>
      <div className="panel">
        <p>Signed in as <strong>{account.user.email}</strong></p>
        {u?.credits && (
          <div className="credits-line">
            <strong>{u.credits.plan} plan</strong>
            <span>{creditsText(u.credits)} this month{u.credits.unlimited ? "" : `; ${plural(u.credits.remaining, "credit", "credits")} left, renewing ${resetLabel(u.credits.resets_on)}`}.</span>
            <span className="muted small">A video costs 1 credit for every {u.credits.minutes_per_credit === 1 ? "minute" : `${u.credits.minutes_per_credit} minutes`} of narration, rounded up (at least 1). A video that cannot be made gives its credits back.</span>
          </div>
        )}
        {u && (
          <ul className="small">
            <li>Projects: {u.projects} of {u.max_projects}</li>
            <li>Storage: {mb(u.storage_bytes)} of {mb(u.max_storage_bytes)}</li>
            <li>Exports: up to {u.max_exports_per_day} a day</li>
          </ul>
        )}
      </div>
      <div className="panel">
        <h2>Your data</h2>
        <p className="muted small">Download your projects, uploads and exports as one zip file.</p>
        <a className="btn" href={api.accountExportUrl} download>Download my data</a>
      </div>
      <div className="panel">
        <h2>Delete the account</h2>
        <p className="muted small">This deletes your account and every project in it. It cannot be undone.</p>
        {!confirming ? <button className="btn" type="button" onClick={() => setConfirming(true)}>Delete my account…</button> : (
          <form onSubmit={remove} className="form" noValidate>
            <Field id="confirm-password" label="Type your password to confirm" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
            {error && <p className="alert" role="alert">{error}</p>}
            <div className="card-actions">
              <button className="btn btn-danger" type="submit" disabled={!password}>Delete everything</button>
              <button className="btn" type="button" onClick={() => { setConfirming(false); setPassword(""); setError(null); }}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

export function LegalPage({ kind }: { kind: "terms" | "privacy" }) {
  return kind === "terms" ? (
    <Card title="Terms of use (draft)">
      <p className="alert small">This is a plain-language draft for the operator to review with a lawyer before the site goes public.</p>
      <ul>
        <li>You may only upload audio, pictures and video that you have the right to use. You confirm this when you upload.</li>
        <li>Stock media found through the app comes from free-to-reuse sources; the credits file lists what must be credited. Keeping those credits is your responsibility.</li>
        <li>Do not use the service for unlawful, hateful or deceptive content, or to impersonate a real person.</li>
        <li>We may delete accounts that break these rules, and projects that stay unused for a long time.</li>
        <li>The service is provided as it is, without a promise that it is always available or that results are error-free (speech recognition and computer voices make mistakes: check your video).</li>
      </ul>
    </Card>
  ) : (
    <Card title="Privacy policy (draft)">
      <p className="alert small">This is a plain-language draft for the operator to review with a lawyer before the site goes public.</p>
      <ul>
        <li>We keep your e-mail address, a salted hash of your password, and the projects you create (your uploads, scripts, captions, timelines and exports).</li>
        <li>Your scripts and narration text may be sent to outside services that do part of the work (for example a language model for planning scenes, stock-media search). We do not sell your data.</li>
        <li>You can download all your data and delete your account and all projects at any time from the Account page.</li>
        <li>We use one cookie to keep you logged in. We do not use advertising or tracking cookies.</li>
      </ul>
    </Card>
  );
}
