import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, DEFAULT_LIMITS, uploadProject, type Limits } from "../api/client";
import { Icon } from "../components/Icon";
import { ProgressBar } from "../components/ProgressBar";
import { costOfScript, costOfSeconds, plural } from "../credits";
import { useAuth } from "../store/auth";
import { useProjects } from "../store/projects";
import {
  buildForm, DEFAULT_VALUES, formatSize, validateAudioFile, validateScript, validateSpeak, type NewProjectValues,
} from "../newProject";

export function NewProjectPage() {
  const navigate = useNavigate();
  const upsert = useProjects((s) => s.upsert);
  const [limits, setLimits] = useState<Limits>(DEFAULT_LIMITS);
  const [values, setValues] = useState<NewProjectValues>(DEFAULT_VALUES);
  const [file, setFile] = useState<File | null>(null);
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"record" | "speak">(params.get("source") === "script" ? "speak" : "record");   // a recording, or a typed script spoken by a synthetic voice
  const [speech, setSpeech] = useState<string[]>([]);
  const [speechPaid, setSpeechPaid] = useState(false);   // the voice is an outside paid service
  const [paidOk, setPaidOk] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const credits = useAuth((s) => s.account?.usage?.credits);   // hosted accounts pay for each video in credits
  const [fileSeconds, setFileSeconds] = useState<number | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let live = true;
    api.health().then((h) => { if (live) { setLimits(h.limits); setSpeech(h.speech ?? []); setSpeechPaid(!!h.speech_paid); } }).catch(() => undefined); // keep defaults
    return () => {
      live = false;
      abortRef.current?.(); // leaving the page cancels a running upload
    };
  }, []);

  const set = <K extends keyof NewProjectValues>(key: K, value: NewProjectValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  const pick = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    const problem = validateAudioFile(f, limits);
    setFileError(problem);
    setFile(problem ? null : f);
    setFileSeconds(null);
    if (!problem && credits && !credits.unlimited) {   // the browser can read the length: that is what the credits are based on
      const url = URL.createObjectURL(f);
      const a = new Audio();
      a.preload = "metadata";
      a.onloadedmetadata = () => { setFileSeconds(Number.isFinite(a.duration) ? a.duration : null); URL.revokeObjectURL(url); };
      a.onerror = () => URL.revokeObjectURL(url);
      a.src = url;
    }
  };

  const scriptError = validateScript(values.script, limits);
  const speakError = mode === "speak" ? validateSpeak(values, speech) : null;
  const per = credits?.minutes_per_credit ?? 1;
  const cost = !credits || credits.unlimited ? null : mode === "speak" ? costOfScript(values.script, per) : fileSeconds !== null ? costOfSeconds(fileSeconds, per) : null;
  const short = cost !== null && credits !== undefined && cost > credits.remaining;   // the server refuses it too; this tells the person first
  const ready = (mode === "speak" ? !speakError && (!speechPaid || paidOk) : !!file) && !short;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ready || scriptError || uploading) return;
    setError(null);
    setUploading(true);
    setProgress(0);
    const up = uploadProject(buildForm(mode === "speak" ? null : file, values), setProgress);
    abortRef.current = up.abort;
    up.promise
      .then((project) => {
        abortRef.current = null;
        upsert(project);
        void useAuth.getState().load();   // the balance has changed
        navigate(`/projects/${project.id}`);
      })
      .catch((err: Error) => {
        abortRef.current = null;
        setUploading(false);
        setError(err.message);
      });
  };

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>New project</h1>
          <p className="page-sub">Start from your own recording, or type a script and let a voice read it. We find the pictures, time them and add captions.</p>
        </div>
      </div>

      <form className="np-grid" onSubmit={submit} noValidate>
        <div className="np-main">
        <div className="choices" role="radiogroup" aria-label="Where does the narration come from?">
          <label className={`choice${mode === "record" ? " choice-on" : ""}`}>
            <input type="radio" name="source" aria-label="I have a recording" checked={mode === "record"} disabled={uploading} onChange={() => setMode("record")} />
            <Icon name="upload" size={22} />
            <strong>I have a recording</strong>
            <span>Upload narration audio (Urdu or English).</span>
          </label>
          <label className={`choice${mode === "speak" ? " choice-on" : ""}`}>
            <input type="radio" name="source" aria-label="Speak my script with a computer voice" checked={mode === "speak"} disabled={uploading} onChange={() => setMode("speak")} />
            <Icon name="text" size={22} />
            <strong>Type a script</strong>
            <span>A computer voice reads it for you.</span>
          </label>
        </div>

        {mode === "record" && <div className={`panel dropzone${dragging ? " dropzone-on" : ""}`}
          onDragOver={(e) => { e.preventDefault(); if (!uploading) setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); if (!uploading) pick(e.dataTransfer.files?.[0]); }}>
          <label className="field">
            <span className="label">Narration audio</span>
            <input
              type="file"
              accept={limits.extensions.join(",")}
              disabled={uploading}
              onChange={(e) => pick(e.target.files?.[0])}
              aria-describedby="audio-help"
            />
          </label>
          <p id="audio-help" className="muted small">
            Drop a file here or choose one. {limits.extensions.join(" ")} · up to {limits.max_upload_mb} MB and {limits.max_audio_minutes} minutes.
          </p>
          {file && (
            <p className="small">
              Selected: <strong dir="auto">{file.name}</strong> ({formatSize(file.size)})
            </p>
          )}
          {fileError && (
            <p className="alert small" role="alert">
              {fileError}
            </p>
          )}
        </div>}

        <div className="panel">
          <label className="field">
            <span className="label">Project name (optional)</span>
            <input type="text" dir="auto" maxLength={80} value={values.name} disabled={uploading}
              onChange={(e) => set("name", e.target.value)} placeholder="Defaults to the file name" />
          </label>
        </div>

        <div className="panel">
          <label className="field">
            <span className="label">{mode === "speak" ? "Script to speak" : "Script (optional)"}</span>
            <textarea rows={6} dir="auto" value={values.script} disabled={uploading}
              onChange={(e) => set("script", e.target.value)}
              placeholder="Paste the exact text of your narration. Captions will use your spelling and punctuation; the timing still comes from the audio." />
          </label>
          <p className="muted small">
            {mode === "speak"
              ? `The voice reads this text and the video is built from it. Voices installed: ${speech.length ? speech.map((l) => (l === "ur" ? "Urdu" : "English")).join(", ") : "none"}. Choose the language below.`
              : "A script is matched to the audio you upload, so captions use your exact words."}
          </p>
          {mode === "speak" && speechPaid && (
            <label className="check">
              <input type="checkbox" checked={paidOk} disabled={uploading} onChange={(e) => setPaidOk(e.target.checked)} />
              The voice is an outside paid service: your script is sent to it and uses your quota there.
            </label>
          )}
          {speakError && (
            <p className="alert small" role="alert">
              {speakError}
            </p>
          )}
          {scriptError && (
            <p className="alert small" role="alert">
              {scriptError}
            </p>
          )}
        </div>

        </div>
        <aside className="np-side">
          <div className="panel">
            <h2>Video settings</h2>
          <div className="np-fields">
            <label className="field">
              <span className="label">Language</span>
              <select value={values.language} disabled={uploading}
                onChange={(e) => set("language", e.target.value as NewProjectValues["language"])}>
                {mode === "record" && <option value="">Detect automatically</option>}
                {mode === "speak" && <option value="">Choose…</option>}
                <option value="en">English</option>
                <option value="ur">Urdu (اردو)</option>
              </select>
            </label>
            <label className="field">
              <span className="label">Video format</span>
              <select value={values.aspect} disabled={uploading}
                onChange={(e) => set("aspect", e.target.value as NewProjectValues["aspect"])}>
                <option value="16:9">Landscape 16:9 (1920×1080)</option>
                <option value="9:16">Vertical 9:16 (1080×1920)</option>
              </select>
            </label>
          </div>
          </div>
          {credits && !credits.unlimited && (
            <div className={`np-credits${short ? " np-credits-short" : ""}`} role="status">
              <Icon name="credit" size={18} />
              <p>
                {cost === null ? <>A video uses 1 credit for every {credits.minutes_per_credit === 1 ? "minute" : `${credits.minutes_per_credit} minutes`} of narration (at least 1).</>
                  : short ? <><strong>Not enough credits.</strong> This video needs {cost}; you have {credits.remaining} left this month.</>
                  : <><strong>Uses {plural(cost, "credit", "credits")}.</strong> You have {credits.remaining} left this month.</>}
              </p>
            </div>
          )}
          <div className="np-note">
            <Icon name="check" size={18} />
            <p><strong>Made for both languages.</strong> English and Urdu captions keep their own reading direction, font and line breaks.</p>
          </div>
        <details className="panel">
          <summary>Audio and caption options</summary>
          {([
            ["captions", "Burn captions into the video"],
            ["clean", "Remove background noise"],
            ["normalize", "Even out the loudness (−14 LUFS)"],
            ["removeSilence", "Shorten long pauses"],
          ] as const).map(([key, label]) => (
            <label key={key} className="check">
              <input type="checkbox" checked={values[key]} disabled={uploading}
                onChange={(e) => set(key, e.target.checked)} />
              {label}
            </label>
          ))}
        </details>

        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        {uploading && (
          <div className="panel">
            <ProgressBar value={progress} label="Upload progress" />
            <p className="small">
              {progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : "Upload complete, starting…"}
            </p>
          </div>
        )}

        <div className="card-actions">
          <button className="btn btn-primary" type="submit" disabled={!ready || !!scriptError || uploading}>
            {uploading ? "Uploading…" : "Create video"}
          </button>
          {uploading ? (
            <button className="btn" type="button" onClick={() => abortRef.current?.()}>
              Cancel
            </button>
          ) : (
            <Link className="btn" to="/">
              Cancel
            </Link>
          )}
        </div>
        </aside>
      </form>
    </section>
  );
}
