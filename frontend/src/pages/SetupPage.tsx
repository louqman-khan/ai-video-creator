import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type SetupStatus } from "../api/client";

const Tick = ({ ok }: { ok: boolean }) => <span aria-label={ok ? "ready" : "not ready"}>{ok ? "✓" : "○"}</span>;

export function SetupPage() {
  const [st, setSt] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gemini, setGemini] = useState("");
  const [pixabay, setPixabay] = useState("");
  const [size, setSize] = useState("small");
  const [saved, setSaved] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = () => api.setupStatus().then((s) => { setSt(s); return s; });
  useEffect(() => {
    refresh().then((s) => setSize(s.models.whisper_model), (e: Error) => setError(e.message));
  }, []);
  const running = st?.download.running ?? false;
  useEffect(() => {
    if (!running) return;
    timer.current = setInterval(() => void refresh().catch(() => undefined), 1500);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [running]);

  if (!st) return <section>{error ? <p className="alert" role="alert">{error}</p> : <p className="muted">Loading…</p>}</section>;

  const saveKeys = async () => {
    setError(null); setSaved(false);
    const body: { gemini_api_key?: string; pixabay_api_key?: string } = {};
    if (gemini.trim()) body.gemini_api_key = gemini.trim();
    if (pixabay.trim()) body.pixabay_api_key = pixabay.trim();
    try { setSt(await api.setupKeys(body)); setGemini(""); setPixabay(""); setSaved(true); } catch (e) { setError((e as Error).message); }
  };
  const download = async () => {
    setError(null);
    try { setSt(await api.setupModels({ whisper: size, clip: true })); } catch (e) { setError((e as Error).message); }
  };
  const m = st.models;

  return (
    <section>
      <div className="page-head"><h1>Setup</h1><Link className="btn" to="/">Back to projects</Link></div>
      {error && <p className="alert" role="alert">{error}</p>}
      <p className="muted">Everything stays on this computer{st.data_dir ? <> (in <code>{st.data_dir}</code>)</> : null}. Both keys are free.</p>

      <h2><Tick ok={st.keys.gemini_api_key} /> Scene planner key (Google Gemini)</h2>
      <p className="muted">Get a free key at aistudio.google.com/apikey. {st.keys.gemini_api_key ? "A key is saved." : "Not set yet."}</p>
      <label>Gemini API key <input type="password" autoComplete="off" value={gemini} onChange={(e) => setGemini(e.target.value)} placeholder={st.keys.gemini_api_key ? "(saved — type to replace)" : ""} /></label>

      <h2><Tick ok={st.keys.pixabay_api_key} /> Picture and video key (Pixabay)</h2>
      <p className="muted">Get a free key at pixabay.com/api/docs. {st.keys.pixabay_api_key ? "A key is saved." : "Not set yet."}</p>
      <label>Pixabay API key <input type="password" autoComplete="off" value={pixabay} onChange={(e) => setPixabay(e.target.value)} placeholder={st.keys.pixabay_api_key ? "(saved — type to replace)" : ""} /></label>
      <p><button className="btn btn-primary" type="button" onClick={() => void saveKeys()} disabled={!gemini.trim() && !pixabay.trim()}>Save keys</button> {saved && <span role="status">Saved.</span>}</p>

      <h2><Tick ok={m.whisper && m.rnnoise && m.clip} /> Models (one-time download)</h2>
      <ul>
        <li><Tick ok={m.whisper} /> Speech recognition ({m.whisper_model})</li>
        <li><Tick ok={m.rnnoise} /> Noise removal</li>
        <li><Tick ok={m.clip} /> Picture ranking</li>
        <li><Tick ok={!!m.face} /> Face finding (smart crop)</li>
      </ul>
      <label>Speech model size{" "}
        <select value={size} onChange={(e) => setSize(e.target.value)} disabled={running}>
          {Object.entries(st.whisper_sizes_mb).map(([k, mb]) => <option key={k} value={k}>{k} (~{mb} MB){k === "small" ? " — recommended" : ""}</option>)}
        </select>
      </label>
      <p><button className="btn btn-primary" type="button" onClick={() => void download()} disabled={running}>{running ? "Downloading…" : "Download models"}</button></p>
      {running && <p role="status">{st.download.message}</p>}
      {st.download.error && <p className="alert" role="alert">{st.download.error}</p>}
      {!st.ffmpeg && <p className="alert" role="alert">The video engine (FFmpeg) was not found. Reinstall the app.</p>}
    </section>
  );
}
