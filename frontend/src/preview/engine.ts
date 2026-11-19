// The live preview: draws the timeline on a canvas straight from the small proxy files and plays the audio through
// WebAudio, so an edit is visible at once instead of after a server render. It looks like an HTMLVideoElement to
// the rest of the editor (currentTime, paused, play, pause and the usual events) so the playhead code is shared.
// What it draws is decided by the pure functions in plan.ts. Export stays the truth (FFmpeg): see docs/live-preview.md.

import type { Doc } from "../timeline/ops";
import { timelineLength } from "../timeline/ops";
import { GlKeyer, keyImageData, refineAlpha, rgbToHex, type Key } from "./chromakey";
import { audioAt, captionAt, layersAt, type Layer } from "./plan";

/** Addresses of the prepared files; null while a file is not ready yet (nothing is requested until it is). */
export interface Urls {
  video(assetId: string): string | null;
  image(assetId: string): string | null;
  audio(assetId: string): string | null;
}

const DRIFT = 0.15;     // seconds a playing video or audio may be off before it is corrected
const KEEP = 6;         // media elements kept per kind (older, unused ones are released)

interface AudioVoice { el: HTMLAudioElement; gain: GainNode | null }

/** The colour and blur effects as a CSS filter: the same mapping as `_fx_args` in render.py. */
function cssFilter(l: Layer, W: number): string {
  const { brightness: b, contrast: c, saturation: s, blur } = l.fx;
  const parts: string[] = [];
  if (b) parts.push(`brightness(${Math.max(0, 1 + 0.8 * (b / 100))})`);
  if (c) parts.push(`contrast(${Math.max(0, 1 + c / 100)})`);
  if (s) parts.push(`saturate(${Math.max(0, 1 + s / 100)})`);
  if (blur > 0) parts.push(`blur(${(blur * 0.00015 * W).toFixed(2)}px)`);
  return parts.length ? parts.join(" ") : "none";
}

/** Match `BLUR_ZOOM` / `BLUR_SIGMA` in render.py. */
const BLUR_ZOOM = 1.15;
const BLUR_SIGMA = 0.03;

/** The font list for the live caption: the font chosen in the caption style first (when this computer has it), then the Urdu defaults. */
export function captionFontStack(chosen: unknown): string {
  const name = typeof chosen === "string" ? chosen.replace(/["'\\;{}]/g, "").trim().slice(0, 60) : "";
  const defaults = '"Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", system-ui, sans-serif';
  return name ? `"${name}", ${defaults}` : defaults;
}

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

  /** Files became ready (or not): look again at what can be shown and heard. */
  refresh(): void {
    this.draw();
    this.syncMedia(true);
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
  private videoFor(clipId: string, assetId: string): HTMLVideoElement | null {
    let v = this.videos.get(clipId);
    if (!v) {
      const url = this.urls.video(assetId);
      if (!url) return null;
      v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.preload = "auto";
      v.src = url;
      v.addEventListener("seeked", () => !this.disposed && this.draw());
      v.addEventListener("loadeddata", () => !this.disposed && this.draw());
      this.videos.set(clipId, v);
      this.trim(this.videos, new Set([clipId]));
    }
    return v;
  }
  private imageFor(assetId: string): HTMLImageElement | null {
    let im = this.images.get(assetId);
    if (!im) {
      const url = this.urls.image(assetId);
      if (!url) return null;
      im = new Image();
      im.addEventListener("load", () => !this.disposed && this.draw());
      im.src = url;
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
  private voiceFor(clipId: string, assetId: string): AudioVoice | null {
    let v = this.voices.get(clipId);
    if (!v) {
      const url = this.urls.audio(assetId);
      if (!url) return null;
      const el = new Audio();
      el.preload = "auto";
      el.src = url;
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
      if (!v) continue;
      // aim at the middle of the frame: a time that is a hair before a frame's own time would show the frame before it
      const want = l.time + 0.5 / this.doc.fps;
      if (force || Math.abs(v.currentTime - want) > (this.playing ? DRIFT : 0.5 / this.doc.fps)) {
        try { v.currentTime = want; } catch { /* not loaded yet: loadeddata draws it */ }
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
      if (!voice) continue;
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
  private scratch: HTMLCanvasElement[] = [];
  private offscreen(i: number, W: number, H: number): CanvasRenderingContext2D | null {
    let c = this.scratch[i];
    if (!c) c = this.scratch[i] = document.createElement("canvas");
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    const g = c.getContext("2d");
    g?.clearRect(0, 0, W, H);
    return g;
  }

  /**
   * One picture, the same steps in the same order as the renderer's `_layer_chain`: show it in the frame (fill, fit or
   * blurred background; a still with Ken Burns zooms), effects, crop, resize, rotate, opacity, transition shift and zoom.
   */
  /** Step 1 of a layer: the picture in a frame-sized image (fill / fit / blurred background), without key or effects. */
  private drawBase(l: Layer, W: number, H: number, a: CanvasRenderingContext2D): boolean {
    if (!l.clip.asset) return false;
    let src: CanvasImageSource;
    let w: number;
    let h: number;
    if (l.clip.kind === "video") {
      const v = this.videoFor(l.clip.id, l.clip.asset);
      if (!v || v.readyState < 2 || !v.videoWidth) return false;
      src = v; w = v.videoWidth; h = v.videoHeight;
    } else {
      const im = this.imageFor(l.clip.asset);
      if (!im || !im.complete || !im.naturalWidth) return false;
      src = im; w = im.naturalWidth; h = im.naturalHeight;
    }
    const place = (ctx: CanvasRenderingContext2D, scale: number) => ctx.drawImage(src, (W - w * scale) / 2, (H - h * scale) / 2, w * scale, h * scale);
    const cover = Math.max(W / w, H / h);
    const contain = Math.min(W / w, H / h);
    if (l.fit === "fit" && l.zoom === 1) place(a, contain);
    else if (l.fit === "blur" && l.zoom === 1) {
      a.filter = `blur(${(W * BLUR_SIGMA).toFixed(1)}px)`;
      place(a, cover * BLUR_ZOOM);
      a.filter = "none";
      place(a, contain);
    } else if (l.focus && l.zoom === 1) {
      const [ox, oy] = this.focusOffset(l.focus, w, h, W, H);
      a.drawImage(src, -ox, -oy, w * cover, h * cover); // fill, with the window centred on the focus point
    } else place(a, cover * l.zoom); // fill (and Ken Burns, which is always "fill")
    return true;
  }

  /** How far a cover-scaled picture is shifted left/up so that the focus point is centred in the frame (kept inside the picture). */
  private focusOffset(focus: [number, number], w: number, h: number, W: number, H: number): [number, number] {
    const s = Math.max(W / w, H / h);
    const sw = w * s, sh = h * s;
    return [Math.min(Math.max(focus[0] * sw - W / 2, 0), Math.max(0, sw - W)), Math.min(Math.max(focus[1] * sh - H / 2, 0), Math.max(0, sh - H))];
  }

  /** The point of the clip's own picture (as fractions 0..1 of the picture) under a point of the canvas: what a click on the preview means as a focus. */
  pickFocus(clipId: string, x: number, y: number): { x: number; y: number } | null {
    const l = layersAt(this.doc, this.frame).find((v) => v.clip.id === clipId);
    const { width: W, height: H } = this.canvas;
    if (!l || !l.clip.asset || l.fit !== "fill" || l.zoom !== 1) return null;
    const v = l.clip.kind === "video" ? this.videos.get(l.clip.id) : undefined;
    const im = l.clip.kind === "image" ? this.images.get(l.clip.asset) : undefined;
    const w = v?.videoWidth || im?.naturalWidth || 0;
    const h = v?.videoHeight || im?.naturalHeight || 0;
    if (!w || !h) return null;
    const { sx, sy, sw, sh, cx, cy, k } = this.placement(l, W, H);
    const t = (-l.rotation * Math.PI) / 180;
    const dx = x - cx, dy = y - cy;
    const bx = sx + sw / 2 + (dx * Math.cos(t) - dy * Math.sin(t)) / k;   // the point in the frame-sized image
    const by = sy + sh / 2 + (dx * Math.sin(t) + dy * Math.cos(t)) / k;
    if (bx < 0 || by < 0 || bx >= W || by >= H) return null;
    const s = Math.max(W / w, H / h);
    const [ox, oy] = l.focus ? this.focusOffset(l.focus, w, h, W, H) : [Math.max(0, (w * s - W) / 2), Math.max(0, (h * s - H) / 2)];
    return { x: Math.min(1, Math.max(0, (ox + bx) / (w * s))), y: Math.min(1, Math.max(0, (oy + by) / (h * s))) };
  }

  /** The green screen: make the key colour transparent (on the graphics card when there is one). */
  private applyKey(a: CanvasRenderingContext2D, key: Key, W: number, H: number) {
    this.keyer ??= new GlKeyer();
    const refine = !!(key.shrink || key.feather);
    const out = this.keyer.apply(a.canvas, key);
    if (out) {
      a.clearRect(0, 0, W, H);
      a.drawImage(out, 0, 0);
    } else {
      const img = a.getImageData(0, 0, W, H);
      keyImageData(img.data, key);
      a.putImageData(img, 0, 0);
    }
    if (refine) {   // edge clean-up needs the neighbours of each pixel: done on the pixels (a few ms at preview size)
      const img = a.getImageData(0, 0, W, H);
      refineAlpha(img.data, W, H, key.shrink ?? 0, key.feather ?? 0);
      a.putImageData(img, 0, 0);
    }
  }
  private keyer: GlKeyer | null = null;

  /** Where the picture's frame-sized image ended up on the canvas: centre, crop rectangle, size factor. */
  private placement(l: Layer, W: number, H: number) {
    const [cl, ct, cr, cb] = l.crop;
    return {
      sx: cl * W, sy: ct * H, sw: W * (1 - cl - cr), sh: H * (1 - ct - cb),
      cx: W / 2 + (l.x + l.dx) * W + ((cl - cr) / 2) * W * l.scale,
      cy: H / 2 + l.y * H + ((ct - cb) / 2) * H * l.scale,
      k: l.scale * l.zoomMul,
    };
  }

  /**
   * One picture, the same steps in the same order as the renderer's `_layer_chain`: show it in the frame (fill, fit or
   * blurred background; a still with Ken Burns zooms), green screen, effects, crop, resize, rotate, opacity, transition shift and zoom.
   */
  private drawLayer(g: CanvasRenderingContext2D, l: Layer, W: number, H: number) {
    const a = this.offscreen(0, W, H);
    const b = this.offscreen(1, W, H);
    if (!a || !b || !this.drawBase(l, W, H, a)) return;
    if (l.key) this.applyKey(a, l.key, W, H);
    b.filter = cssFilter(l, W);
    b.drawImage(a.canvas, 0, 0);
    b.filter = "none";
    const { sx, sy, sw, sh, cx, cy, k } = this.placement(l, W, H);
    g.save();
    g.globalAlpha = l.opacity;
    g.translate(cx, cy);
    g.rotate((l.rotation * Math.PI) / 180);
    g.drawImage(b.canvas, sx, sy, sw, sh, (-sw * k) / 2, (-sh * k) / 2, sw * k, sh * k);
    g.restore();
  }

  /** The colour of the clip's own picture (before any key or effect) under a point of the canvas, as "#rrggbb"; null if there is none. */
  pickColor(clipId: string, x: number, y: number): string | null {
    const l = layersAt(this.doc, this.frame).find((v) => v.clip.id === clipId);
    const { width: W, height: H } = this.canvas;
    const a = this.offscreen(0, W, H);
    if (!l || !a || !this.drawBase(l, W, H, a)) return null;
    const { sx, sy, sw, sh, cx, cy, k } = this.placement(l, W, H);
    const t = (-l.rotation * Math.PI) / 180;
    const dx = x - cx;
    const dy = y - cy;
    const bx = Math.floor(sx + sw / 2 + (dx * Math.cos(t) - dy * Math.sin(t)) / k);
    const by = Math.floor(sy + sh / 2 + (dx * Math.sin(t) + dy * Math.cos(t)) / k);
    if (bx < 0 || by < 0 || bx >= W || by >= H) return null;
    const [r, gg, bl, al] = a.getImageData(bx, by, 1, 1).data;
    return al === 0 ? null : rgbToHex(r!, gg!, bl!);
  }

  /** An approximation of the burned-in caption (the export uses libass and the caption style): white text, dark outline. */
  private drawCaption(g: CanvasRenderingContext2D, text: string, W: number, H: number) {
    const size = Math.round(H * 0.055);
    g.font = `${size}px ${captionFontStack(this.doc.caption_style?.font)}`;
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
