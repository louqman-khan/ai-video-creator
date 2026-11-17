import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TimelineView } from "../api/types";
import * as ops from "./ops";
import { EditSession, type SaveBody } from "./session";

const view = (): TimelineView => ({
  rev: 1, fps: 30, aspect: "16:9", duration: 100,
  tracks: [{ id: "v1", kind: "video", name: "V", muted: false, locked: false }],
  assets: { i: { id: "i", kind: "image", duration: null, width: 1, height: 1, source: "", license: "CC0", author: "", title: "", attribution: "", attribution_required: false } },
  caption_style: null,
  clips: [{ id: "a", track: "v1", kind: "image", asset: "i", start: 0, duration: 100, in_point: 0, loop: false, volume: 1, fade_in: 0, fade_out: 0,
    transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, crop: [0, 0, 0, 0] }, effects: [], transition_in: null, text: null, words: [], meta: {} }],
});

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("EditSession", () => {
  it("undoes and redoes, and a new edit clears redo", () => {
    const s = new EditSession(view(), async () => ({ rev: 2 }));
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    expect(s.getSnapshot().doc.clips).toHaveLength(2);
    s.undo();
    expect(s.getSnapshot().doc.clips).toHaveLength(1);
    expect(s.getSnapshot().canRedo).toBe(true);
    s.redo();
    expect(s.getSnapshot().doc.clips).toHaveLength(2);
    s.undo();
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 10));
    expect(s.getSnapshot().canRedo).toBe(false);
  });

  it("a refused operation is reported and records nothing", () => {
    const s = new EditSession(view(), async () => ({ rev: 2 }));
    expect(s.apply(ops.splitClip(s.getSnapshot().doc, "a", 0))).toMatch(/playhead/);
    expect(s.getSnapshot().canUndo).toBe(false);
    expect(s.getSnapshot().status).toBe("saved");
  });

  it("saves once after a burst of edits, with the revision it was based on, then continues from the new one", async () => {
    const bodies: SaveBody[] = [];
    let rev = 1;
    const s = new EditSession(view(), async (b) => (bodies.push(b), { rev: ++rev }));
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 20));
    expect(s.getSnapshot().status).toBe("dirty");
    await vi.advanceTimersByTimeAsync(900);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]!.base_rev).toBe(1);
    expect(s.getSnapshot().status).toBe("saved");
    expect(s.getSnapshot().rev).toBe(2);
    s.apply(ops.splitClip(s.getSnapshot().doc, "a-2", 70));
    await vi.advanceTimersByTimeAsync(900);
    expect(bodies[1]!.base_rev).toBe(2);
  });

  it("edits made while saving are saved right after", async () => {
    const bodies: SaveBody[] = [];
    let release!: () => void;
    let rev = 1;
    const s = new EditSession(view(), (b) => new Promise((res) => { bodies.push(b); release = () => res({ rev: ++rev }); }));
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    await vi.advanceTimersByTimeAsync(900);
    expect(s.getSnapshot().status).toBe("saving");
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 20));
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]!.base_rev).toBe(2);
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(s.getSnapshot().status).toBe("saved");
    expect(s.getSnapshot().doc.clips).toHaveLength(3);
  });

  it("a revision conflict stops saving and keeps the local edits", async () => {
    const save = vi.fn(async () => { throw Object.assign(new Error("changed elsewhere"), { status: 409 }); });
    const s = new EditSession(view(), save);
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    await vi.advanceTimersByTimeAsync(900);
    expect(s.getSnapshot().status).toBe("conflict");
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 20));
    await vi.advanceTimersByTimeAsync(5000);
    expect(save).toHaveBeenCalledTimes(1);
    expect(s.getSnapshot().doc.clips).toHaveLength(3);
  });

  it("after a conflict the user can keep their edits: they are saved on top of the newer revision", async () => {
    const bodies: SaveBody[] = [];
    let n = 0;
    const s = new EditSession(view(), async (b) => {
      bodies.push(b);
      if (++n === 1) throw Object.assign(new Error("changed elsewhere"), { status: 409 });
      return { rev: 8 };
    });
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    await vi.advanceTimersByTimeAsync(900);
    expect(s.getSnapshot().status).toBe("conflict");
    s.keepMine(7);                                                           // the other window is at revision 7
    await vi.advanceTimersByTimeAsync(0);
    expect(bodies[1]!.base_rev).toBe(7);
    expect(bodies[1]!.clips).toHaveLength(2);                                // my split, not theirs
    expect(s.getSnapshot().status).toBe("saved");
    expect(s.getSnapshot().rev).toBe(8);
    s.keepMine(9);                                                           // only meaningful in the conflict state
    expect(s.getSnapshot().rev).toBe(8);
  });

  it("another kind of failure is retried later", async () => {
    let n = 0;
    const s = new EditSession(view(), async () => { if (++n === 1) throw new Error("offline"); return { rev: 2 }; });
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    await vi.advanceTimersByTimeAsync(900);
    expect(s.getSnapshot().status).toBe("error");
    await vi.advanceTimersByTimeAsync(3500);
    expect(s.getSnapshot().status).toBe("saved");
  });

  it("undoing back to the saved document needs no save", async () => {
    const save = vi.fn(async () => ({ rev: 2 }));
    const s = new EditSession(view(), save);
    s.apply(ops.splitClip(s.getSnapshot().doc, "a", 40));
    s.undo();
    await vi.advanceTimersByTimeAsync(900);
    expect(save).not.toHaveBeenCalled();
    expect(s.getSnapshot().status).toBe("saved");
  });
});
