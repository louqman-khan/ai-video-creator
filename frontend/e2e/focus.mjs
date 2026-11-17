// usage: node e2e/focus.mjs <project-id> <ffmpeg> <out-dir> [ui-url]   (edits the project: use a COPY with prepared media)
// Smart reframing: a landscape picture in a 9:16 frame, focus suggested / picked on the preview, live vs render; then a real 1080x1920 export.
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1800 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p, init) => fetch(`${base}/api/projects/${pid}${p}`, init).then((r) => r.json());
const saved = async () => { await page.waitForTimeout(400); await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 15000 }); };
async function rendered() { const tl = await api("/timeline"); for (let i = 0; i < 120; i++) { const p = await api(""); if (p.status === "done" && p.preview_rev === tl.rev) return tl; await page.waitForTimeout(500); } throw new Error("no render"); }
async function compare(name, frame) {
  await page.evaluate((f) => { document.querySelector("canvas.live-canvas").__engine.currentTime = f / 30; }, frame);
  await page.waitForTimeout(1500);
  const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
  const live = `${out}/${name}_live.png`; writeFileSync(live, Buffer.from(png.split(",")[1], "base64"));
  let best = 0;
  for (const k of [frame - 1, frame, frame + 1]) {
    spawnSync(ffmpeg, ["-v", "error", "-y", "-i", `${base}/api/projects/${pid}/video`, "-vf", `select=eq(n\\,${k})`, "-fps_mode", "passthrough", "-frames:v", "1", `${out}/${name}_render.png`]);
    const q = spawnSync(ffmpeg, ["-v", "info", "-i", live, "-i", `${out}/${name}_render.png`, "-lavfi", "[0:v]scale=96:-2:flags=area[a];[1:v]scale=96:-2:flags=area[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
    best = Math.max(best, Number(/All:([0-9.]+)/.exec(q)?.[1] ?? 0));
  }
  return best;
}

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(2500);
await page.getByLabel("Frame shape").selectOption("9:16"); await saved();
const dims = await page.evaluate(() => { const c = document.querySelector("canvas.live-canvas"); return [c.width, c.height]; });
step("the frame is now 9:16", dims.join() === "540,960", dims.join("x"));
let tl = await api("/timeline");
const clip = tl.clips.filter((c) => c.track === "V1").sort((a, b) => a.start - b.start)[1];
const frame = clip.start + 40;
const el = page.locator(`[data-clip="${clip.id}"]`); await el.scrollIntoViewIfNeeded();
const bb = await el.boundingBox(); await page.mouse.click(bb.x + bb.width * 0.7, bb.y + bb.height / 2);

// 1. suggestion
await page.getByRole("button", { name: "Suggest" }).click();
let f = null;
for (let i = 0; i < 40 && !f; i++) { await page.waitForTimeout(500); f = (await api("/timeline")).clips.find((c) => c.id === clip.id).focus; }   // the suggestion takes a moment, then the edit autosaves
await saved();
step("Suggest sets a focus point", Array.isArray(f) && f[0] >= 0 && f[0] <= 1, JSON.stringify(f));
await rendered();
const sSuggest = await compare("suggest", frame);
step("live preview matches the render with the suggested focus", sSuggest >= 0.8, `SSIM ${sSuggest.toFixed(3)}`);

// 2. picking on the preview: click near the left edge of the preview -> the crop window must move left
await page.getByRole("button", { name: "Pick on the preview" }).click();
const layer = page.locator(".pick-layer"); await layer.waitFor(); await layer.scrollIntoViewIfNeeded();
const lb = await layer.boundingBox();
await page.mouse.click(lb.x + lb.width * 0.1, lb.y + lb.height * 0.5); await saved();
tl = await api("/timeline"); f = tl.clips.find((c) => c.id === clip.id).focus;
step("clicking the left of the preview puts the focus on the left part of the picture", f && f[0] < 0.45, JSON.stringify(f));
await rendered();
const sPick = await compare("pick", frame);
step("live preview matches the render with the picked focus", sPick >= 0.8, `SSIM ${sPick.toFixed(3)}`);
await page.getByRole("button", { name: "Centre" }).click(); await saved();
step("Centre removes it", (await api("/timeline")).clips.find((c) => c.id === clip.id).focus === null);

// 3. a real 1080x1920 export of pictures and videos
await rendered();   // an export is refused while the preview of the last edit is still being made
const started = await fetch(`${base}/api/projects/${pid}/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ aspect: "9:16", preset: "1080p", encoder: "software" }) });
step("the export was accepted", started.status === 202, `HTTP ${started.status}`);
let info; for (let i = 0; i < 240; i++) { info = await api(""); if (info.status === "done" || info.status === "failed") break; await page.waitForTimeout(1000); }
const size = spawnSync(ffmpeg.replace(/ffmpeg$/, "ffprobe"), ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", `${base}/api/projects/${pid}/export`], { encoding: "utf8" }).stdout.trim();
step("the 9:16 export is 1080x1920", info.export_ready && size === "1080,1920", `${info.status} ${size} ${info.error ?? ""}`);
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
