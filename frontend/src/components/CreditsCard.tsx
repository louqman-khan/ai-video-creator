import { Link } from "react-router-dom";
import { creditsText, resetLabel } from "../credits";
import { useAuth } from "../store/auth";
import { Icon } from "./Icon";

/** Sidebar card of a hosted account: the plan, how many credits this month's videos have used, when they renew. */
export function CreditsCard() {
  const c = useAuth((s) => s.account?.usage?.credits);
  if (!c) return null;
  const pct = c.unlimited || c.monthly === 0 ? 0 : Math.min(100, Math.round((c.used / c.monthly) * 100));
  const low = !c.unlimited && c.remaining <= Math.max(1, Math.round(c.monthly * 0.2));
  return (
    <div className={`credits${low ? " credits-low" : ""}`} aria-label="Credits">
      <p className="credits-plan"><Icon name="credit" size={16} /><strong>{c.plan} plan</strong></p>
      <p className="muted small">{creditsText(c)} this month.</p>
      {!c.unlimited && (
        <div className="credits-bar" role="progressbar" aria-label="Credits used" aria-valuemin={0} aria-valuemax={c.monthly} aria-valuenow={c.used}><span style={{ width: `${pct}%` }} /></div>
      )}
      <p className="muted small">{c.unlimited ? "No limit on your account." : `${c.remaining} left · renews ${resetLabel(c.resets_on)}`}</p>
      <Link to="/account" className="credits-link">Manage plan<Icon name="chevron" size={14} /></Link>
    </div>
  );
}
