// usage: node e2e/avatar.mjs <project-id> <ffmpeg> <out-dir> [ui-url]   (edits the project: use a COPY with prepared media)
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 2200 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("response", (r) => r.status() >= 400 && console.log("  HTTP", r.status(), r.request().method(), r.url().replace(base, "")));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p) => fetch(`${base}/api/projects/${pid}${p}`).then((r) => r.json());

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(2500);
await page.getByRole("tab", { name: "Avatar" }).click();                    // the avatar panel is one of the editor's side tabs
await page.getByText("Talking avatar").click();
const thumbs = await page.locator(".avatar-choice img").evaluateAll((els) => els.map((e) => e.complete && e.naturalWidth > 0));
step("the avatar pictures load", thumbs.length >= 3 && thumbs.every(Boolean), `${thumbs.length} avatars`);
await page.getByLabel(/Nomi/).check({ force: true });
await page.getByLabel("Corner").selectOption("top-right");
await page.getByRole("button", { name: "Add avatar to the video" }).click();
await page.waitForFunction(() => document.querySelector('[data-clip="avatar-1"]') !== null, null, { timeout: 120000 });
step("the avatar clip appears on the timeline by itself", true);
let info;
for (let i = 0; i < 120; i++) { info = await api(""); const tl = await api("/timeline"); if (info.status === "done" && info.preview_rev === tl.rev) break; await page.waitForTimeout(500); }
const tl = await api("/timeline");
const clip = tl.clips.find((c) => c.id === "avatar-1");
step("it is keyed, fitted and in the top-right corner", clip.key?.color === "#00ff00" && clip.fit === "fit" && clip.transform.x > 0 && clip.transform.y < 0, JSON.stringify(clip.transform));
// the live canvas and the render agree, and the green is gone in both
const frame = 30;
await page.evaluate((f) => { document.querySelector("canvas.live-canvas").__engine.currentTime = f / 30; }, frame);
await page.waitForTimeout(1500);
const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
writeFileSync(`${out}/live.png`, Buffer.from(png.split(",")[1], "base64"));
spawnSync(ffmpeg, ["-v", "error", "-y", "-i", `${base}/api/projects/${pid}/video`, "-vf", `select=eq(n\\,${frame})`, "-fps_mode", "passthrough", "-frames:v", "1", `${out}/render.png`]);
const q = spawnSync(ffmpeg, ["-v", "info", "-i", `${out}/live.png`, "-i", `${out}/render.png`, "-lavfi", "[0:v]scale=160:-2:flags=area[a];[1:v]scale=160:-2:flags=area[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
const s = Number(/All:([0-9.]+)/.exec(q)?.[1] ?? 0);
step("live preview matches the render with the avatar in it", s >= 0.8, `SSIM ${s.toFixed(3)}`);
const greenShare = (file) => { const r = spawnSync(ffmpeg, ["-v", "error", "-i", file, "-vf", "scale=96:54", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout; let g = 0; for (let i = 0; i < r.length; i += 3) if (r[i + 1] > 200 && r[i] < 70 && r[i + 2] < 70) g++; return g / (r.length / 3); };
step("no key-green is left on screen (live or render)", greenShare(`${out}/live.png`) < 0.01 && greenShare(`${out}/render.png`) < 0.01, `${(greenShare(`${out}/live.png`) * 100).toFixed(2)}% / ${(greenShare(`${out}/render.png`) * 100).toFixed(2)}%`);
const lum = (file, x, y) => { const r = spawnSync(ffmpeg, ["-v", "error", "-i", file, "-vf", `crop=6:6:${x}:${y}`, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout; return (r[0] + r[1] + r[2]) / 3 / 1; };
// just left of the avatar's square (inside the fitted layer, where black bars used to appear): the video underneath shows
step("no black bars around the avatar (live and render)", lum(`${out}/live.png`, 722, 90) > 60 && lum(`${out}/render.png`, 722, 90) > 60, `live ${lum(`${out}/live.png`, 722, 90).toFixed(0)}, render ${lum(`${out}/render.png`, 722, 90).toFixed(0)}`);
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
