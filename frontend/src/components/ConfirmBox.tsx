import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import { useT } from "../i18n";

const COOLDOWN = 45;

/** "Check your e-mail": the six digits from the e-mail confirm the address too (no need to switch to the same browser). Used after sign-up and when a log-in is refused because the address is not confirmed. */
export function ConfirmBox({ email, onDone, onOtherAddress }: { email: string; onDone: (message: string) => void; onOtherAddress?: () => void }) {
  const { t, lang } = useT();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [wait, setWait] = useState(COOLDOWN);

  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  const confirm = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      onDone((await api.verifyCode(email, value)).message);
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");
      setCode("");
    } finally {
      setBusy(false);
    }
  };
  const change = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, 6);
    setCode(digits);
    if (digits.length === 6 && !busy) void confirm(digits);   // six digits: no need to press anything
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (code.length === 6) void confirm(code);
  };
  const resend = async () => {
    setError(null);
    try {
      await api.resend(email, lang);
      setSent(true);
      setWait(COOLDOWN);
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");
    }
  };

  return (
    <div className="confirm">
      <p className="confirm-lead">{t("We sent a confirmation e-mail to")} <strong dir="ltr">{email}</strong></p>
      <p className="muted small">{t("Click the button in the e-mail, or type the 6-digit code here.")}</p>
      <form onSubmit={submit} className="form" noValidate>
        <label className="field">
          <span className="label">{t("6-digit code")}</span>
          <input className="code-input" dir="ltr" inputMode="numeric" autoComplete="one-time-code" maxLength={7} placeholder="000000" value={code} disabled={busy} onChange={(e) => change(e.target.value)} />
        </label>
        {error && <p className="alert" role="alert">{t(error)}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy || code.length !== 6}>{busy ? t("Confirming…") : t("Confirm")}</button>
      </form>
      <div className="confirm-actions">
        <button className="btn btn-quiet" type="button" disabled={wait > 0} onClick={() => void resend()}>
          {wait > 0 ? `${t("Send a new e-mail")} (${wait})` : t("Send a new e-mail")}
        </button>
        {onOtherAddress && <button className="btn btn-quiet" type="button" onClick={onOtherAddress}>{t("Use another address")}</button>}
      </div>
      {sent && <p className="muted small" role="status">{t("If that is possible, an e-mail is on its way. Check your inbox (and the spam folder).")}</p>}
      <p className="muted small">{t("Check the spam folder if it does not arrive within a minute.")}</p>
    </div>
  );
}
