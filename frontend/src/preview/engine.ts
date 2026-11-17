// The live preview: draws the timeline on a canvas straight from the small proxy files and plays the audio through
// WebAudio, so an edit is visible at once instead of after a server render. It looks like an HTMLVideoElement to
// the rest of the editor (currentTime, paused, play, pause and the usual events) so the playhead code is shared.
// What it draws is decided by the pure functions in plan.ts. Export stays the truth (FFmpeg): see docs/live-preview.md.

import type { Doc } from "../timeline/ops";
import { timelineLength } from "../timeline/ops";
import { audioAt, captionAt, layersAt, type Layer } from "./plan";

export interface Urls {
  video(assetId: string): string;
  image(assetId: string): string;
  audio(assetId: string): string;
}

const DRIFT = 0.15;     // seconds a playing video or audio may be off before it is corrected
const KEEP = 6;         // media elements kept per kind (older, unused ones are released)

interface AudioVoice { el: HTMLAudioElement; gain: GainNode | null }

export class LiveEngine extends EventTarget {
  private doc: Doc;
  private frame = 0;
  private playing = false;
  private startedAt = 0;
  private startFrame = 0;
  private raf = 0;
  private disposed = false;
  private readonly ctx2d: CanvasRenderingContext2D | null;
  private videos = new Map<string, HTMLVideoElement>();
  private images = new Map<string, HTMLImageElement>();
  private voices = new Map<string, AudioVoice>();
  private audioCtx: AudioContext | null = null;
  /** frames drawn / skipped, for the performance check */
  stats = { drawn: 0 };

  constructor(private readonly canvas: HTMLCanvasElement, private readonly urls: Urls, doc: Doc) {
    super();
    this.doc = doc;
    this.ctx2d = canvas.getContext("2d");
    this.draw();
  }

  // ---- the part of HTMLVideoElement the editor uses
  get currentTime(): number { return this.frame / this.doc.fps; }
  set currentTime(sec: number) {
    this.frame = Math.max(0, Math.min(this.lastFrame, Math.round(sec * this.doc.fps)));
    if (this.playing) { this.startedAt = performance.now(); this.startFrame = this.frame; }
    this.draw();
    this.syncMedia(true);
    this.emit("seeked");
  }
  get paused(): boolean { return !this.playing; }
  private get lastFrame(): number { return Math.max(0, timelineLength(this.doc) - 1); }

  async play(): Promise<void> {
    if (this.playing || this.disposed) return;
    if (this.frame >= this.lastFrame) this.frame = 0;
    this.ensureAudio();
    void this.audioCtx?.resume();
    this.playing = true;
    this.startedAt = performance.now();
    this.startFrame = this.frame;
    this.emit("play");
    this.raf = requestAnimationFrame(this.tick);
  }
  pause(): void {
    if (!this.playing) return;
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.videos.forEach((v) => v.pause());
    this.voices.forEach((v) => v.el.pause());
    this.emit("pause");
  }

  /** The document changed (an edit, undo, a track muted): show it. */
  setDoc(doc: Doc): void {
    this.doc = doc;
    this.frame = Math.min(this.frame, this.lastFrame);
    this.draw();
    this.syncMedia(true);
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.playing = false;
    for (const v of this.videos.values()) { v.pause(); v.removeAttribute("src"); v.load(); }
    for (const v of this.voices.values()) { v.el.pause(); v.el.removeAttribute("src"); v.el.load(); }
    this.videos.clear(); this.voices.clear(); this.images.clear();
    void this.audioCtx?.close();
  }

  private emit(type: string) { this.dispatchEvent(new Event(type)); }

  // ---- clock
  private tick = () => {
    if (!this.playing || this.disposed) return;
    const f = this.startFrame + Math.floor(((performance.now() - this.startedAt) / 1000) * this.doc.fps);
    if (f > this.lastFrame) {
      this.frame = this.lastFrame;
      this.draw();
      this.pause();
      this.emit("ended");
      return;
    }
    if (f !== this.frame) {
      this.frame = f;
      this.draw();
    }
    this.syncMedia(false);
    this.raf = requestAnimationFrame(this.tick);
  };

  // ---- media elements
  private videoFor(clipId: string, assetId: string): HTMLVideoElement {
    let v = this.videos.get(clipId);
    if (!v) {
      v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.preload = "auto";
      v.src = this.urls.video(assetId);
      v.addEventListener("seeked", () => !this.disposed && this.draw());
      v.addEventListener("loadeddata", () => !this.disposed && this.draw());
      this.videos.set(clipId, v);
      this.trim(this.videos, new Set([clipId]));
    }
    return v;
  }
  private imageFor(assetId: string): HTMLImageElement {
    let im = this.images.get(assetId);
    if (!im) {
      im = new Image();
      im.addEventListener("load", () => !this.disposed && this.draw());
      im.src = this.urls.image(assetId);
      this.images.set(assetId, im);
    }
    return im;
  }
  private trim<T extends { pause?: () => void }>(m: Map<string, T>, keep: Set<string>) {
    for (const k of [...m.keys()]) {
      if (m.size <= KEEP) break;
      if (!keep.has(k)) { m.get(k)?.pause?.(); m.delete(k); }
    }
  }
  private ensureAudio() {
    if (this.audioCtx || typeof AudioContext === "undefined") return;
    this.audioCtx = new AudioContext();
  }
  private voiceFor(clipId: string, assetId: string): AudioVoice {
    let v = this.voices.get(clipId);
    if (!v) {
      const el = new Audio();
      el.preload = "auto";
      el.src = this.urls.audio(assetId);
      v = { el, gain: null };
      if (this.audioCtx) {
        const node = this.audioCtx.createMediaElementSource(el);
        v.gain = this.audioCtx.createGain();
        node.connect(v.gain).connect(this.audioCtx.destination);
      }
      this.voices.set(clipId, v);
    }
    return v;
  }

  /** Keep every playing video/audio element on the time the clock says (correct only when it has drifted). */
  private syncMedia(force: boolean) {
    const layers = layersAt(this.doc, this.frame);
    for (const l of layers) {
      if (l.clip.kind !== "video" || !l.clip.asset) continue;
      const v = this.videoFor(l.clip.id, l.clip.asset);
      if (force || Math.abs(v.currentTime - l.time) > (this.playing ? DRIFT : 0.5 / this.doc.fps)) {
        try { v.currentTime = l.time; } catch { /* not loaded yet: loadeddata draws it */ }
      }
      if (this.playing && v.paused) void v.play().catch(() => undefined);
      if (!this.playing && !v.paused) v.pause();
    }
    const live = new Set(layers.map((l) => l.clip.id));
    this.videos.forEach((v, id) => { if (!live.has(id) && !v.paused) v.pause(); });

    const sounding = audioAt(this.doc, this.frame);
    for (const a of sounding) {
      if (!a.clip.asset) continue;
      const voice = this.voiceFor(a.clip.id, a.clip.asset);
      if (voice.gain) voice.gain.gain.value = a.gain;
      else voice.el.volume = Math.min(1, a.gain);
      if (force || Math.abs(voice.el.currentTime - a.time) > DRIFT) {
        try { voice.el.currentTime = a.time; } catch { /* metadata not loaded yet */ }
      }
      if (this.playing && voice.el.paused) void voice.el.play().catch(() => undefined);
      if (!this.playing && !voice.el.paused) voice.el.pause();
    }
    const heard = new Set(sounding.map((a) => a.clip.id));
    this.voices.forEach((v, id) => { if (!heard.has(id) && !v.el.paused) v.el.pause(); });
  }

  // ---- drawing
  private draw() {
    const g = this.ctx2d;
    if (!g || this.disposed) return;
    const { width: W, height: H } = this.canvas;
    g.globalAlpha = 1;
    g.fillStyle = "#000";
    g.fillRect(0, 0, W, H);
    for (const l of layersAt(this.doc, this.frame)) this.drawLayer(g, l, W, H);
    g.globalAlpha = 1;
    const cap = captionAt(this.doc, this.frame);
    if (cap) this.drawCaption(g, cap, W, H);
    this.stats.drawn++;
  }
  private drawLayer(g: CanvasRenderingContext2D, l: Layer, W: number, H: number) {
    if (!l.clip.asset) return;
    let src: CanvasImageSource;
    let w: number;
    let h: number;
    if (l.clip.kind === "video") {
      const v = this.videoFor(l.clip.id, l.clip.asset);
      if (v.readyState < 2 || !v.videoWidth) return;
      src = v; w = v.videoWidth; h = v.videoHeight;
    } else {
      const im = this.imageFor(l.clip.asset);
      if (!im.complete || !im.naturalWidth) return;
      src = im; w = im.naturalWidth; h = im.naturalHeight;
    }
    const s = Math.max(W / w, H / h) * l.zoom * l.scale; // "cover", then the picture-in-picture size, like the renderer
    g.globalAlpha = l.opacity;
    g.drawImage(src, (W - w * s) / 2 + l.x * W, (H - h * s) / 2 + l.y * H, w * s, h * s);
  }

  /** An approximation of the burned-in caption (the export uses libass and the caption style): white text, dark outline. */
  private drawCaption(g: CanvasRenderingContext2D, text: string, W: number, H: number) {
    const size = Math.round(H * 0.055);
    g.font = `${size}px "Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", system-ui, sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "alphabetic";
    g.direction = "inherit";
    g.lineJoin = "round";
    g.lineWidth = Math.max(2, size / 8);
    g.strokeStyle = "rgba(0,0,0,.85)";
    g.fillStyle = "#fff";
    const max = W * 0.9;
    let lines = [text];
    if (g.measureText(text).width > max) {
      const words = text.split(" ");
      const mid = Math.ceil(words.length / 2);
      lines = [words.slice(0, mid).join(" "), words.slice(mid).join(" ")];
    }
    lines.forEach((line, i) => {
      const y = H - size * 0.9 - (lines.length - 1 - i) * size * 1.5;
      g.strokeText(line, W / 2, y, max);
      g.fillText(line, W / 2, y, max);
    });
  }
}
