// Render the invented cover art for the showcase fixture (media/fixtures/showcase).
// Usage: node site/scripts/covers.mjs <out-dir>   (writes <slug>.png, 1280x720)
// `just site-covers` runs this and converts the PNGs to webp.
import { chromium } from 'playwright-core';
import { launchOptions } from './browser.mjs';

const COVERS = [
  // slug, kicker, title, background, foreground, accent, decoration
  ['compilers', 'LECTURE 07', 'How Compilers<br>Actually Work', '#0f172a', '#38bdf8', '#f472b6', 'grid'],
  ['penny', 'EP. 112', 'The Penny<br>Problem', '#f59e0b', '#7c2d12', '#fde68a', 'coins'],
  ['cornerbar', 'SET TWO', 'Live at the<br>Corner Bar', '#1e1b4b', '#a78bfa', '#facc15', 'rings'],
  ['garden', 'PART 3', 'Gardening for<br>Lazy People', '#14532d', '#86efac', '#fef9c3', 'leaf'],
  ['bread', 'A WEEKEND BAKE', 'Bread,<br>Slowly', '#fef3c7', '#92400e', '#b45309', 'dots'],
  ['spreadsheet', 'SMALL QUESTIONS', 'A Short History<br>of the Spreadsheet', '#ecfeff', '#0e7490', '#0891b2', 'cells'],
  ['night', 'HOUR 3', 'Night Owl<br>Radio', '#020617', '#e2e8f0', '#6366f1', 'stars'],
  ['bikes', 'WORKSHOP', 'Fixing a<br>Flat in 5 Min', '#dc2626', '#fff', '#111', 'stripes'],
];

const DECORATION = {
  grid: c => `background-image:linear-gradient(${c}33 1px,transparent 1px),linear-gradient(90deg,${c}33 1px,transparent 1px);background-size:48px 48px`,
  coins: c => `background-image:radial-gradient(circle at 80% 50%,${c} 0 150px,transparent 151px),radial-gradient(circle at 92% 30%,${c}aa 0 110px,transparent 111px)`,
  rings: c => `background-image:repeating-radial-gradient(circle at 85% 50%,${c}55 0 6px,transparent 6px 40px)`,
  leaf: c => `background-image:radial-gradient(ellipse 260px 140px at 80% 50%,${c} 0 99%,transparent 100%)`,
  dots: c => `background-image:radial-gradient(${c}55 3px,transparent 4px);background-size:30px 30px`,
  cells: c => `background-image:linear-gradient(${c}44 2px,transparent 2px),linear-gradient(90deg,${c}44 2px,transparent 2px);background-size:160px 50px`,
  stars: c => `background-image:radial-gradient(${c} 2px,transparent 3px),radial-gradient(#fff8 1px,transparent 2px);background-size:90px 70px,37px 41px`,
  stripes: c => `background-image:repeating-linear-gradient(-45deg,${c}22 0 30px,transparent 30px 60px)`,
};

const outDir = process.argv[2];
if (!outDir) throw new Error('usage: node covers.mjs <out-dir>');

const browser = await chromium.launch(launchOptions());
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
for (const [slug, kicker, title, bg, fg, accent, deco] of COVERS) {
  await page.setContent(`<body style="margin:0"><div style="width:1280px;height:720px;background:${bg};${DECORATION[deco](accent)};
    display:flex;flex-direction:column;justify-content:center;padding:0 90px;box-sizing:border-box;
    font-family:Inter,'Helvetica Neue',Arial,sans-serif;color:${fg}">
    <div style="font-weight:800;letter-spacing:.2em;font-size:30px;color:${accent};margin-bottom:22px">${kicker}</div>
    <div style="font-weight:900;font-size:118px;line-height:.95;letter-spacing:-.04em">${title}</div></div></body>`);
  await page.screenshot({ path: `${outDir}/${slug}.png` });
}
await browser.close();
console.log(`wrote ${COVERS.length} covers to ${outDir}`);
