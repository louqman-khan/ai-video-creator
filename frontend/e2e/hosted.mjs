// usage: node e2e/hosted.mjs <base-url> <server-work-dir> <audio-file>
// The hosted mode in a real browser: sign-up with e-mail verification, log-in, a project that only its owner can see, CSP, cookies, delete the account.
import { chromium } from "playwright-core";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
const [base, work, audio] = process.argv.slice(2);
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const step = (n, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${n} ${extra}`); if (!ok) process.exitCode = 1; };
const PASSWORD = "correct horse battery";
const mailLink = (to, kind) => {
  const files = readdirSync(join(work, "outbox")).sort().reverse();
  for (const f of files) { const t = readFileSync(join(work, "outbox", f), "utf8"); const m = new RegExp(`To: ${to}[\\s\\S]*?${kind}\\?token=([\\w-]+)`).exec(t); if (m) return m[1]; }
  throw new Error(`no ${kind} mail for ${to}`);
};

async function person(label) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1500 } });
  const page = await ctx.newPage();
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("response", (r) => r.status() >= 400 && problems.push(`${r.status()} ${r.url().replace(/[0-9a-f]{32}/g, "<id>")}`));
  return { ctx, page, problems, label };
}
async function signUpAndLogIn(p, email) {
  await p.page.goto(`${base}/signup`);
  await p.page.getByLabel("E-mail").fill(email);
  await p.page.getByLabel("Password").fill(PASSWORD);
  await p.page.getByRole("checkbox").check();
  await p.page.getByRole("button", { name: "Create account" }).click();
  await p.page.getByRole("status").waitFor();
  await p.page.goto(`${base}/verify?token=${mailLink(email, "verify")}`);
  await p.page.getByRole("button", { name: "Confirm my address" }).click();
  await p.page.getByRole("link", { name: "Log in" }).click();
  await p.page.getByLabel("E-mail").fill(email);
  await p.page.getByLabel("Password").fill(PASSWORD);
  await p.page.getByRole("button", { name: "Log in" }).click();
  await p.page.getByRole("heading", { name: /Good (morning|afternoon|evening)|Working late/ }).waitFor();
}

const ann = await person("ann"), bob = await person("bob"), anon = await person("anon");
await anon.page.goto(`${base}/projects/0123456789abcdef0123456789abcdef`);
await anon.page.getByRole("heading", { name: "Log in" }).waitFor();
step("a visitor who is not logged in is sent to the log-in page", true);

await signUpAndLogIn(ann, "ann@example.com");
step("ann signed up, confirmed her e-mail, and is logged in", (await ann.page.getByRole("link", { name: "ann@example.com" }).count()) === 1);
const cookie = (await ann.ctx.cookies()).find((c) => c.name === "avc_session");
step("the session cookie is HttpOnly and SameSite=Lax", !!cookie && cookie.httpOnly && cookie.sameSite === "Lax", JSON.stringify({ httpOnly: cookie?.httpOnly, sameSite: cookie?.sameSite }));
step("script on the page cannot read the session", (await ann.page.evaluate(() => document.cookie)) === "");

// ann makes a project from a recording
await ann.page.goto(`${base}/new`);
await ann.page.getByLabel(/Narration audio/).setInputFiles(audio);
await ann.page.getByRole("button", { name: "Create video" }).click();
await ann.page.waitForURL(/\/projects\/[0-9a-f]{32}/);
const pid = ann.page.url().match(/projects\/([0-9a-f]{32})/)[1];
await ann.page.getByRole("region", { name: "Timeline" }).waitFor({ timeout: 540000 });
await ann.page.locator("canvas.live-canvas").waitFor();
await ann.page.waitForTimeout(3000);
const me = await (await ann.page.request.get(`${base}/api/auth/me`)).json();
step("one video used credits (a 25 second narration costs 1)", me.usage.credits.used === 1 && me.usage.credits.remaining === 9, JSON.stringify(me.usage.credits));
step("ann's project finished and the editor with its live preview works under the security headers", ann.problems.length === 0, ann.problems.join(" | ").slice(0, 300));
const headers = (await ann.page.request.get(`${base}/api/health`)).headers();
step("security headers are sent", headers["x-frame-options"] === "DENY" && headers["x-content-type-options"] === "nosniff" && headers["content-security-policy"].includes("default-src 'self'"));

// bob cannot see or reach it
await signUpAndLogIn(bob, "bob@example.com");
await bob.page.getByText("No projects yet").waitFor({ timeout: 15000 });
step("bob's project list is empty", (await bob.page.getByText("No projects yet").count()) === 1);
const direct = await bob.page.request.get(`${base}/api/projects/${pid}`);
const video = await bob.page.request.get(`${base}/api/projects/${pid}/video`);
step("bob gets 404 for ann's project and its video", direct.status() === 404 && video.status() === 404, `${direct.status()} / ${video.status()}`);
await bob.page.goto(`${base}/projects/${pid}`);
await bob.page.getByText("Project not found").waitFor();
step("bob opening ann's link sees 'Project not found'", true);
step("a visitor gets 401 for the video", (await anon.page.request.get(`${base}/api/projects/${pid}/video`)).status() === 401);
const forged = await bob.page.request.post(`${base}/api/projects/${pid}/export`, { headers: { "X-Requested-With": "" }, data: {} });
step("a request without the app's header is refused (403)", forged.status() === 403, String(forged.status()));

// ann's account page, logging out, deleting bob's account
await ann.page.goto(`${base}/account`);
await ann.page.getByText(/Projects: 1 of/).waitFor();
step("ann's account page shows her use", true);
await ann.page.getByRole("button", { name: "Log out" }).click();
await ann.page.getByRole("heading", { name: "Log in" }).waitFor();
step("logging out ends the session", (await ann.page.request.get(`${base}/api/projects`)).status() === 401);
await bob.page.goto(`${base}/account`);
await bob.page.getByRole("button", { name: "Delete my account…" }).click();
await bob.page.getByLabel("Type your password to confirm").fill(PASSWORD);
await bob.page.getByRole("button", { name: "Delete everything" }).click();
await bob.page.getByRole("heading", { name: "Log in" }).waitFor();
await bob.page.getByLabel("E-mail").fill("bob@example.com");
await bob.page.getByLabel("Password").fill(PASSWORD);
await bob.page.getByRole("button", { name: "Log in" }).click();
await bob.page.getByRole("alert").waitFor();
step("bob's deleted account can no longer log in", /wrong/.test(await bob.page.getByRole("alert").innerText()));
await ann.page.getByLabel("E-mail").fill("ann@example.com");
await ann.page.getByLabel("Password").fill(PASSWORD);
await ann.page.getByRole("button", { name: "Log in" }).click();
await ann.page.getByRole("heading", { name: "Your account" }).waitFor({ timeout: 15000 });   // she is taken back to the page she was on
step("ann logs in again and lands where she was (her account page)", true);
await ann.page.goto(`${base}/`);
await ann.page.getByRole("heading", { name: /Good (morning|afternoon|evening)|Working late/ }).waitFor();
step("the sidebar plan card shows 1 of 10 credits used", (await ann.page.getByText("1 of 10 video credits used this month.").count()) === 1);
step("her project is still there after bob's account was deleted", (await ann.page.request.get(`${base}/api/projects/${pid}`)).status() === 200 && (await ann.page.locator(".proj").count()) === 1);
await browser.close();
