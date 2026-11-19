// usage: node e2e/a11y-pages.mjs [ui-url] [project-id]   axe-core on the projects page, the new-project page and (with an id) the editor, light and dark
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
const base = process.argv[2] ?? "http://127.0.0.1:5742";
const axeSource = readFileSync(new URL("../node_modules/axe-core/axe.min.js", import.meta.url), "utf8");
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
for (const scheme of ["light", "dark"]) {
  const page = await browser.newPage({ colorScheme: scheme });
  for (const path of ["/", "/new", ...(process.argv[3] ? [`/projects/${process.argv[3]}`] : [])]) {
    await page.goto(base + path);
    await page.waitForTimeout(path.startsWith("/projects") ? 5000 : 1200);
    await page.addScriptTag({ content: axeSource });
    const detail = process.env.DETAIL === "1";
    const v = await page.evaluate(async (detail) => (await window.axe.run(document)).violations.map((x) => `${x.impact} ${x.id} x${x.nodes.length}` + (detail ? " [" + x.nodes.slice(0, 6).map((n) => n.target.join(" ") + " :: " + ((n.any[0] && n.any[0].message) || "").slice(0, 90)).join(" | ") + "]" : "")), detail);
    console.log(`${v.length === 0 ? "PASS" : "FAIL"} ${scheme} ${path} ${v.join("; ")}`);
    if (v.length) process.exitCode = 1;
  }
  await page.close();
}
await browser.close();
