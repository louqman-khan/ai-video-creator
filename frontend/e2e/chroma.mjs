// usage: node e2e/chroma.mjs <project-id> <ffmpeg> <out-dir> [ui-url]   (edits the project: use a COPY with prepared media)
// Uploads a synthetic green-screen clip, keys it out with the eyedropper, and compares the live preview with the render.
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const clip = `${out}/greenscreen.mp4`;
spawnSync(ffmpeg, ["-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00ff00:s=1280x720:r=30:d=4", "-f", "lavfi", "-i", "color=c=red:s=200x200:r=30:d=4",
  "-f", "lavfi", "-i", "color=c=0xc8e696:s=120x120:r=30:d=4",
  "-filter_complex", "[0][1]overlay=x='40+t*120':y=200[a];[a][2]overlay=x='900-t*60':y=420", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", clip]);
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1700 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p) => fetch(`${base}/api/projects/${pid}${p}`).then((r) => r.json());
const saved = async () => { await page.waitForTimeout(400); await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 15000 }); };
async function rendered() {
  const tl = await api("/timeline");
  for (let i = 0; i < 120; i++) { const p = await api(""); if (p.status === "done" && p.preview_rev === tl.rev) return tl; await page.waitForTimeout(500); }
  throw new Error("preview did not render");
}
const rgbAt = (file, x, y) => { const r = spawnSync(ffmpeg, ["-v", "error", "-i", file, "-vf", `crop=6:6:${x}:${y}`, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout; const n = r.length / 3; return [0, 1, 2].map((c) => Math.round([...r].filter((_, i) => i % 3 === c).reduce((a, b) => a + b, 0) / n)); };

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(2500);
await page.getByRole("button", { name: "Add media…" }).click();
await page.getByRole("tab", { name: "Upload" }).click();
await page.getByLabel("File to upload").setInputFiles(clip);
await page.getByLabel(/I have the right/).check();
await page.getByRole("button", { name: /Upload and add/ }).click();
await page.locator('[data-track="V2"] [data-clip]').waitFor({ timeout: 60000 });
step("the green-screen clip is on a new video track", true);
await page.waitForTimeout(6000);   // proxy preparation
await page.getByRole("button", { name: "Hide media bin" }).click();

// key it: tick the box, then pick the colour with the eyedropper
await page.getByLabel("Green screen (remove a background colour)").check();
await saved();
await page.getByRole("button", { name: "Pick from the preview" }).click();
const layer = page.locator(".pick-layer");
await layer.waitFor();
await layer.scrollIntoViewIfNeeded();
const lb = await layer.boundingBox();
await page.mouse.click(lb.x + lb.width * 0.93, lb.y + lb.height * 0.12);    // a green corner
await saved();
let tl = await api("/timeline");
const key = tl.clips.find((c) => c.track === "V2").key;
step("the eyedropper picked the screen colour", key && Math.abs(parseInt(key.color.slice(3, 5), 16) - 255) < 40 && parseInt(key.color.slice(1, 3), 16) < 60, JSON.stringify(key));

await rendered();
const frame = 40;
await page.evaluate((f) => { document.querySelector("canvas.live-canvas").__engine.currentTime = f / 30; }, frame);
await page.waitForTimeout(1500);
const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
const live = `${out}/chroma_live.png`, ref = `${out}/chroma_render.png`;
writeFileSync(live, Buffer.from(png.split(",")[1], "base64"));
spawnSync(ffmpeg, ["-v", "error", "-y", "-i", `${base}/api/projects/${pid}/video`, "-vf", `select=eq(n\\,${frame})`, "-fps_mode", "passthrough", "-frames:v", "1", ref]);
const q = spawnSync(ffmpeg, ["-v", "info", "-i", live, "-i", ref, "-lavfi", "[0:v]scale=160:-2:flags=area[a];[1:v]scale=160:-2:flags=area[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
const s = Number(/All:([0-9.]+)/.exec(q)?.[1] ?? 0);
step("live vs render with the green removed", s >= 0.8, `SSIM ${s.toFixed(3)}`);
const greenness = ([r, g, b]) => g - Math.max(r, b);
const gl = rgbAt(live, 880, 70), gr = rgbAt(ref, 880, 70);                    // the same corner, both previews
step("the corner shows the picture underneath, not green (live and render)", greenness(gl) < 60 && greenness(gr) < 60, `live ${gl} render ${gr}`);
const sl = rgbAt(live, 160 + 40 * 120 / 30 * 0.75, 270), sr = rgbAt(ref, 160 + 40 * 120 / 30 * 0.75, 270);
console.log(`  subject area live ${sl} render ${sr}`);
// playing with the key on: smooth? (and is the graphics card doing the keying?)
const perf = await page.evaluate(async () => {
  const e = document.querySelector("canvas.live-canvas").__engine;
  const gl = !!document.createElement("canvas").getContext("webgl");
  const iv = []; let last = 0; let go = true;
  const tick = (t) => { if (last) iv.push(t - last); last = t; if (go) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  e.currentTime = 0; await e.play();
  await new Promise((r) => setTimeout(r, 3500));
  e.pause(); go = false; iv.sort((x, y) => x - y);
  return { gl, n: iv.length, p95: iv[Math.floor(iv.length * 0.95)], over33: iv.filter((x) => x > 33).length, pos: e.currentTime };
});
console.log("  ", JSON.stringify(perf));
step("playing with the key on stays smooth (<10% of frames over 33 ms)", perf.over33 / perf.n < 0.1, `${perf.over33}/${perf.n}, p95 ${perf.p95?.toFixed(1)} ms, WebGL ${perf.gl}`);
await page.getByLabel("Green screen (remove a background colour)").uncheck();
await saved();
await rendered();
spawnSync(ffmpeg, ["-v", "error", "-y", "-i", `${base}/api/projects/${pid}/video`, "-vf", `select=eq(n\\,${frame})`, "-fps_mode", "passthrough", "-frames:v", "1", `${out}/chroma_off.png`]);
step("without the key the corner is green again", greenness(rgbAt(`${out}/chroma_off.png`, 880, 70)) > 150);
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
