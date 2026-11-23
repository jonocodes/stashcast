// Capture StashCast app screenshots for the marketing site.
// Usage: node site/scripts/screenshots.mjs <base-url> <out-dir>
// Expects a running instance seeded with `./manage.py seed_showcase` and an admin/admin
// superuser. `just site-screenshots` does all of that in a throwaway data dir, then
// converts these PNGs to webp under site/public/assets/app/.
import { chromium } from 'playwright-core';
import { fileURLToPath } from 'node:url';
import { launchOptions } from './browser.mjs';

const [base, outDir] = process.argv.slice(2);
if (!base || !outDir) throw new Error('usage: node screenshots.mjs <base-url> <out-dir>');

const DESKTOP = { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 };
const MOBILE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };

async function login(page) {
  await page.goto(`${base}/admin/login/?next=/admin/tools/grid/`);
  await page.fill('input[name=username]', 'admin');
  await page.fill('input[name=password]', 'admin');
  await page.click('[type=submit]');
  await page.waitForURL('**/admin/tools/grid/');
}

async function shoot(page, path, name) {
  await page.goto(`${base}${path}`);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${outDir}/${name}.png` });
}

const browser = await chromium.launch(launchOptions());
for (const scheme of ['dark', 'light']) {
  const desktop = await browser.newContext({ ...DESKTOP, colorScheme: scheme });
  const page = await desktop.newPage();
  await login(page);
  await shoot(page, '/admin/tools/grid/', `grid-${scheme}`);
  await shoot(page, '/admin/tools/list/', `list-${scheme}`);
  const item = await page.goto(`${base}/admin/tools/grid/`)
    .then(() => page.locator('a[href*="/admin/tools/item/"]').first().getAttribute('href'));
  await shoot(page, item, `item-${scheme}`);
  if (scheme === 'dark') await shoot(page, '/', 'home'); // the landing page is always dark
  await desktop.close();

  const mobile = await browser.newContext({ ...MOBILE, colorScheme: scheme });
  const phone = await mobile.newPage();
  await login(phone);
  await shoot(phone, '/admin/tools/grid/', `mobile-${scheme}`);
  await mobile.close();
}

// Social preview card: the site's own hero, rendered from the static file.
const site = new URL('../public/index.html', import.meta.url);
const og = await browser.newPage({ viewport: { width: 1200, height: 630 } });
await og.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' });
await og.goto(site.href);
await og.screenshot({ path: `${outDir}/og.png` });

await browser.close();
console.log(`screenshots written to ${outDir} (site: ${fileURLToPath(site)})`);
