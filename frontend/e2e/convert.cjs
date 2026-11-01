// v0.5.0 M4 browser check on the dev server (127.0.0.1:8765, admin/admin12345) with listings fetched from the offline
// fake Setad host: convert a listing to an inquiry from the side panel, "From Setad" on the inquiry, the deadline-change
// banner and Apply, the command center "Setad" section, Settings -> Setad. fa and en, light and dark, 1280 and 1024 px.
// Usage: NODE_PATH=$(npm root -g) node e2e/convert.cjs <screenshot dir> src/i18n
// The deadline change is simulated with psql on the dev database (PGPASSWORD etc. from the environment).
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);
const psql = (sql) => execFileSync('psql', ['-h', '127.0.0.1', '-U', process.env.BOMS_DB_USER || 'boms_dev',
  process.env.BOMS_DB_NAME || 'boms_dev', '-Atc', sql], { env: { ...process.env, PGPASSWORD: process.env.BOMS_DB_PASSWORD || 'devpass-local' } }).toString().trim();

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
  const shot = async (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) problems.push(`overflow: ${label}`); };
  const check = (r, key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${r.lang}: ${key} ${detail ?? ''}`); };
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
      // a listing with its detail fetched (and, for fa, a downloaded attachment) that is not converted yet
      step = `${lang} pick`;
      const id = psql(`SELECT l.id FROM ext.listing l JOIN ext.listing_detail d ON d.listing_id = l.id
        LEFT JOIN ext.listing_screening s ON s.listing_id = l.id WHERE coalesce(s.status, 'new') NOT IN ('converted', 'dismissed')
        ORDER BY EXISTS (SELECT 1 FROM ext.listing_file f WHERE f.listing_id = l.id AND f.state = 'downloaded') DESC, l.external_no LIMIT 1`);
      if (!id) throw new Error('no listing with details left to convert (fetch details of another one first)');
      await call('POST', `/api/listings/${id}/screen`, { action: 'star' });
      step = `${lang} convert dialog`;
      await page.goto(`${BASE}/tenders?include_old=1&listing=${id}`);
      const panel = page.locator('[data-testid=listing-panel]');
      await panel.waitFor();
      await panel.getByRole('button', { name: t('listings.convert'), exact: true }).click();
      const dlg = page.locator('[data-testid=convert-dialog]');
      await dlg.waitFor();
      check(r, 'dialog shows items', (await dlg.locator('li').count()) >= 1);
      const clip = await selectClip(`${lang} convert dialog`); problems.push(...clip);
      await overflow(`${lang} convert dialog`);
      await shot(`${lang}-convert-dialog`);
      const buyer = page.locator('#convert-buyer');
      if (await buyer.locator('option[value=""]').count() === 0) await buyer.selectOption('new');
      const without = page.getByRole('checkbox', { name: t('listings.convertWithout') });
      if (await without.count()) await without.click();
      step = `${lang} convert`;
      await page.locator('[data-testid=convert-submit]').click();
      const dup = page.getByRole('checkbox', { name: t('listings.createAnyway') });
      await Promise.race([page.waitForURL(/\/sourcing\/inquiries\//), dup.waitFor()]);
      if (!/\/sourcing\/inquiries\//.test(page.url())) { await dup.click(); await page.locator('[data-testid=convert-submit]').click(); await page.waitForURL(/\/sourcing\/inquiries\//); }
      const inquiryId = page.url().split('/').pop();
      const origin = page.locator('[data-testid=setad-origin]');
      await origin.waitFor();
      check(r, 'from setad shown', (await origin.innerText()).includes(t('setad.fromSetad').split('«')[0].trim()));
      check(r, 'channel setad', await page.getByText(t('sourcing.channels.setad')).first().isVisible());
      await overflow(`${lang} inquiry 1280`);
      await shot(`${lang}-inquiry-from-setad`);
      // a later fetch moves the deadline on Setad by two days: banner, then Apply
      step = `${lang} deadline change`;
      psql(`UPDATE ext.listing SET response_deadline = response_deadline + interval '2 days' WHERE id = '${id}'`);
      await page.reload();
      const banner = page.locator('[data-testid=deadline-changed]');
      await banner.waitFor();
      check(r, 'deadline banner', await banner.isVisible());
      await shot(`${lang}-deadline-banner`);
      await banner.getByRole('button', { name: t('setad.applyDeadline') }).click();
      await banner.waitFor({ state: 'detached' });
      const applied = await call('GET', `/api/inquiries/${inquiryId}`);
      check(r, 'deadline applied', applied.body.response_due_at && new Date(applied.body.response_due_at).getTime()
        === new Date(psql(`SELECT to_char(response_deadline AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') FROM ext.listing WHERE id = '${id}'`)).getTime());
      // the listing shows "converted" with a link back
      step = `${lang} listing converted`;
      await page.goto(`${BASE}/tenders?include_old=1&listing=${id}`);
      await page.locator('[data-testid=listing-panel]').getByRole('link', { name: t('listings.convertedTo') }).waitFor();
      check(r, 'listing converted link', true);
      // command center: Setad section
      step = `${lang} command center`;
      await page.goto(`${BASE}/command-center`);
      const cc = page.locator('[data-testid=cc-setad]');
      await cc.waitFor();
      check(r, 'cc setad section', (await cc.innerText()).includes(t('cc.setad.title')));
      await overflow(`${lang} cc 1280`);
      await shot(`${lang}-cc-setad`);
      // Settings -> Setad: typing keeps focus, purge dialog shows the count
      step = `${lang} settings`;
      await page.goto(`${BASE}/settings/setad`);
      const kw = page.locator('[id="sd-setad.warn_keywords"]');
      await kw.waitFor();
      await kw.click(); await page.keyboard.press('End'); await kw.pressSequentially('x', { delay: 20 });
      check(r, 'settings focus', await kw.evaluate((el) => document.activeElement === el));
      await kw.press('Backspace');
      await page.getByRole('button', { name: t('setadSettings.purge') }).first().click();
      await page.locator('[data-testid=purge-count]').waitFor();
      check(r, 'purge count shown', true);
      await page.getByRole('dialog').getByRole('button', { name: t('common.cancel') }).click();
      await overflow(`${lang} settings 1280`);
      await shot(`${lang}-settings-setad`);
      // 1024 px, dark
      step = `${lang} 1024 dark`;
      await page.setViewportSize({ width: 1024, height: 800 });
      await call('PATCH', '/api/me', { theme: 'dark' });
      for (const [name, path] of [['inquiry', `/sourcing/inquiries/${inquiryId}`], ['cc', '/command-center'], ['settings', '/settings/setad']]) {
        await page.goto(BASE + path); await page.waitForLoadState('networkidle');
        await overflow(`${lang} ${name} 1024`);
        problems.push(...await selectClip(`${lang} ${name} 1024`));
        await shot(`${lang}-1024-dark-${name}`);
      }
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
