import { useId, useState } from "react";
import { api } from "../api/client";
import type { Asset, MediaView, TimelineAsset } from "../api/types";
import { formatTimecode } from "./layout";
import type { Doc } from "./ops";

type Tab = "project" | "stock" | "upload";
type StockKind = "video" | "image" | "music" | "sound";
const KIND_LABEL: Record<StockKind, string> = { video: "Videos", image: "Photos", music: "Music", sound: "Sound effects" };
const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

interface Props {
  projectId: string;
  doc: Doc;
  media: Record<string, MediaView>;
  /** put an asset on the timeline at the playhead */
  onInsert: (asset: TimelineAsset, title?: string) => void;
  /** the project gained a file: start watching its preparation */
  onAdded: () => void;
  onNotice: (message: string | null) => void;
}

/** Everything that can be put on the timeline: the project's files, stock search (legal sources only) and uploads. */
export function MediaBin({ projectId, doc, media, onInsert, onAdded, onNotice }: Props) {
  const [tab, setTab] = useState<Tab>("project");
  const [open, setOpen] = useState(false);
  const fps = doc.fps;
  return (
    <section className="bin" aria-label="Media bin">
      <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide media bin" : "Add media…"}</button>
      {open && (
        <>
          <div role="tablist" aria-label="Media sources" className="bin-tabs">
            {([["project", "In this project"], ["stock", "Stock media"], ["upload", "Upload"]] as const).map(([id, label]) => (
              <button key={id} role="tab" type="button" aria-selected={tab === id} className="btn" onClick={() => setTab(id)}>{label}</button>
            ))}
          </div>
          {tab === "project" && (
            <ul className="bin-list" aria-label="Files in this project">
              {Object.values(doc.assets).map((a) => (
                <li key={a.id}>
                  <span className="bin-kind" aria-hidden="true">{a.kind === "audio" ? "♪" : a.kind === "video" ? "▣" : "▢"}</span>
                  <span className="bin-title" dir="auto">{a.title || a.id}</span>
                  <span className="muted small">{a.kind}{a.duration ? ` · ${formatTimecode(a.duration, fps)}` : ""} · {a.license}{media[a.id]?.status === "failed" ? " · unusable" : ""}</span>
                  <button type="button" className="btn" disabled={media[a.id]?.status === "failed"} onClick={() => onInsert(a, a.title)}>Add at playhead</button>
                </li>
              ))}
            </ul>
          )}
          {tab === "stock" && <Stock projectId={projectId} fps={fps} onInsert={onInsert} onAdded={onAdded} onNotice={onNotice} />}
          {tab === "upload" && <Upload projectId={projectId} onInsert={onInsert} onAdded={onAdded} onNotice={onNotice} />}
        </>
      )}
    </section>
  );
}

function Stock({ projectId, fps, onInsert, onAdded, onNotice }: Pick<Props, "projectId" | "onInsert" | "onAdded" | "onNotice"> & { fps: number }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<StockKind>("video");
  const [results, setResults] = useState<Asset[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const idQ = useId();
  const idKind = useId();

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy("search");
    onNotice(null);
    try {
      setResults(await api.binSearch(projectId, q.trim(), kind));
    } catch (er) {
      onNotice(messageOf(er));
    } finally {
      setBusy(null);
    }
  };
  const add = async (a: Asset) => {
    setBusy(a.id);
    onNotice(null);
    try {
      const asset = await api.binAdd(projectId, a.id);
      onAdded();
      onInsert(asset, a.title);
    } catch (er) {
      onNotice(messageOf(er));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div>
      <form className="bin-search" onSubmit={search} role="search">
        <label htmlFor={idQ}>Search</label>
        <input id={idQ} value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} placeholder="e.g. calm piano, waves, city at night" />
        <label htmlFor={idKind}>Media type</label>
        <select id={idKind} value={kind} onChange={(e) => setKind(e.target.value as StockKind)}>
          {(Object.keys(KIND_LABEL) as StockKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <button className="btn" type="submit" disabled={busy === "search" || !q.trim()}>{busy === "search" ? "Searching…" : "Search"}</button>
      </form>
      <p className="muted small">Free-to-reuse sources only. Credits for what you use are added to the project's credits automatically.</p>
      {results && results.length === 0 && <p className="muted">Nothing found. Try other words.</p>}
      {results && results.length > 0 && (
        <ul className="bin-list" aria-label="Search results">
          {results.map((a) => (
            <li key={a.id}>
              {a.thumb_url && a.kind !== "audio" && <img className="bin-thumb" src={a.thumb_url} alt="" loading="lazy" referrerPolicy="no-referrer" />}
              <span className="bin-title" dir="auto">{a.title || a.id}</span>
              <span className="muted small">{a.source}{a.duration ? ` · ${formatTimecode(Math.round(a.duration * fps), fps)}` : ""} · {a.license}{a.attribution_required && a.author ? ` · by ${a.author}` : ""}</span>
              <button type="button" className="btn" disabled={busy !== null} onClick={() => void add(a)}>{busy === a.id ? "Adding…" : "Add at playhead"}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Upload({ projectId, onInsert, onAdded, onNotice }: Pick<Props, "projectId" | "onInsert" | "onAdded" | "onNotice">) {
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [busy, setBusy] = useState(false);
  const idRights = useId();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !rights) return;
    setBusy(true);
    onNotice(null);
    try {
      const m = await api.uploadMedia(projectId, file, "");
      const tl = await api.getTimeline(projectId); // the asset as the timeline knows it
      const asset = tl.assets[m.asset_id];
      onAdded();
      if (asset) onInsert(asset, asset.title);
      setFile(null);
      setRights(false);
    } catch (er) {
      onNotice(messageOf(er));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="bin-search" onSubmit={submit}>
      <input type="file" aria-label="File to upload" accept="video/*,image/*,audio/*,.mkv,.mov,.m4a,.flac,.ogg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <input id={idRights} type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
      <label htmlFor={idRights}>I have the right to use this file in my video</label>
      <button className="btn" type="submit" disabled={!file || !rights || busy}>{busy ? "Uploading…" : "Upload and add at playhead"}</button>
    </form>
  );
}
