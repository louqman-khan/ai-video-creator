// usage: node e2e/bin.mjs <project-id> [ui-url]   (edits the project: use a COPY; needs internet for the stock search)
import { chromium } from "playwright-core";
const pid = process.argv[2];
const base = process.argv[3] ?? "http://127.0.0.1:5742";
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1200 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("response", (r) => r.status() >= 400 && console.log("  HTTP", r.status(), r.request().method(), r.url().replace(base, "")));
page.on("pageerror", (e) => problems.push(e.message));
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const api = (p) => fetch(`${base}/api/projects/${pid}${p}`).then((r) => r.json());

await page.goto(`${base}/projects/${pid}`);
await page.getByRole("region", { name: "Timeline" }).waitFor();
await page.getByRole("button", { name: "Add media…" }).click();
await page.getByRole("tab", { name: "Stock media" }).click();
await page.getByLabel("Search").fill("piano");
await page.getByLabel("Media type").selectOption("music");
await page.getByRole("button", { name: "Search" }).click();
await page.getByRole("list", { name: "Search results" }).waitFor({ timeout: 40000 });
const n = await page.getByRole("list", { name: "Search results" }).getByRole("listitem").count();
step("music search returns results", n > 0, `${n} results`);
const first = page.getByRole("list", { name: "Search results" }).getByRole("listitem").first();
const title = await first.locator(".bin-title").innerText();
await first.getByRole("button", { name: "Add at playhead" }).click();
await page.locator('[data-track="A2"] [data-clip]').waitFor({ timeout: 60000 });
step("the song is on a new audio track", true, title);
await page.waitForFunction(() => /All changes saved/.test(document.body.innerText), null, { timeout: 15000 });
const tl = await api("/timeline");
const song = Object.values(tl.assets).find((a) => a.kind === "audio" && a.source === "openverse");
step("saved with its licence", !!song && !!song.license, song && `${song.license}, ${song.duration} frames`);
step("no file path or download address reached the browser", !JSON.stringify(tl).includes("/Users/") && !("path" in song) && !("url" in song));
// the file is prepared (waveform) and the credits list it
let m;
for (let i = 0; i < 60; i++) { m = (await api("/media")).find((x) => x.asset_id === song.id); if (m?.status === "ready") break; await new Promise((r) => setTimeout(r, 500)); }
step("the song was prepared for editing", m?.status === "ready", JSON.stringify(m?.derived));
await page.locator('[data-track="A2"] canvas').first().waitFor({ timeout: 15000 }).catch(() => undefined);
let info;
for (let i = 0; i < 80; i++) { info = await api(""); if (info.status === "done" && info.preview_rev === tl.rev) break; await new Promise((r) => setTimeout(r, 500)); }
const credits = await fetch(`${base}/api/projects/${pid}/credits`).then((r) => r.text());
step("CREDITS lists the song", credits.includes(song.title.slice(0, 15)) || credits.includes(song.license), credits.split("\n").slice(-3).join(" | ").slice(0, 160));
step("no console errors", problems.length === 0, problems.join(" | ").slice(0, 300));
await browser.close();
