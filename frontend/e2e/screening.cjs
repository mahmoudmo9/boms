// v0.5.0 browser check of the Setad screening workspace (Tenders & Calls) on the dev server (127.0.0.1:8765,
// admin/admin12345) with listings already fetched from the offline fake host. fa and en, 1280 and 1024 px, light and
// dark: search / organisation search / note keep focus while typing, selects are not clipped, no horizontal page
// scroll, chips and counts, column chooser (remembered), "select all results" + bulk star / unstar, panel actions.
// Usage: NODE_PATH=$(npm root -g) node e2e/screening.cjs <screenshot dir> src/i18n
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = 'http://127.0.0.1:8765';
// every listing, whatever its deadline: the fake host's deadlines are relative to the day it was fetched, so the
// number still open varies by day (and a later fetch marks earlier rows old); the checks below need 100+ rows
const LIST = `${BASE}/tenders?deadline=any&include_old=1`;
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(10000);
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const shot = async (name) => page.screenshot({ path: `${OUT}/${name}.png` });
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) problems.push(`overflow: ${label}`); };
  const check = (r, key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${r.lang}: ${key} ${detail ?? ''}`); };
  const typeCheck = async (r, label, selector, text) => {
    const loc = page.locator(selector).first();
    await loc.click(); await loc.fill(''); await loc.pressSequentially(text, { delay: 25 });
    const res = await loc.evaluate((el, text) => ({ focused: document.activeElement === el, value: el.value }), text);
    check(r, `focus ${label}`, res.focused && res.value === text, JSON.stringify(res));
  };
  const selectClip = (label) => page.evaluate((label) => {
    const out = []; const canvas = document.createElement('canvas').getContext('2d');
    for (const s of document.querySelectorAll('select')) {
      if (!s.offsetParent) continue;
      const cs = getComputedStyle(s); canvas.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const avail = s.clientWidth - parseFloat(cs.paddingInlineStart) - parseFloat(cs.paddingInlineEnd);
      const widest = Math.max(...[...s.options].map((o) => canvas.measureText(o.text).width));
      if (widest > avail + 0.5) out.push(`${label}: ${s.getAttribute('aria-label') || s.id} needs ${widest.toFixed(1)}px, has ${avail.toFixed(1)}px`);
    }
    return out;
  }, label);
  const checkSelects = async (r, label) => { const c = await selectClip(`${r.lang} ${label}`); if (c.length) problems.push(...c); };
  const total = async () => Number((await page.locator('[data-testid=listing-total]').innerText()).replace(/[^\d۰-۹]/g, '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));
  const settle = () => page.waitForLoadState('networkidle');
  const waitTotal = async (n) => {   // the list refetches after a change; wait for the expected total (max 8 s)
    const ok = typeof n === 'function' ? n : (v) => v === n;
    for (let i = 0; i < 40; i++) { if (ok(await total())) return true; await page.waitForTimeout(200); }
    return false;
  };
  let step = '';

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  const results = [];
  try {
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      await call('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      step = `${lang} start`;
      for (const source of ['setad_purchase', 'setad_tender'])   // start from a clean screening state
        await call('POST', '/api/listings/bulk', { filters: { source, include_old: true }, action: 'unstar' });
      await page.evaluate(() => { try { localStorage.removeItem('boms.listings.columns.setad_purchase'); localStorage.removeItem('boms.listings.pageSize'); } catch (e) {} });
      await page.goto(LIST);
      await page.locator('[data-testid=listing-table] tbody tr').first().waitFor();
      check(r, 'sidebar label', await page.getByText(t('nav.tenders')).first().isVisible());
      const all = await total();
      check(r, 'listings shown', all >= 100, String(all));
      // search: typing keeps focus; the result follows after the debounce
      await typeCheck(r, 'search', '[data-testid=listing-search]', lang === 'fa' ? 'پمپ' : 'پمپ');
      await page.waitForTimeout(700); await settle();     // the search reaches the URL after a 350 ms debounce
      const searched = await total();
      check(r, 'search narrows the list', searched > 0 && searched < all, `${searched} of ${all}`);
      await page.locator('[data-testid=clear-filters]').click(); await page.goto(LIST); await page.locator('[data-testid=listing-table] tbody tr').first().waitFor();
      await page.waitForTimeout(500); await settle();
      check(r, 'clear filters', (await total()) === all);
      // organisation multi-pick with its own search
      await page.locator('[data-testid=org-picker]').click();
      const dlg = page.getByRole('dialog');
      await typeCheck(r, 'organisation search', `[aria-label="${t('listings.searchOrganizations')}"]`, lang === 'fa' ? 'بیمارستان' : 'بیمارستان');
      step = `${lang} organisation filter`;
      const orgs = await call('POST', '/api/listings/facets/organization?q=' + encodeURIComponent('بیمارستان'), { source: 'setad_purchase' });
      const org = orgs.body[0].value;                     // the list re-renders while the search settles: pick by name
      await dlg.getByRole('checkbox', { name: org, exact: true }).click();   // controlled box: it shows checked once the URL updates
      await page.waitForURL(/organizations=/);
      await dlg.getByRole('button', { name: t('common.close') }).last().click();
      check(r, 'organisation filter', await waitTotal((v) => v > 0 && v < all), `${await total()}`);
      await page.locator('[data-testid=clear-filters]').click(); await page.goto(LIST); await settle();
      // chips carry counts over the whole result
      check(r, 'chip counts', /\d|[۰-۹]/.test(await page.locator('[data-testid=chip-all]').innerText()));
      // column chooser: show "documents", remembered after reload
      await page.locator('[data-testid=column-chooser]').click();
      await page.getByRole('checkbox', { name: t('listings.cols.documents'), exact: true }).click();
      await page.locator('[data-testid=column-chooser]').click();
      await page.reload(); await page.locator('[data-testid=listing-table] tbody tr').first().waitFor();
      check(r, 'column chooser remembered', (await page.locator('thead th', { hasText: t('listings.cols.documents') }).count()) === 1);
      // 100 rows per page (remembered), select the page, then all results; bulk star and unstar
      await page.getByLabel(t('listings.pageSize')).selectOption('100'); await settle();
      check(r, 'page size', (await page.locator('[data-testid=listing-table] tbody tr').count()) === 100);
      step = `${lang} bulk star`;
      await page.getByRole('checkbox', { name: t('listings.selectPage') }).check();
      await page.locator('[data-testid=select-all-results]').click();
      const barText = (await page.locator('[data-testid=bulk-bar]').innerText()).replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace(/[,٬]/g, '');
      check(r, 'select all results', barText.includes(String(all)), barText.slice(0, 80));
      await page.locator('[data-testid=bulk-bar]').getByRole('button', { name: `★ ${t('listings.star')}` }).click();
      await settle();
      const starredText = await page.locator('[data-testid=chip-starred]').innerText();
      await page.locator('[data-testid=chip-starred]').click(); await settle();
      check(r, 'bulk star over all results', await waitTotal(all), `${await total()} vs ${all} (${starredText})`);
      step = `${lang} bulk unstar`;
      await page.locator('[data-testid=bulk-bar]').waitFor({ state: 'detached' }).catch(() => {});
      await page.getByRole('checkbox', { name: t('listings.selectPage') }).check();
      const sel = page.locator('[data-testid=select-all-results]');
      if (await sel.count()) await sel.click();
      await page.locator('[data-testid=bulk-bar]').getByRole('button', { name: t('listings.unstar') }).click();
      await settle();
      check(r, 'bulk unstar', await waitTotal(0));
      await page.locator('[data-testid=chip-starred]').click(); await settle();
      await waitTotal(all);
      // side panel: open, star, dismiss dialog, note keeps focus
      await page.locator('[data-testid=listing-table] tbody tr button').first().click();
      const panel = page.locator('[data-testid=listing-panel]');
      await panel.waitFor();
      await panel.getByRole('button', { name: `★ ${t('listings.star')}` }).click();
      await panel.getByText(t('listings.status.starred')).first().waitFor();
      await panel.locator('[data-testid=panel-tab-screening]').click();   // v0.6.0: the note is on the «بررسی» tab
      await typeCheck(r, 'panel note', '#listing-note', lang === 'fa' ? 'تماس با تأمین‌کننده' : 'call the supplier');
      await page.locator('#listing-note').press('Tab'); await settle();
      await panel.getByRole('button', { name: t('listings.dismiss'), exact: true }).click();
      await checkSelects(r, 'dismiss dialog');
      await page.getByRole('dialog').getByRole('button', { name: t('common.cancel') }).click();
      await checkSelects(r, 'filters 1280');
      await overflow(`${lang} 1280`);
      await shot(`${lang}-1280-light`);
      // tenders tab: free / paid chips
      step = `${lang} tenders tab`;
      await page.locator('[data-testid=tab-setad_tender]').click();
      await page.locator('[data-testid=chip-free]').waitFor();
      const tenders = await call('POST', '/api/listings/query', { source: 'setad_tender', page: 1, page_size: 100 });
      const want = tenders.body.counts.free;
      check(r, 'tender list', await waitTotal(tenders.body.total), `${await total()} vs ${tenders.body.total}`);
      const free = (await page.locator('[data-testid=chip-free]').innerText()).replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d));
      check(r, 'free documents counted', want > 0 && free.trim().endsWith(String(want)), `${free} vs ${want}`);
      await shot(`${lang}-1280-tenders`);
      // 1024 px, dark
      await page.setViewportSize({ width: 1024, height: 800 });
      await call('PATCH', '/api/me', { theme: 'dark' });
      await page.goto(LIST); await page.locator('[data-testid=listing-table] tbody tr').first().waitFor();
      await page.locator('[data-testid=listing-table] tbody tr button').first().click();
      await page.locator('[data-testid=listing-panel]').waitFor(); await settle();
      await overflow(`${lang} 1024`);
      await checkSelects(r, 'filters 1024');
      await shot(`${lang}-1024-dark`);
      await call('PATCH', '/api/me', { theme: 'light' });
      await page.setViewportSize({ width: 1280, height: 900 });
      results.push(r);
    }
  } catch (e) {
    problems.push(`exception at ${step}: ${e.message.split('\n')[0]}`);
    await shot('exception');
  }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
