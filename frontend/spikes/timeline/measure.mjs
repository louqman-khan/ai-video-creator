// usage: node spikes/timeline/measure.mjs <vite-url, e.g. http://127.0.0.1:5742>
import { chromium } from "playwright-core";
const base = process.argv[2] ?? "http://127.0.0.1:5742";
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const r1 = (x) => +x.toFixed(1);

async function drag(n) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 500 } });
  await page.goto(`${base}/spikes/timeline/index.html?n=${n}`);
  await page.waitForFunction(() => window.ready === true);
  await page.evaluate(() => {
    window.__iv = []; window.__long = 0; let last = 0;
    const tick = (t) => { if (last) window.__iv.push(t - last); last = t; requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    new PerformanceObserver((l) => (window.__long += l.getEntries().length)).observe({ entryTypes: ["longtask"] });
  });
  const box = await page.locator('[data-clip="40"]').boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.waitForTimeout(300);
  await page.evaluate(() => { window.__iv = []; window.__long = 0; });
  const t0 = Date.now();
  await page.mouse.move(x, y); await page.mouse.down();
  for (let i = 1; i <= 240; i++) { await page.mouse.move(x + i * 2.5, y + Math.sin(i / 10) * 3); await page.waitForTimeout(8); }  // ~600 px, fast input
  await page.mouse.up();
  const secs = (Date.now() - t0) / 1000;
  const m = await page.evaluate(() => ({ iv: window.__iv.slice().sort((a, b) => a - b), long: window.__long }));
  await page.close();
  const pick = (p) => m.iv[Math.min(m.iv.length - 1, Math.floor(m.iv.length * p))];
  return { clips: n, frames: m.iv.length, fps: r1(m.iv.length / secs), medianFrameMs: r1(pick(0.5)), p95FrameMs: r1(pick(0.95)), maxFrameMs: r1(m.iv[m.iv.length - 1]), framesOver33ms: m.iv.filter((v) => v > 33).length, longTasks: m.long };
}
for (const n of [100, 300, 1000]) console.log(JSON.stringify(await drag(n)));
await browser.close();
