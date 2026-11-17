// The edit session: the document being edited, undo/redo, and autosave with the server's revision check.
// Framework-free so it can be tested without React; `useSession` (hooks) connects it to components.

import type { TimelineView } from "../api/types";
import type { Doc, Result } from "./ops";

export type SaveStatus = "saved" | "dirty" | "saving" | "error" | "conflict";

export interface SaveBody {
  base_rev: number;
  tracks: Doc["tracks"];
  clips: Doc["clips"];
  caption_style: Doc["caption_style"];
}
export type Saver = (body: SaveBody) => Promise<{ rev: number }>;

export interface Snapshot {
  doc: Doc;
  rev: number;
  status: SaveStatus;
  message: string | null;
  canUndo: boolean;
  canRedo: boolean;
}

const HISTORY_LIMIT = 200;
export const docOf = (v: TimelineView): Doc => ({ fps: v.fps, tracks: v.tracks, clips: v.clips, assets: v.assets, caption_style: v.caption_style });

export class EditSession {
  private doc: Doc;
  private rev: number;
  private past: Doc[] = [];
  private future: Doc[] = [];
  private status: SaveStatus = "saved";
  private message: string | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private saving = false;
  private disposed = false;
  private savedDoc: Doc;
  private listeners = new Set<() => void>();
  private snap: Snapshot;
  /** the revision the server holds once the last save finished (the document may be ahead of it) */
  onSaved: (rev: number) => void = () => undefined;

  constructor(initial: TimelineView, private readonly save: Saver, private readonly debounceMs = 800) {
    this.doc = docOf(initial);
    this.rev = initial.rev;
    this.savedDoc = this.doc;
    this.snap = this.makeSnapshot();
  }

  // ---- store interface (useSyncExternalStore)
  subscribe = (l: () => void): (() => void) => (this.listeners.add(l), () => void this.listeners.delete(l));
  getSnapshot = (): Snapshot => this.snap;

  private makeSnapshot(): Snapshot {
    return { doc: this.doc, rev: this.rev, status: this.status, message: this.message, canUndo: this.past.length > 0, canRedo: this.future.length > 0 };
  }
  private publish() {
    this.snap = this.makeSnapshot();
    this.listeners.forEach((l) => l());
  }

  // ---- editing
  /** Apply the result of an operation. A refused operation (it has `error`) changes nothing and reports why. */
  apply(r: Result): string | null {
    if (r.error) return r.error;
    if (r.doc === this.doc) return null;
    this.past.push(this.doc);
    if (this.past.length > HISTORY_LIMIT) this.past.shift();
    this.future = [];
    this.doc = r.doc;
    this.changed();
    return null;
  }
  undo(): void {
    const prev = this.past.pop();
    if (!prev) return;
    this.future.push(this.doc);
    this.doc = prev;
    this.changed();
  }
  redo(): void {
    const next = this.future.pop();
    if (!next) return;
    this.past.push(this.doc);
    this.doc = next;
    this.changed();
  }

  private changed() {
    if (this.status !== "conflict") {
      this.status = this.saving ? "saving" : "dirty";
      this.message = null;
      this.schedule(this.debounceMs);
    }
    this.publish();
  }

  // ---- saving
  private schedule(ms: number) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), ms);
  }

  /** Save now (also called before leaving the page). Resolves when nothing is left unsaved or saving failed. */
  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    if (this.saving || this.disposed || this.status === "conflict") return;
    this.saving = true;
    try {
      for (;;) {
        const sent = this.doc;
        if (sent === this.savedDoc) break;
        this.status = "saving";
        this.publish();
        try {
          const res = await this.save({ base_rev: this.rev, tracks: sent.tracks, clips: sent.clips, caption_style: sent.caption_style });
          this.rev = res.rev;
          this.savedDoc = sent;
          this.onSaved(res.rev);
        } catch (e) {
          const status = (e as { status?: number }).status;
          const text = e instanceof Error ? e.message : "Saving failed";
          if (status === 409) {
            this.status = "conflict";
            this.message = text;
          } else {
            this.status = "error";
            this.message = text;
            this.schedule(Math.max(this.debounceMs, 3000)); // try again; the edits are still here
          }
          this.publish();
          return;
        }
        if (this.disposed) return;
      }
      this.status = "saved";
      this.message = null;
      this.publish();
    } finally {
      this.saving = false;
    }
  }

  /** True when nothing local would be lost by replacing the document with the server's. */
  get clean(): boolean {
    return this.status === "saved" && this.past.length === 0 && this.future.length === 0;
  }
  /** Replace everything with what the server has (after a conflict, or when a render changed the project). */
  reset(view: TimelineView): void {
    if (this.timer) clearTimeout(this.timer);
    this.doc = docOf(view);
    this.savedDoc = this.doc;
    this.rev = view.rev;
    this.past = [];
    this.future = [];
    this.status = "saved";
    this.message = null;
    this.publish();
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer) clearTimeout(this.timer);
    this.listeners.clear();
  }
}
