// v0.10.1 section 3.1 browser check: the sidebar is a 72 px icon rail; it expands over the content on hover (the
// content does not move), English labels never truncate, pinning keeps it open beside the content across a reload,
// and unpinning returns to the rail. Usage: NODE_PATH=$(npm root -g) node e2e/rail.cjs <out dir>
const { chromium } = require('playwright');
const OUT = process.argv[2];
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = []; const results = {};
  const check = (k, ok, d) => { results[k] = ok ? true : `FAIL ${d ?? ''}`; if (!ok) problems.push(`${k} ${d ?? ''}`); };
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  try {
    await page.goto(BASE + '/'); await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
    await page.waitForSelector('aside');
    await page.evaluate(async () => { const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
      await fetch('/api/me', { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: JSON.stringify({ language: 'en' }) });
      localStorage.removeItem('boms.nav.pinned'); });
    await page.goto(BASE + '/command-center'); await page.waitForTimeout(1500);
    const w = async () => Math.round((await page.locator('[data-testid=sidebar]').boundingBox()).width);
    const mainX = async () => Math.round((await page.locator('#main').boundingBox()).x);
    check('collapsed is 72 px', (await w()) === 72, String(await w()));
    const before = await mainX();
    await page.locator('[data-testid=sidebar]').hover(); await page.waitForTimeout(400);
    check('hover expands', (await w()) >= 272, String(await w()));
    check('content does not move on hover', (await mainX()) === before);
    check('no truncated label', (await page.evaluate(() => [...document.querySelectorAll('[data-testid=sidebar] nav a span')].filter((s) => s.scrollWidth > s.clientWidth + 1).length)) === 0);
    await page.screenshot({ path: `${OUT}/rail-hover-en.png` });
    await page.locator('[data-testid=nav-pin]').click(); await page.mouse.move(1200, 500); await page.waitForTimeout(400);
    check('pinned stays open', (await w()) >= 272);
    check('pinned pushes content', (await mainX()) >= 272);
    await page.reload(); await page.waitForTimeout(1500);
    check('pin kept after reload', (await w()) >= 272);
    await page.locator('[data-testid=nav-pin]').click(); await page.mouse.move(1200, 500); await page.waitForTimeout(400);
    check('unpinned returns to the rail', (await w()) === 72, String(await w()));
    await page.locator('[data-testid=open-palette]').focus();
    for (let i = 0; i < 40 && !(await page.evaluate(() => !!document.activeElement?.closest('[data-testid=sidebar]'))); i++) await page.keyboard.press('Shift+Tab');
    await page.waitForTimeout(300);
    check('keyboard focus expands', (await w()) >= 272);
    await page.locator('[data-testid=sidebar] nav a').nth(2).click();
    check('a click on a module closes the rail', (await w()) === 72, String(await w()));
  } catch (e) { problems.push(`exception: ${String(e.message).split('\n')[0]}`); }
  await browser.close();
  console.log(JSON.stringify({ results, problems }, null, 1));
})();
