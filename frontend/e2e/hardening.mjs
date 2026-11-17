// usage: node e2e/hardening.mjs <project-id> [ui-url]   (edits the project: use a COPY with prepared media)
// Performance budgets on a 300-clip timeline (drag >= 50 fps, seek < 150 ms) and an accessibility audit with axe-core.
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
const pid = process.argv[2];
const base = process.argv[3] ?? "http://127.0.0.1:5742";
const axeSource = readFileSync(new URL("../node_modules/axe-core/axe.min.js", import.meta.url), "utf8");
const api = (p, init) => fetch(`${base}/api/projects/${pid}${p}`, init).then((r) => r.json());
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };

// 1. a heavy timeline: 100 pictures back to back, 100 on a second track with gaps, 100 captions
const tl = await api("/timeline");
const video = Object.values(tl.assets).find((a) => a.kind === "video" && a.source !== "narration");
const tpl = tl.clips.find((c) => c.kind === "video");
const cap = tl.clips.find((c) => c.kind === "caption");
const clips = [...tl.clips];
const tracks = [...tl.tracks, { id: "V2", kind: "video", name: "Overlay", muted: false, locked: false, duck: false }];
for (let i = 0; i < 100; i++) {
  clips.push({ ...tpl, id: `h1-${i}`, track: "V1", asset: video.id, kind: "video", start: 400 + i * 30, duration: 30, in_point: (i * 7) % 600, loop: false, meta: {}, transition_in: null });
  clips.push({ ...tpl, id: `h2-${i}`, track: "V2", asset: video.id, kind: "video", start: 400 + i * 40, duration: 20, in_point: (i * 11) % 600, loop: false, meta: {}, transition_in: null, transform: { ...tpl.transform, scale: 0.3, x: 0.3, y: 0.3 } });
  clips.push({ ...cap, id: `hc-${i}`, track: tl.clips.find((c) => c.kind === "caption").track, start: 400 + i * 30, duration: 28, text: `caption number ${i} پاکستان کے پہاڑ` });
}
const put = await fetch(`${base}/api/projects/${pid}/timeline`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_rev: tl.rev, tracks, clips, caption_style: tl.caption_style, aspect: tl.aspect }) });
step("a 300+ clip timeline is accepted", put.ok, `${clips.length} clips, HTTP ${put.status}`);
if (!put.ok) { console.log(await put.text()); process.exit(1); }

const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1800 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(e.message));
await page.goto(`${base}/projects/${pid}`);
await page.getByRole("region", { name: "Timeline" }).waitFor();
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(4000);

// 2. dragging a clip: smoothness
const clip = page.locator('[data-clip="h1-3"]');
await clip.scrollIntoViewIfNeeded();
await page.evaluate(() => { document.querySelector(".tl-scroll").scrollLeft = 0; });
const zoomFit = page.getByRole("button", { name: "Fit" });
await zoomFit.click();
await page.waitForTimeout(500);
const target = page.locator('[data-track="V2"] [data-clip]').first();
await target.scrollIntoViewIfNeeded();
const bb = await target.boundingBox();
await page.evaluate(() => { window.__iv = []; let last = 0; const tick = (t) => { if (last) window.__iv.push(t - last); last = t; window.__raf = requestAnimationFrame(tick); }; window.__raf = requestAnimationFrame(tick); });
const x = bb.x + bb.width / 2, y = bb.y + bb.height / 2;
const t0 = Date.now();
await page.mouse.move(x, y); await page.mouse.down();
for (let i = 1; i <= 120; i++) { await page.mouse.move(x + i * 2.5, y); await page.waitForTimeout(8); }
await page.mouse.up();
const secs = (Date.now() - t0) / 1000;
const iv = await page.evaluate(() => { cancelAnimationFrame(window.__raf); return window.__iv.slice().sort((a, b) => a - b); });
const fps = iv.length / secs, p95 = iv[Math.floor(iv.length * 0.95)], over = iv.filter((v) => v > 20).length;
step("dragging a clip among 300+ stays at 50 fps or better", fps >= 50 && p95 <= 25, `${fps.toFixed(0)} fps, p95 ${p95.toFixed(1)} ms, ${over}/${iv.length} frames over 20 ms`);

// 3. seeking: from the call to a drawn picture
const seeks = await page.evaluate(async () => {
  const e = document.querySelector("canvas.live-canvas").__engine;
  const out = [];
  for (let i = 0; i < 25; i++) {
    const frame = 420 + Math.floor(Math.random() * 2900);
    const t0 = performance.now();
    const d0 = e.stats.drawn;
    e.currentTime = frame / 30;
    // ready when every playing layer's video has finished seeking and a picture has been drawn since
    await new Promise((res) => { const poll = () => { const vids = [...e.videos.values()]; if (e.stats.drawn > d0 && vids.every((v) => !v.seeking)) res(); else requestAnimationFrame(poll); }; poll(); });
    out.push(performance.now() - t0);
    await new Promise((r) => setTimeout(r, 60));
  }
  return out.sort((a, b) => a - b);
});
const med = seeks[Math.floor(seeks.length / 2)], p95s = seeks[Math.floor(seeks.length * 0.95)];
step("a seek shows its picture in under 150 ms", p95s < 150, `median ${med.toFixed(0)} ms, p95 ${p95s.toFixed(0)} ms, max ${seeks[seeks.length - 1].toFixed(0)} ms`);

// 4. accessibility audit with the editor in a busy state
await target.click({ position: { x: 3, y: 3 } }).catch(() => undefined);
await page.getByRole("button", { name: "Add media…" }).click();
await page.addScriptTag({ content: axeSource });
const result = await page.evaluate(async () => {
  const r = await window.axe.run(document, { resultTypes: ["violations"] });
  return r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, count: v.nodes.length, sample: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) }));
});
for (const v of result) console.log(`  axe ${v.impact?.padEnd(8)} ${v.id} x${v.count}: ${v.help} -> ${v.sample.join(" | ")}`);
const serious = result.filter((v) => v.impact === "serious" || v.impact === "critical");
step("no serious or critical accessibility violations", serious.length === 0, `${result.length} violations in total, ${serious.length} serious/critical`);
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
