import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

type Usage = Awaited<ReturnType<typeof api.storage>>;
const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`);

/** How much disk the app uses, and a button that frees what can be made again. */
export function StoragePanel() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.storage().then(setUsage, () => undefined), []);
  useEffect(() => { void load(); }, [load]);
  if (!usage) return null;

  const clean = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.cleanStorage();
      setMessage(r.removed ? `Freed ${mb(r.freed)}.` : "Nothing to free up.");
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="panel storage-panel">
      <summary>Disk space: {mb(usage.total)} used{usage.reclaimable ? `, ${mb(usage.reclaimable)} can be freed` : ""}</summary>
      <ul className="small">
        {usage.items.map((i) => <li key={i.key}>{i.label}: {mb(i.bytes)}{i.reclaimable ? ` (${mb(i.reclaimable)} unused)` : ""}</li>)}
      </ul>
      <p className="muted small">Freeing space removes downloaded stock media and caches nothing uses any more. They are made again when needed. Your uploads, exports and edits are never touched.</p>
      <button className="btn" type="button" disabled={busy || usage.reclaimable === 0} onClick={() => void clean()}>{busy ? "Cleaning…" : "Free up space"}</button>
      {message && <p role="status" className="small">{message}</p>}
    </details>
  );
}
