// usage: node e2e/transitions.mjs <project-id> <ffmpeg> <out-dir> [ui-url]   (edits the project: use a COPY with prepared media)
// For each transition and for colour effects: set it in the editor, wait for the saved render, and compare the live canvas with the render.
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1300 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p) => fetch(`${base}/api/projects/${pid}${p}`).then((r) => r.json());
const saved = () => page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 15000 });

async function rendered() {
  const tl = await api("/timeline");
  for (let i = 0; i < 120; i++) { const p = await api(""); if (p.status === "done" && p.preview_rev === tl.rev) return tl; await page.waitForTimeout(500); }
  throw new Error("preview did not render");
}
async function compare(name, sec) {
  await page.evaluate((s) => { document.querySelector("canvas.live-canvas").__engine.currentTime = s; }, sec);
  await page.waitForTimeout(1200);
  const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
  const live = `${out}/${name}_live.png`, ref = `${out}/${name}_render.png`;
  writeFileSync(live, Buffer.from(png.split(",")[1], "base64"));
  // Compared at 160 px wide so that compression noise does not count (the preview is encoded very coarsely); alpha, position and zoom errors still do.
  // The footage is 29.97 fps converted to 30 in two different ways (proxy / render), so a frame can differ by one: take the best of
  // the three neighbouring frames (a wrong alpha, position or zoom still scores low on all of them).
  const frame = Math.round(sec * 30);
  let best = 0;
  for (const k of [frame - 1, frame, frame + 1]) {
    spawnSync(ffmpeg, ["-v", "error", "-y", "-i", `${base}/api/projects/${pid}/video`, "-vf", `select=eq(n\\,${k}),scale=960:540`, "-fps_mode", "passthrough", "-frames:v", "1", ref]);
    const q = spawnSync(ffmpeg, ["-v", "info", "-i", live, "-i", ref, "-lavfi", "[0:v]crop=960:380:0:0,scale=160:63:flags=area[a];[1:v]crop=960:380:0:0,scale=160:63:flags=area[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
    best = Math.max(best, Number(/All:([0-9.]+)/.exec(q)?.[1] ?? 0));
  }
  return best;
}

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(2500);
const v1 = page.locator('[data-track="V1"] [data-clip]');
const first = await v1.nth(0).getAttribute("data-clip");
const second = await v1.nth(1).getAttribute("data-clip");
let tl = await api("/timeline");
const b = tl.clips.find((c) => c.id === second);
const mid = (b.start + 15) / tl.fps;           // half-way through a 30-frame transition into the second picture
const bb = await v1.nth(1).boundingBox();
await page.mouse.click(bb.x + bb.width * 0.6, bb.y + bb.height / 2);   // select it (not at the start, so the playhead does not matter)

// How alike are live and render when nothing special is happening? (the preview render is heavily compressed, so busy footage
// never reaches 1.0.) A transition or effect must stay within 0.08 of the worse of these.
const baseA = await compare("base_a", (b.start - 10) / tl.fps);
const baseB = await compare("base_b", (b.start + 60) / tl.fps);
const baseline = Math.min(baseA, baseB);
const need = Math.max(0.6, baseline - 0.08);
console.log(`  baseline (no transition, no effect): ${baseA.toFixed(3)} / ${baseB.toFixed(3)} -> need >= ${need.toFixed(3)}`);
for (const [value, label] of [["crossfade", "Crossfade"], ["dip", "Dip"], ["slide", "Slide"], ["zoom", "Zoom"]]) {
  await page.getByLabel("Transition").selectOption(value);
  await saved();
  tl = await rendered();
  const t = tl.clips.find((c) => c.id === second).transition_in;
  const s = await compare(value, value === "dip" ? mid - 7 / tl.fps : mid);   // a dip is black in the middle: look where it is half dark
  if (value === "crossfade") for (const F of [0, 3, 29]) console.log(`  crossfade F=${F}: SSIM ${(await compare(`cf${F}`, (b.start + F) / tl.fps)).toFixed(3)}`);
  step(`${label}: live matches the render at the middle of the transition`, t?.type === value && s >= need, `SSIM ${s.toFixed(3)} (transition ${t?.duration} frames)`);
}
await page.getByLabel("Transition").selectOption("");
await saved();

// colour effects on the second picture
for (const [label, value] of [["Saturation", -100], ["Brightness", 50], ["Contrast", 60], ["Blur", 60]]) {
  const slider = page.getByLabel(label, { exact: true });
  await slider.fill(String(value));
  await slider.blur();
  await saved();
  await rendered();
  const s = await compare(label.toLowerCase(), mid + 0.6);
  step(`${label} ${value}: live matches the render`, s >= need - 0.04, // contrast and blur exaggerate a one-frame difference
    `SSIM ${s.toFixed(3)}`);
  await slider.fill("0");
  await slider.blur();
  await saved();
}
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
