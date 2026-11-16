// usage: node measure.mjs <port> <seconds>   (server from serve.py must be running)
import { chromium } from "playwright-core";
const port = process.argv[2] ?? "8899", seconds = +(process.argv[3] ?? 60);
const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});
const round = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === "number" ? +v.toFixed(1) : v]));
async function run(variant, { play, sync = false, layers = 3 }) {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${port}/?v=${variant}&layers=${layers}&sync=${sync ? 1 : 0}`);
  await page.evaluate(() => window.spike.boot());
  const out = {};
  if (play) out.play = round(await page.evaluate((s) => window.spike.play(s), play));
  out.scrub = round(await page.evaluate(() => window.spike.scrub(25)));
  await page.close();
  return out;
}
const results = {
  "A. proxy 960x540, keyframe every 0.5 s (3 video + 2 audio)": await run("proxy", { play: seconds }),
  "A2. same with drift correction (resync if > 40 ms)": await run("proxy", { play: Math.min(seconds, 30), sync: true }),
  "B. same size, long GOP": await run("longgop", { play: 0 }),
  "C. untouched 1080p sources (mixed fps, long GOP)": await run("source", { play: 20 }),
};
console.log(JSON.stringify(results, null, 2));
await browser.close();
