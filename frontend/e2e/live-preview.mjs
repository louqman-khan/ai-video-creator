// usage: node e2e/live-preview.mjs <project-id> <ffmpeg> <out-dir> [ui-url]
// Plays the live preview in real Chrome, measures smoothness and audio/video drift, and compares frames with the
// FFmpeg-rendered preview of the same project (SSIM on the picture area above the captions).
import { chromium } from "playwright-core";
import { execFileSync, spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(1500); // proxies load
const fps = 30;
const seek = (sec) => page.evaluate((s) => { document.querySelector("canvas.live-canvas").__engine.currentTime = s; }, sec);

// 1. parity with the rendered preview at several moments
const ref = (sec, file) => execFileSync(ffmpeg, ["-v", "error", "-y", "-ss", String(sec), "-i", `${base}/api/projects/${pid}/video`, "-frames:v", "1", "-vf", "scale=960:540", file]);
let worst = 1;
for (const sec of [0.5, 2.5, 5, 7, 10]) {
  await seek(sec);
  await page.waitForTimeout(700);
  const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
  const live = `${out}/live_${sec}.png`, rendered = `${out}/ref_${sec}.png`;
  writeFileSync(live, Buffer.from(png.split(",")[1], "base64"));
  ref(sec, rendered);
  const text = spawnSync(ffmpeg, ["-v", "info", "-i", live, "-i", rendered, "-lavfi", "[0:v]crop=960:380:0:0[a];[1:v]crop=960:380:0:0[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
  const m = /All:([0-9.]+)/.exec(text || "");
  const v = m ? Number(m[1]) : NaN;
  console.log(`  t=${sec}s ssim(picture area)=${v}`);
  worst = Math.min(worst, Number.isNaN(v) ? 0 : v);
}
step("live frames match the rendered preview (SSIM >= 0.85 above the captions)", worst >= 0.85, `worst ${worst}`);

// 2. smooth playback for 6 s: frames drawn, playhead follows the clock, audio is running
await seek(0);
const res = await page.evaluate(async () => {
  const e = document.querySelector("canvas.live-canvas").__engine;
  const iv = []; let last = 0; let go = true;
  const tick = (t) => { if (last) iv.push(t - last); last = t; if (go) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  const long = []; new PerformanceObserver((l) => l.getEntries().forEach((x) => long.push(x.duration))).observe({ entryTypes: ["longtask"] });
  const drawn0 = e.stats.drawn; const t0 = performance.now();
  await e.play();
  await new Promise((r) => setTimeout(r, 6000));
  const wall = (performance.now() - t0) / 1000; const pos = e.currentTime; const drawn = e.stats.drawn - drawn0;
  const voices = [...e.voices.values()].map((v) => ({ t: v.el.currentTime, paused: v.el.paused }));
  const clock = e.audioCtx?.state;
  e.pause(); go = false;
  iv.sort((a, b) => a - b);
  return { wall, pos, drawn, p95: iv[Math.floor(iv.length * 0.95)], over33: iv.filter((x) => x > 33).length, n: iv.length, long: long.length, voices, clock };
});
console.log("  ", JSON.stringify(res));
step("playhead follows the clock (within 0.25 s over 6 s)", Math.abs(res.pos - res.wall) < 0.25, `pos ${res.pos.toFixed(2)} wall ${res.wall.toFixed(2)}`);
step("draws about 30 pictures a second", res.drawn >= 6 * 30 * 0.9, `${res.drawn} drawn`);
step("animation frames are smooth (<5% over 33 ms)", res.over33 / res.n < 0.05, `${res.over33}/${res.n}, p95 ${res.p95?.toFixed(1)} ms`);
const narr = res.voices.find((v) => !v.paused);
step("narration audio is playing in sync", !!narr && Math.abs(narr.t - res.pos) < 0.3, JSON.stringify(res.voices));

// 3. an edit shows instantly (no render): delete the first visual clip
await seek(1);
const before = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL());
const first = page.locator('[data-clip="scene-1"]');
await first.scrollIntoViewIfNeeded();
const box = await first.boundingBox();
await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
await page.getByLabel(/Timeline tracks/).focus();
await page.keyboard.press("Delete");
await page.waitForTimeout(300);
const after = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL());
step("deleting a clip changes the live picture within 300 ms", before !== after);
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 400));
await browser.close();
