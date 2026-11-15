// v0.10.1 section 3.3: render the main pages in fa and fail on a Latin digit outside a <bdi> (codes, IDs, IBAN,
// phone, e-mail, URLs and model names stay Latin inside <bdi>); inputs, <code>, <pre>, sr-only text and charts'
// hidden data tables are skipped. Usage: NODE_PATH=$(npm root -g) node e2e/digits.cjs <out dir>
const { chromium } = require('playwright');
const OUT = process.argv[2];
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';
const PAGES = ['/command-center', '/tasks', '/cases', '/parties', '/tenders', '/finance', '/execution', '/documents',
  '/settings/ai', '/settings/reference', '/settings/events', '/settings/system', '/sourcing/catalog'];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  const problems = [];
  const found = {};
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  await page.evaluate(async () => { const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    await fetch('/api/me', { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: JSON.stringify({ language: 'fa' }) }); });
  const extra = [];
  try {
    const cases = await page.evaluate(async () => (await (await fetch('/api/cases?page_size=3')).json()).items.map((c) => c.id));
    for (const id of cases.slice(0, 2)) extra.push(`/cases/${id}`, `/cases/${id}?tab=finance`, `/cases/${id}?tab=logistics`);
    const parties = await page.evaluate(async () => (await (await fetch('/api/parties?page_size=2')).json()).items.map((c) => c.id));
    for (const id of parties.slice(0, 1)) extra.push(`/parties/${id}`);
  } catch { /* lists empty: the main pages still run */ }
  for (const path of [...PAGES, ...extra]) {
    await page.goto(BASE + path);
    await page.waitForTimeout(2200);
    const hits = await page.evaluate(() => {
      const out = [];
      const skip = (el) => el.closest('bdi, code, pre, input, textarea, select, option, script, style, svg, .sr-only, [data-latin], [aria-hidden=true]');
      const walker = document.createTreeWalker(document.querySelector('#main') || document.body, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = n.textContent || '';
        if (!/[0-9]/.test(text) || !n.parentElement || skip(n.parentElement)) continue;
        const r = n.parentElement.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        out.push(`${n.parentElement.tagName.toLowerCase()}${n.parentElement.dataset.testid ? `[${n.parentElement.dataset.testid}]` : ''}: ${text.trim().slice(0, 80)}`);
      }
      return [...new Set(out)].slice(0, 25);
    });
    if (hits.length) { found[path] = hits; problems.push(`${path}: ${hits.length} Latin digit run(s)`); }
  }
  await browser.close();
  console.log(JSON.stringify({ found, problems }, null, 1));
})();
