// usage: node e2e/reframe.mjs <project-id> <ffmpeg> <out-dir> [ui-url]   (edits the project: use a COPY with prepared media)
// Crop / turn / size, the on-canvas handles, frame shapes and fit modes: live preview vs rendered preview.
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p) => fetch(`${base}/api/projects/${pid}${p}`).then((r) => r.json());
const saved = async () => { await page.waitForTimeout(400); await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 15000 }); };  // (the chip says "saved" until the edit has registered)
async function rendered() {
  const tl = await api("/timeline");
  for (let i = 0; i < 120; i++) { const p = await api(""); if (p.status === "done" && p.preview_rev === tl.rev) return tl; await page.waitForTimeout(500); }
  throw new Error("preview did not render");
}
async function compare(name, frame) {
  await page.evaluate((f) => { document.querySelector("canvas.live-canvas").__engine.currentTime = f / 30; }, frame);
  await page.waitForTimeout(1200);
  const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
  const live = `${out}/${name}_live.png`, ref = `${out}/${name}_render.png`;
  writeFileSync(live, Buffer.from(png.split(",")[1], "base64"));
  let best = 0;
  for (const k of [frame - 1, frame, frame + 1]) {
    spawnSync(ffmpeg, ["-v", "error", "-y", "-i", `${base}/api/projects/${pid}/video`, "-vf", `select=eq(n\\,${k})`, "-fps_mode", "passthrough", "-frames:v", "1", ref]);
    const q = spawnSync(ffmpeg, ["-v", "info", "-i", live, "-i", ref, "-lavfi", "[0:v]scale=160:-2:flags=area[a];[1:v]scale=160:-2:flags=area[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
    best = Math.max(best, Number(/All:([0-9.]+)/.exec(q)?.[1] ?? 0));
  }
  return best;
}
const slider = async (label, value) => { const s = page.getByLabel(label, { exact: true }); await s.fill(String(value)); await s.blur(); await saved(); };

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(2500);
let tl = await api("/timeline");
const v1 = tl.clips.filter((c) => c.track === "V1").sort((a, b) => a.start - b.start);
const clip = v1[1];
const frame = clip.start + 40;
const baseline = await compare("baseline", frame);
const need = Math.max(0.6, baseline - 0.1);
console.log(`  baseline ${baseline.toFixed(3)} -> need >= ${need.toFixed(3)}`);

// select the second picture
const el = page.locator(`[data-clip="${clip.id}"]`);
await el.scrollIntoViewIfNeeded();
const bb = await el.boundingBox();
await page.mouse.click(bb.x + bb.width * 0.7, bb.y + bb.height / 2);

// 1. size, turn, crop from the inspector
await slider("Size", 0.7);
await slider("Turn", 20);
await slider("Crop left", 0.15);
await slider("Crop bottom", 0.1);
await rendered();
step("size 70 %, turned 20°, cropped: live matches the render", (await compare("shape", frame)) >= need, "");
await page.getByRole("button", { name: "Reset position and size" }).click();
await saved();
step("reset puts it back", JSON.stringify((await api("/timeline")).clips.find((c) => c.id === clip.id).transform.crop) === "[0,0,0,0]");

// 2. the on-canvas handles
await page.evaluate((f) => { document.querySelector("canvas.live-canvas").__engine.currentTime = f / 30; }, frame);
await slider("Size", 0.6);
const svg = page.locator("svg.canvas-handles");
await svg.waitFor();
const box = async (h) => { const loc = page.locator(`[data-handle="${h}"]`).first(); await loc.scrollIntoViewIfNeeded(); const b = await loc.boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
const before = (await api("/timeline")).clips.find((c) => c.id === clip.id).transform;
const m = await box("move");
await page.mouse.move(m.x, m.y); await page.mouse.down();
for (let i = 1; i <= 8; i++) await page.mouse.move(m.x + i * 8, m.y + i * 4);
await page.mouse.up(); await saved();
const afterMove = (await api("/timeline")).clips.find((c) => c.id === clip.id).transform;
step("dragging the picture on the canvas moves it", afterMove.x > before.x + 0.02 && afterMove.y > before.y + 0.01, `x ${before.x} -> ${afterMove.x}, y ${before.y} -> ${afterMove.y}`);
const c1 = await box("scale");
await page.mouse.move(c1.x, c1.y); await page.mouse.down();
for (let i = 1; i <= 8; i++) await page.mouse.move(c1.x - i * 10, c1.y - i * 6);
await page.mouse.up(); await saved();
const afterScale = (await api("/timeline")).clips.find((c) => c.id === clip.id).transform;
step("dragging a corner resizes it", afterScale.scale > afterMove.scale + 0.03, `${afterMove.scale} -> ${afterScale.scale}`);
const r = await box("rotate");
await page.mouse.move(r.x, r.y); await page.mouse.down();
for (let i = 1; i <= 8; i++) await page.mouse.move(r.x + i * 15, r.y + i * 5);
await page.mouse.up(); await saved();
const afterRot = (await api("/timeline")).clips.find((c) => c.id === clip.id).transform;
step("dragging the round handle turns it", Math.abs(afterRot.rotation) > 5, `${afterRot.rotation}°`);
await page.getByRole("button", { name: "Crop on the preview" }).click();
const e = await box("crop-l");
await page.mouse.move(e.x, e.y); await page.mouse.down();
for (let i = 1; i <= 8; i++) await page.mouse.move(e.x + i * 8, e.y);
await page.mouse.up(); await saved();
const afterCrop = (await api("/timeline")).clips.find((c) => c.id === clip.id).transform;
step("dragging an edge in crop mode crops it", afterCrop.crop[0] > 0.05, JSON.stringify(afterCrop.crop));
await rendered();
step("after the handle edits: live matches the render", (await compare("handles", frame)) >= need);
await page.getByRole("button", { name: "Crop on the preview" }).click();
await page.getByRole("button", { name: "Reset position and size" }).click(); await saved();

// 3. frame shape and fit modes
for (const [aspect, size] of [["9:16", [540, 960]], ["1:1", [540, 540]], ["4:5", [560, 700]]]) {
  await page.getByLabel("Frame shape").selectOption(aspect); await saved();
  const canvasSize = await page.evaluate(() => { const c = document.querySelector("canvas.live-canvas"); return [c.width, c.height]; });
  await rendered();
  const dims = spawnSync(ffmpeg.replace(/ffmpeg$/, "ffprobe"), ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", `${base}/api/projects/${pid}/video`], { encoding: "utf8" }).stdout.trim();
  step(`frame ${aspect}: canvas and render are ${size.join("x")}`, canvasSize.join() === size.join() && dims === size.join(), `canvas ${canvasSize.join("x")}, render ${dims}`);
  for (const fit of ["fill", "fit", "blur"]) {
    await page.getByLabel("Pictures that do not match the frame").selectOption(fit); await saved(); await rendered();
    const s = await compare(`${aspect.replace(":", "x")}_${fit}`, frame);
    step(`frame ${aspect}, pictures ${fit}: live matches the render`, s >= need, `SSIM ${s.toFixed(3)}`);
  }
}
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
