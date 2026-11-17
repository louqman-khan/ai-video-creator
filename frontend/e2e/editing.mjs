// usage: node e2e/editing.mjs <project-id> [ui-url]    (run it against a COPY of a project: it edits the timeline)
import { chromium } from "playwright-core";
const pid = process.argv[2];
const base = process.argv[3] ?? "http://127.0.0.1:5742";
const api = (p, init) => fetch(`${base}/api/projects/${pid}${p}`, init).then((r) => r.json());
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("requestfailed", (r) => r.failure()?.errorText !== "net::ERR_ABORTED" && problems.push(`failed: ${r.url()} ${r.failure()?.errorText}`)); // a reloaded player cancels its old request
const step = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); if (!ok) process.exitCode = 1; };

await page.goto(`${base}/projects/${pid}`);
await page.getByRole("region", { name: "Timeline" }).waitFor();
const before = await api("/timeline");
const clips = () => page.locator("[data-clip]").evaluateAll((els) => els.map((e) => e.getAttribute("data-clip")));
const n0 = (await clips()).length;

// 1. split the first visual at the playhead: click a clip, then press S
const v = page.locator('.tl-video [data-clip], [data-track] .tl-clip-video, [data-track] .tl-clip-image').first();
await v.scrollIntoViewIfNeeded();
const box = await v.boundingBox();
await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
await page.getByLabel(/Timeline tracks/).focus();
await page.keyboard.press("s");
await page.waitForTimeout(200);
step("split adds a clip", (await clips()).length === n0 + 1, `${n0} -> ${(await clips()).length}`);

// 2. autosave and preview re-render
await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 8000 });
const saved = await api("/timeline");
step("autosave bumped the revision", saved.rev === before.rev + 1, `rev ${before.rev} -> ${saved.rev}`);
let info;
for (let i = 0; i < 60; i++) { info = await api(""); if (info.status === "done" && info.preview_rev === saved.rev) break; await page.waitForTimeout(500); }
step("preview re-rendered from the saved revision", info.status === "done" && info.preview_rev === saved.rev, `preview_rev=${info.preview_rev}`);

// 3. drag the right edge of a clip left (trim), with snapping
const target = page.locator('[data-clip]').nth(1);
await target.scrollIntoViewIfNeeded();
const b2 = await target.boundingBox();
const startDuration = (await api("/timeline")).clips.find((c) => c.id === (undefined))?.duration;
await page.mouse.move(b2.x + b2.width - 3, b2.y + b2.height / 2);
await page.mouse.down();
for (let i = 1; i <= 10; i++) await page.mouse.move(b2.x + b2.width - 3 - i * 8, b2.y + b2.height / 2);
await page.mouse.up();
await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 8000 });
const trimmed = await api("/timeline");
step("trim by dragging an edge was saved", trimmed.rev === saved.rev + 1, `rev ${trimmed.rev}`);

// 4. delete the selected clip, undo restores it
const countBefore = (await clips()).length;
await page.keyboard.press("Delete");
await page.waitForTimeout(200);
step("delete removes the clip", (await clips()).length === countBefore - 1);
await page.keyboard.press("Meta+z");
await page.waitForTimeout(200);
step("undo brings it back", (await clips()).length === countBefore);
await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 8000 });

// 5. reload: what we edited is what comes back
await page.reload();
await page.getByRole("region", { name: "Timeline" }).waitFor();
const final = await api("/timeline");
step("reload shows the saved edits", (await clips()).length === final.clips.length, `${final.clips.length} clips`);
step("no console errors or failed requests", problems.length === 0, problems.join(" | "));
await browser.close();
