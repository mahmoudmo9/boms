// v0.10.1 section 1.10 browser check: a paged list stays on its page through a live update, opening a row,
// a reload and back/forward; it goes back to page 1 only on a filter or sort change.
// Usage: NODE_PATH=$(npm root -g) node e2e/pagination.cjs <screenshot dir>. Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const OUT = process.argv[2];
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  const problems = [];
  const results = {};
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const check = (key, ok, detail) => { results[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${key} ${detail ?? ''}`); };
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const pageNo = () => new URL(page.url()).searchParams.get('page');
  const firstRow = () => page.locator('[data-testid=listing-table] tbody tr').first().getAttribute('data-listing').catch(() => null);
  const settle = () => page.waitForTimeout(1500);
  try {
    await page.goto(BASE + '/');
    await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
    await page.waitForSelector('aside');
    await call('PATCH', '/api/me', { language: 'en' });
    await page.goto(`${BASE}/tenders?deadline=any&include_old=1&size=100`);
    await page.locator('[data-testid=listing-table] tbody tr').first().waitFor();
    const p1 = await firstRow();
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await settle();
    const p2 = await firstRow();
    check('next shows page 2', pageNo() === '2' && p2 && p2 !== p1, `${pageNo()} ${p1} ${p2}`);

    // a live notice: a screening change on some listing (the event stream invalidates the list)
    const listing = (await call('POST', '/api/listings/query', { deadline: null, include_old: true, page: 1, page_size: 100, sort: 'deadline', dir: 'asc' })).body.items[0];
    await call('POST', `/api/listings/${listing.id}/screen`, { action: 'star' });
    await page.waitForTimeout(6000);
    check('live update keeps page 2', pageNo() === '2' && (await firstRow()) === p2, `${pageNo()}`);
    await call('POST', `/api/listings/${listing.id}/screen`, { action: 'unstar' });

    await page.locator('[data-testid=listing-table] tbody tr').nth(3).locator('button[title]').first().click();
    await settle();
    check('opening a row keeps page 2', pageNo() === '2' && new URL(page.url()).searchParams.get('listing'), page.url());

    await page.reload(); await page.locator('[data-testid=listing-table] tbody tr').first().waitFor(); await settle();
    check('reload keeps page 2', pageNo() === '2' && (await firstRow()) === p2, `${pageNo()}`);

    await page.goBack(); await settle();
    check('back returns to page 1', pageNo() === null && (await firstRow()) === p1, `${pageNo()}`);
    await page.goForward(); await settle();
    check('forward returns to page 2', pageNo() === '2' && (await firstRow()) === p2, `${pageNo()}`);
    await page.locator('[data-testid=listing-table] thead th button').nth(1).click(); await settle();
    check('a sort change goes to page 1', pageNo() === null, `${pageNo()}`);
    await page.screenshot({ path: `${OUT}/pagination.png` });
  } catch (e) {
    problems.push(`exception: ${String(e.message).split('\n')[0]}`);
  }
  await browser.close();
  console.log(JSON.stringify({ results, problems }, null, 1));
})();
