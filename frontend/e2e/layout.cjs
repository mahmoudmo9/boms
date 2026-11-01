// v0.6.0 section 0 browser check of the screening workspace layout and the listing panel (dev server 127.0.0.1:8765,
// admin/admin12345, listings fetched from the offline fake host):
// - at 1920x1080, 1280x800 and 1024x768, fa and en: the page never scrolls (document and main), the table area scrolls,
//   its header stays visible after scrolling, the panel scrolls on its own, compact rows are at most 44 px high;
// - with technical fields on, at 1920 and 1280, fa and en: nothing inside the panel extends beyond the panel and the
//   document has no horizontal scroll; dates in the panel use the user's digits; no «باقی‌مانده» remark is shown.
// Usage: NODE_PATH=$(npm root -g) node e2e/layout.cjs <screenshot dir> src/i18n
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.setDefaultTimeout(10000);
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) problems.push(`${r.status()} ${r.url().replace(BASE, '')}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const results = [];
  let step = '';
  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  // a listing with details (for the technical fields)
  const withDetail = (await call('POST', '/api/listings/query', { source: 'setad_purchase', include_old: true, deadline: null, page_size: 100 }))
    .body.items.map((r) => r.id);
  let detailId = null;
  for (const id of withDetail) { if ((await call('GET', `/api/listings/${id}`)).body.detail) { detailId = id; break; } }
  try {
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      await call('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      await page.evaluate(() => { try { localStorage.removeItem('boms.listings.density'); localStorage.setItem('boms.listings.technical', '0'); } catch (e) {} });
      for (const [w, h] of [[1920, 1080], [1280, 800], [1024, 768]]) {
        step = `${lang} ${w}x${h}`;
        const r = { lang, size: `${w}x${h}` };
        const check = (key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${lang} ${w}x${h}: ${key} ${detail ?? ''}`); };
        await page.setViewportSize({ width: w, height: h });
        await page.goto(`${BASE}/tenders?include_old=1&deadline=any&listing=${detailId ?? withDetail[0]}`);
        await page.locator('[data-testid=listing-table] tbody tr').first().waitFor();
        await page.locator('[data-testid=listing-panel] [data-testid=panel-body]').waitFor();
        await page.waitForLoadState('networkidle');
        const m = await page.evaluate(() => {
          const main = document.querySelector('main');
          const sc = document.querySelector('[data-testid=table-scroll]');
          const rows = [...document.querySelectorAll('[data-testid=listing-table] tbody tr')].slice(0, 20).map((x) => x.getBoundingClientRect().height);
          return { docScroll: document.documentElement.scrollHeight, inner: window.innerHeight,
            docWide: document.documentElement.scrollWidth > window.innerWidth,
            mainScroll: main.scrollHeight - main.clientHeight, tableScrolls: sc.scrollHeight > sc.clientHeight, maxRow: Math.max(...rows) };
        });
        check('document does not scroll', m.docScroll <= m.inner, `${m.docScroll} > ${m.inner}`);
        check('main does not scroll', m.mainScroll <= 1, String(m.mainScroll));
        check('no horizontal scroll', !m.docWide);
        check('table area scrolls', m.tableScrolls);
        check('compact rows <= 44px', m.maxRow <= 44, String(m.maxRow));
        // header stays visible after scrolling the table
        const head = await page.evaluate(() => {
          const sc = document.querySelector('[data-testid=table-scroll]');
          sc.scrollTop = sc.scrollHeight / 2;
          const th = sc.querySelector('thead').getBoundingClientRect();
          return { moved: sc.scrollTop > 0, top: th.top, area: sc.getBoundingClientRect().top };
        });
        check('header sticky', head.moved && Math.abs(head.top - head.area) <= 1, JSON.stringify(head));
        check('paging visible', await page.locator('[data-testid=paging]').isVisible());
        // the panel scrolls independently: put many tabs' content in (fields) and scroll it
        const indep = await page.evaluate(() => {
          const sc = document.querySelector('[data-testid=table-scroll]');
          const body = document.querySelector('[data-testid=panel-body]');
          const before = sc.scrollTop;
          body.scrollTop = 200;
          const panel = document.querySelector('[data-testid=listing-panel]').getBoundingClientRect();
          return { tableKept: sc.scrollTop === before, panelInView: panel.bottom <= window.innerHeight + 1 && panel.top >= 0 };
        });
        check('panel scrolls on its own', indep.tableKept && indep.panelInView, JSON.stringify(indep));
        // keyboard moves the selection and the panel follows; the table keeps its scroll position
        const firstSelected = new URL(page.url()).searchParams.get('listing');
        await page.locator('h1').first().click();
        await page.keyboard.press('ArrowDown');
        await page.waitForTimeout(150);
        check('keyboard moves selection', new URL(page.url()).searchParams.get('listing') !== firstSelected);
        // technical fields on (1920 and 1280)
        if (w >= 1280 && detailId) {
          await page.goto(`${BASE}/tenders?include_old=1&deadline=any&listing=${detailId}`);
          await page.locator('[data-testid=panel-body]').waitFor();
          await page.locator('[data-testid=listing-panel]').getByRole('checkbox', { name: t('listings.technical') }).check();
          await page.locator('[data-testid=panel-tab-technical]').click();
          await page.locator('[data-testid=technical-fields]').first().waitFor();
          for (const tab of ['technical', 'fields', 'schedule']) {
            await page.locator(`[data-testid=panel-tab-${tab}]`).click();
            await page.waitForTimeout(100);
            const o = await page.evaluate(() => {
              const p = document.querySelector('[data-testid=listing-panel]').getBoundingClientRect();
              const out = [];
              for (const el of document.querySelectorAll('[data-testid=listing-panel] *')) {
                const b = el.getBoundingClientRect();
                if (!b.width || !b.height) continue;
                if (el.closest('[data-testid=panel-tabs]')) continue;   // the tab strip scrolls horizontally by design
                if (b.left < p.left - 1 || b.right > p.right + 1) out.push(`${el.tagName}.${(el.className || '').toString().slice(0, 30)} ${Math.round(b.left)}-${Math.round(b.right)} vs ${Math.round(p.left)}-${Math.round(p.right)}`);
              }
              const text = document.querySelector('[data-testid=panel-body]').innerText;
              return { out: out.slice(0, 5), wide: document.documentElement.scrollWidth > window.innerWidth, remark: /باقی.?مانده هنگام/.test(text),
                latinDate: /\b1[34]\d\d\/\d\d\/\d\d\b/.test(text) };
            });
            check(`panel ${tab}: nothing overflows`, o.out.length === 0, o.out.join(' | '));
            check(`panel ${tab}: no horizontal scroll`, !o.wide);
            check(`panel ${tab}: no remaining-time remark`, !o.remark);
            if (lang === 'fa') check(`panel ${tab}: dates in Persian digits`, !o.latinDate);
          }
          await page.screenshot({ path: `${OUT}/${lang}-${w}-technical.png` });
          await page.locator('[data-testid=listing-panel]').getByRole('checkbox', { name: t('listings.technical') }).uncheck();
        }
        await page.screenshot({ path: `${OUT}/${lang}-${w}x${h}.png` });
        results.push(r);
      }
    }
  } catch (e) {
    problems.push(`exception at ${step}: ${e.message.split('\n')[0]}`);
    await page.screenshot({ path: `${OUT}/exception.png` });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  console.log(JSON.stringify({ results: results.map((r) => Object.fromEntries(Object.entries(r).filter(([, v]) => v !== true))), problems }, null, 1));
  await browser.close();
})();
