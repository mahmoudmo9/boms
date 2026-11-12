// v0.10.0 milestone 3 browser check (Playwright) against the dev server on 127.0.0.1:8765 (admin/admin12345) with the
// worker running. No network host is contacted. For fa and en, light and dark, at 1024 / 1280 / 1920 px:
//  - the shell: sidebar (current module marked, collapse to icons and back), no horizontal page overflow;
//  - Ctrl+K and «/» open the palette; a case code finds the case first and Enter opens it; Esc closes;
//  - theme (light / dark / system) and language from the top bar, kept after a reload;
//  - «?» opens the shortcut sheet;
//  - live updates: «پشتیبان‌گیری» stays busy until the worker finishes the job, and the new backup row appears without
//    a reload; a party created elsewhere appears on an open party list within 2 s.
// Usage: NODE_PATH=$(npm root -g) node e2e/m3-flow.cjs <out dir>. Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const OUT = process.argv[2];
const BASE = 'http://127.0.0.1:8765';

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) problems.push(`console: ${m.text().slice(0, 200)}`); });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, p, body) => page.evaluate(async ([method, p, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(p, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, p, body]);
  const poll = async (fn, ms = 15000, every = 200) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(every); } return null; };
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) problems.push(`overflow: ${label}`); };
  const results = [];
  let step = '';
  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('[data-testid=sidebar]');
  try {
    const kase = (await call('POST', '/api/cases', { title: `Palette ${Date.now()}` })).body;
    const code = (await call('GET', `/api/cases/${kase.id}`)).body.code;
    for (const lang of ['fa', 'en']) {
      for (const theme of ['light', 'dark']) {
        const r = { lang, theme };
        const check = (key, cond, detail) => { r[key] = cond ? true : `FAIL ${detail ?? ''}`; if (!cond) problems.push(`${lang}/${theme}: ${key} ${detail ?? ''}`); };
        results.push(r);
        await call('PATCH', '/api/me', { language: lang, theme });
        for (const width of [1024, 1280, 1920]) {
          await page.setViewportSize({ width, height: 900 });
          await page.goto(`${BASE}/cases`);
          await page.waitForSelector('[data-testid=page-header], h1');
          await overflow(`${lang}/${theme} cases ${width}`);
        }
        await page.setViewportSize({ width: 1280, height: 900 });
        step = `${lang}/${theme} shell`;
        check('theme class', (await page.evaluate(() => document.documentElement.classList.contains('dark'))) === (theme === 'dark'));
        check('direction', (await page.evaluate(() => document.documentElement.dir)) === (lang === 'fa' ? 'rtl' : 'ltr'));
        check('current module marked', (await page.locator('[data-testid=nav-cases]').getAttribute('aria-current')) === 'page');
        await page.locator('[data-testid=nav-collapse]').click();
        check('sidebar collapses to icons', await page.locator('[data-testid=sidebar][data-collapsed]').count() === 1);
        await page.screenshot({ path: `${OUT}/${lang}-${theme}-collapsed.png` });
        await page.locator('[data-testid=nav-collapse]').click();
        check('live updates connected', await poll(async () => (await page.locator('[data-testid=live]').getAttribute('data-transport')) === 'stream', 8000));

        step = `${lang}/${theme} palette`;
        await page.keyboard.press('Control+k');
        await page.locator('[data-testid=command-palette]').waitFor();
        await page.keyboard.type(code);
        const first = page.locator('[data-testid=palette-row]').first();
        check('exact code first', await poll(async () => (await first.getAttribute('data-exact')) === 'true'), code);
        await page.screenshot({ path: `${OUT}/${lang}-${theme}-palette.png` });
        await page.keyboard.press('Enter');
        check('Enter opens the case', await poll(async () => page.url().endsWith(`/cases/${kase.id}`)), page.url());
        await page.locator('main').click({ position: { x: 5, y: 5 } });
        await page.keyboard.press('/');
        check('«/» opens the palette', await page.locator('[data-testid=command-palette]').isVisible());
        check('recent item listed', await poll(async () => (await page.locator('[data-group=recent] [data-testid=palette-row]').count()) >= 1, 3000, 100));
        await page.keyboard.press('Escape');
        check('Esc closes', await page.locator('[data-testid=command-palette]').count() === 0);
        await page.keyboard.press('?');
        check('«?» opens the shortcut sheet', await page.locator('[data-testid=shortcut-sheet]').isVisible());
        await page.keyboard.press('Escape');
      }
      // theme and language from the top bar, kept after a reload
      step = `${lang} top bar`;
      const r = results[results.length - 1];
      await page.locator('[data-testid=theme]').click();
      await page.getByRole('menuitemradio').nth(2).click();                     // system
      const me = await poll(async () => { const m = (await call('GET', '/api/me')).body; return m.theme === 'system' && m; }, 5000) || (await call('GET', '/api/me')).body;
      r['theme menu sets system'] = me.theme === 'system' || `FAIL ${me.theme}`;
      if (me.theme !== 'system') problems.push(`${lang}: theme menu`);
      await page.reload();
      await page.waitForSelector('[data-testid=sidebar]');
      r['theme kept after reload'] = (await page.evaluate(() => document.documentElement.dataset.theme)) === 'system' || 'FAIL';
    }
    // the language switch in the top bar
    step = 'language switch';
    await call('PATCH', '/api/me', { language: 'fa', theme: 'dark' });
    await page.goto(`${BASE}/cases`);
    await page.locator('[data-testid=language]').click();
    const switched = await poll(async () => (await page.evaluate(() => document.documentElement.lang)) === 'en');
    results.push({ 'language switch': switched || 'FAIL' });
    if (!switched) problems.push('language switch');

    // live: the backup button stays busy until the worker finished; the new row appears without a reload
    step = 'live backup';
    await page.goto(`${BASE}/settings/system`);
    const before = await page.locator('table').first().locator('tbody tr').count();
    const t0 = Date.now();
    await page.locator('[data-testid=backup-now]').click();
    const busy = await page.locator('[data-testid=backup-now]').getAttribute('aria-busy');
    const doubleClick = await page.locator('[data-testid=backup-now]').isDisabled();
    const finished = await poll(async () => (await page.locator('[data-testid=backup-now]').getAttribute('aria-busy')) === null, 120000, 300);
    const rowsAfter = await poll(async () => { const n = await page.locator('table').first().locator('tbody tr').count(); return n > before && n; }, 5000);
    results.push({ 'backup button busy while running': busy === 'true', 'no double submit': doubleClick, 'finished': Boolean(finished), 'new backup row without reload': Boolean(rowsAfter),
      'seconds': Math.round((Date.now() - t0) / 1000) });
    if (busy !== 'true' || !doubleClick || !finished || !rowsAfter) problems.push(`live backup: busy=${busy} disabled=${doubleClick} finished=${finished} rows=${rowsAfter}`);
    await page.screenshot({ path: `${OUT}/live-backup.png` });

    // live: a party created by another client appears on the open list within 2 s
    step = 'live party';
    await page.goto(`${BASE}/parties`);
    await page.waitForSelector('table');
    const name = `Live party ${Date.now()}`;
    const other = await browser.newContext();
    const p2 = await other.newPage();
    await p2.goto(BASE + '/'); await p2.fill('#username', 'admin'); await p2.fill('#password', 'admin12345'); await p2.click('button[type=submit]'); await p2.waitForSelector('[data-testid=sidebar]');
    const t1 = Date.now();
    await p2.evaluate(async (name) => { const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
      await fetch('/api/parties', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: JSON.stringify({ name_en: name, confirm_duplicate: true }) }); }, name);
    const seen = await poll(async () => (await page.getByText(name).count()) > 0, 6000, 100);
    const ms = Date.now() - t1;
    results.push({ 'party appears without reload': Boolean(seen), ms });
    if (!seen || ms > 2500) problems.push(`live party: seen=${Boolean(seen)} after ${ms} ms`);
    await other.close();
  } catch (e) {
    problems.push(`${step}: ${e.message.split('\n')[0]}`);
    await page.screenshot({ path: `${OUT}/failure.png` }).catch(() => {});
  }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
