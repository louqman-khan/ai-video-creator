// usage: node e2e/multitrack.mjs <project-id> <ffmpeg> <out-dir> [ui-url]   (edits the project: use a COPY)
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const [pid, ffmpeg, out, base = "http://127.0.0.1:5742"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p) => fetch(`${base}/api/projects/${pid}${p}`).then((r) => r.json());

await page.goto(`${base}/projects/${pid}`);
await page.locator("canvas.live-canvas").waitFor();
await page.waitForTimeout(2500);
await page.getByRole("button", { name: "+ Video track" }).click();
step("a second video track appears", (await page.locator("[data-track]").count()) === 4);

// drag the first scene up onto the new track (it is shown above V1)
const clip = page.locator('[data-clip="scene-1"]');
await clip.scrollIntoViewIfNeeded();
const cb = await clip.boundingBox();
const v2 = await page.locator('[data-track="V2"]').boundingBox();
await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2);
await page.mouse.down();
for (let i = 1; i <= 8; i++) await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2 + (v2.y + v2.height / 2 - (cb.y + cb.height / 2)) * (i / 8));
await page.mouse.up();
await page.waitForTimeout(300);
step("the clip moved to V2", await page.locator('[data-track="V2"] [data-clip="scene-1"]').count() === 1);

await page.getByRole("button", { name: "Bottom right" }).click();
await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 8000 });
const tl = await api("/timeline");
const pip = tl.clips.find((c) => c.id === "scene-1").transform;
step("size and position were saved", pip.scale === 0.35 && pip.x === 0.3 && pip.y === 0.3, JSON.stringify(pip));

// live picture at t = 1 s
await page.evaluate(() => { document.querySelector("canvas.live-canvas").__engine.currentTime = 1; });
await page.waitForTimeout(800);
const png = await page.evaluate(() => document.querySelector("canvas.live-canvas").toDataURL("image/png"));
writeFileSync(`${out}/live.png`, Buffer.from(png.split(",")[1], "base64"));
let info;
for (let i = 0; i < 80; i++) { info = await api(""); if (info.status === "done" && info.preview_rev === tl.rev) break; await page.waitForTimeout(500); }
step("preview re-rendered from the saved revision", info.preview_rev === tl.rev);
const ref = spawnSync(ffmpeg, ["-v", "error", "-y", "-ss", "1", "-i", `${base}/api/projects/${pid}/video`, "-frames:v", "1", "-vf", "scale=960:540", `${out}/rendered.png`]);
const q = spawnSync(ffmpeg, ["-v", "info", "-i", `${out}/live.png`, "-i", `${out}/rendered.png`, "-lavfi", "[0:v]crop=960:380:0:0[a];[1:v]crop=960:380:0:0[b];[a][b]ssim", "-f", "null", "-"], { encoding: "utf8" }).stderr;
const ssim = Number(/All:([0-9.]+)/.exec(q)?.[1] ?? 0);
step("live picture matches the render (picture-in-picture)", ssim >= 0.85, `SSIM ${ssim}`);
// the window really is small and in the corner: the top-left of the rendered frame is black (V1 has a gap there)
const px = (file, x, y) => { const r = spawnSync(ffmpeg, ["-v", "error", "-i", file, "-vf", `crop=4:4:${x}:${y}`, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout; return [...r].reduce((a, b) => a + b, 0) / r.length; };
step("rendered frame: black top-left, picture bottom-right", px(`${out}/rendered.png`, 40, 40) < 20 && px(`${out}/rendered.png`, 780, 400) > 25, `${px(`${out}/rendered.png`, 40, 40).toFixed(0)} / ${px(`${out}/rendered.png`, 780, 400).toFixed(0)}`);
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
