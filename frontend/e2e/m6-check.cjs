// v0.10.0 M6 browser check against the dev server (127.0.0.1:8765, admin/admin12345), fake AI on 127.0.0.1:8799.
// Every page in fa and en, light and dark: loads, no horizontal page overflow at 1024/1280/1920, no console error, no
// request to any host but 127.0.0.1, and the automated accessibility check (axe-core, WCAG 2.1 A/AA). With a screenshot
// directory it also saves a full-page screenshot of each page at 1440 px as <page>-<fa|en>-<light|dark>.png.
// Usage: NODE_PATH=$(npm root -g) node e2e/m6-check.cjs <out dir> src/i18n [screens dir] [--empty]
// With --empty the database is expected to be empty (fresh install): pages must still load with their empty states.
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const { execFileSync } = require('child_process');

const OUT = process.argv[2]; const I18N = process.argv[3]; const SCREENS = process.argv[4] && !process.argv[4].startsWith('--') ? process.argv[4] : null;
const EMPTY = process.argv.includes('--empty');
const SCREENS_ONLY = process.argv.includes('--screens-only');   // just the review screenshots (the checks ran already)
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';
const DB = process.env.BOMS_CHECK_DB || 'boms_dev';
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js', { paths: [process.cwd()] }), 'utf8');
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const psql = (sql) => execFileSync('sudo', ['-u', 'postgres', 'psql', '-d', DB, '-Atc', sql]).toString().trim();
const one = (sql) => { try { return psql(sql).split('\n')[0] || null; } catch { return null; } };

(async () => {
  const problems = [];
  const results = {};
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const external = new Set();
  await ctx.route('**/*', (route) => {
    const u = new URL(route.request().url());
    if (u.hostname !== '127.0.0.1' && u.protocol !== 'data:' && u.protocol !== 'blob:') { external.add(u.host); return route.abort(); }
    return route.continue();
  });
  let consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message.slice(0, 200)}`));
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = (document.cookie.match(/boms_csrf=([^;]+)/) || [])[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json().catch(() => null) };
  }, [method, path, body]);

  // ---- the pages, with real records from the database (or none on an empty one) ----
  const id = {
    shipmentCase: one("SELECT case_id FROM ops.shipment ORDER BY created_at DESC LIMIT 1"),
    closedCase: one("SELECT id FROM ops.\"case\" WHERE status = 'closed' ORDER BY updated_at DESC LIMIT 1"),
    tenderCase: one("SELECT case_id FROM ops.tender ORDER BY created_at DESC LIMIT 1"),
    quoteCase: one("SELECT case_id FROM ops.quote ORDER BY created_at DESC LIMIT 1"),
    party: one("SELECT party_id FROM ops.party_rating GROUP BY party_id ORDER BY count(*) DESC LIMIT 1")
      || one("SELECT id FROM core.party ORDER BY created_at DESC LIMIT 1"),
    inquiry: one("SELECT id FROM ops.inquiry ORDER BY created_at DESC LIMIT 1"),
    product: one("SELECT id FROM core.product ORDER BY created_at DESC LIMIT 1"),
    document: one("SELECT id FROM core.document ORDER BY created_at DESC LIMIT 1"),
    listing: one("SELECT l.id FROM ext.listing l JOIN ext.listing_detail d ON d.listing_id = l.id ORDER BY l.updated_at DESC LIMIT 1"),
  };
  const P = [
    ['command-center', '/command-center'], ['tasks', '/tasks'], ['finance-desk', '/finance'],
    ['listings', id.listing ? `/tenders?deadline=any&include_old=1&listing=${id.listing}` : '/tenders'], ['triage', '/tenders/triage'],
    ['parties', '/parties'], ['funnels', '/parties/funnels'], ['party', id.party && `/parties/${id.party}`],
    ['inquiries', '/sourcing'], ['inquiry', id.inquiry && `/sourcing/inquiries/${id.inquiry}`], ['catalog', '/sourcing/catalog'],
    ['product', id.product && `/sourcing/catalog/${id.product}`], ['templates', '/sourcing/templates'],
    ['cases', '/cases'], ['guarantees', '/cases/guarantees'],
    ['case', id.shipmentCase && `/cases/${id.shipmentCase}`], ['case-items', id.quoteCase && `/cases/${id.quoteCase}?tab=items`],
    ['case-offers', id.quoteCase && `/cases/${id.quoteCase}?tab=offers`], ['cost-sheet', id.quoteCase && `/cases/${id.quoteCase}?tab=costing`],
    ['quotes', id.quoteCase && `/cases/${id.quoteCase}?tab=quotes`], ['tender', id.tenderCase && `/cases/${id.tenderCase}?tab=tender`],
    ['order', id.shipmentCase && `/cases/${id.shipmentCase}?tab=order`], ['purchase', id.shipmentCase && `/cases/${id.shipmentCase}?tab=purchase`],
    ['shipment', id.shipmentCase && `/cases/${id.shipmentCase}?tab=logistics`], ['delivery', id.shipmentCase && `/cases/${id.shipmentCase}?tab=delivery`],
    ['case-finance', id.closedCase && `/cases/${id.closedCase}?tab=finance`], ['execution', '/execution'],
    ['documents', '/documents'], ['document', id.document && `/documents/${id.document}`], ['verify', '/documents/verify'],
    ['settings', '/settings'], ['basedata', '/settings/basedata/countries'], ['events', '/settings/events'], ['system', '/settings/system'],
    ['costing-settings', '/settings/costing'], ['letterhead', '/settings/letterhead'], ['setad-settings', '/settings/setad'],
    ['tenders-settings', '/settings/tenders'], ['company-documents', '/settings/company-documents'], ['execution-settings', '/settings/execution'],
    ['ai-settings', '/settings/ai'], ['coding', '/settings/coding'], ['reference', '/settings/reference'],
  ].filter(([, url]) => url);

  const axeRun = async () => {
    // through the DevTools protocol: the page's own Content-Security-Policy (no inline script) stays in force
    if (!(await page.evaluate(() => !!window.axe))) await page.evaluate(AXE);
    return page.evaluate(async () => {
      const r = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } });
      return r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, target: v.nodes[0]?.target?.join(' '), html: v.nodes[0]?.html?.slice(0, 140) }));
    });
  };
  const settle = async () => {
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(400);
  };

  // login page first (axe on it, both languages come from the browser)
  await page.goto(BASE); await page.waitForSelector('#username');
  for (const v of await axeRun()) problems.push(`login a11y: ${v.id} (${v.impact}) ${v.target}`);
  if (SCREENS) for (const lang of ['fa']) await page.screenshot({ path: `${SCREENS}/login-${lang}-light.png`, fullPage: true });
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');

  try {
    for (const lang of ['fa', 'en']) {
      for (const theme of ['light', 'dark']) {
        await call('PATCH', '/api/me', { language: lang, theme, calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
        for (const [name, url] of P) {
          const key = `${name} ${lang} ${theme}`;
          consoleErrors = [];
          await page.setViewportSize({ width: 1440, height: 900 });
          await page.goto(BASE + url);
          await page.waitForSelector('main h1, main [data-testid=screening-workspace], main [data-testid=triage]', { timeout: 15000 })
            .catch(() => problems.push(`${key}: no page heading`));
          await settle();
          const crashed = await page.locator('main [data-testid=error-state]').count();
          if (crashed) problems.push(`${key}: error state shown`);
          if (SCREENS) {
            // the shell scrolls inside <main>, so «full page» means the main area's whole height: grow the window to it
            const h = await page.evaluate(() => { const m = document.querySelector('main'); return m ? m.scrollHeight + m.getBoundingClientRect().top : 900; });
            await page.setViewportSize({ width: 1440, height: Math.min(Math.max(900, Math.ceil(h)), 12000) }); await page.waitForTimeout(300);
            await page.screenshot({ path: `${SCREENS}/${name}-${lang}-${theme}.png`, fullPage: true });
            await page.setViewportSize({ width: 1440, height: 900 });
          }
          if (SCREENS_ONLY) continue;
          if (theme === 'light' || lang === 'fa') {               // a11y in both themes for fa, light for en (same markup)
            const v = await axeRun();
            results[key] = v.length;
            for (const x of v) problems.push(`${key} a11y: ${x.id} (${x.impact}, ${x.nodes}) ${x.target} ${x.html}`);
          }
          for (const width of [1024, 1280, 1920]) {
            await page.setViewportSize({ width, height: 900 }); await page.waitForTimeout(150);
            const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
            if (wide > 1) problems.push(`${key} ${width}: page overflows by ${wide}px`);
          }
          for (const e of consoleErrors) problems.push(`${key}: console ${e}`);
        }
      }
    }
  } catch (e) { problems.push(`CRASH: ${e.message.split('\n')[0]}`); await page.screenshot({ path: `${OUT}/crash.png` }); }
  for (const h of external) problems.push(`external request blocked: ${h}`);
  console.log(JSON.stringify({ empty: EMPTY, pages: P.length, ids: id, a11y: results, problems }, null, 1));
  await browser.close();
})();
