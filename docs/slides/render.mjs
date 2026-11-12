// Render docs/slides/aip-technical.html to aip-technical-{light,dark}.pdf and png/NN-{light,dark}.png (2x).
// Usage: node render.mjs [dir]   (dir holds aip-technical.html; default: this script's folder)
// Playwright comes from console/node_modules in this repository: run `npm install` in console/ first.
// Renders under the print layout with the slides at scale 1 and the page chrome hidden, so the
// PNGs are 3840x2160 and the PDFs have one page per slide.
import { createRequire } from "node:module";
const { chromium } = createRequire(new URL("../../console/package.json", import.meta.url))("playwright");
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
const dir = resolve(process.argv[2] ?? new URL(".", import.meta.url).pathname);
mkdirSync(resolve(dir, "png"), { recursive: true });
const browser = await chromium.launch();
for (const theme of ["light", "dark"]) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
  await page.emulateMedia({ media: "print", colorScheme: theme });
  await page.goto("file://" + resolve(dir, "aip-technical.html"));
  await page.evaluate((t) => { document.documentElement.setAttribute("data-theme", t); }, theme);
  await page.addStyleTag({ content: ":root{--k:1 !important} main{padding:0 !important;gap:0 !important} section.slide:last-of-type{break-after:auto !important;page-break-after:auto !important} body > :not(main){display:none !important} main{margin:0 !important}" });
  await page.waitForTimeout(300);
  const slides = await page.locator("section.slide").all();
  let n = 0;
  for (const s of slides) {
    n += 1;
    await s.scrollIntoViewIfNeeded();
    await s.screenshot({ path: resolve(dir, "png", `${String(n).padStart(2, "0")}-${theme}.png`) });
  }
  await page.emulateMedia({ media: "print", colorScheme: theme });
  await page.pdf({ path: resolve(dir, `aip-technical-${theme}.pdf`), width: "1920px", height: "1080px", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 }, preferCSSPageSize: false });
  console.log(theme, "slides:", n);
  await page.close();
}
await browser.close();
