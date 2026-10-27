// v0.4.0 browser check (Playwright, run against a dev server on 127.0.0.1:8765 with user admin/admin12345):
// a case with two selected offers in two currencies -> cost sheet from the import template (FX, duty, margin 20 %,
// gate) -> quote (approve, PDF and Word download, mark sent) -> partial acceptance with a rejection reason ->
// product page, party page and command center. Also: focus while typing, select clipping, page overflow at 1024 px,
// light and dark screenshots, the settings pages (costing, letterhead) and quote terms templates.
// Creates test data in the dev database and sets pdf.browser_path to the given browser (third argument).
// Usage: NODE_PATH=$(npm root -g) node e2e/quote-flow.cjs <screenshot dir> src/i18n <headless chrome path>
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3]; const BROWSER_PATH = process.argv[4] || null;
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`);
  });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  // the page scrolls inside <main>: grow the viewport to the content height for a complete screenshot
  const shot = async (name) => {
    const size = page.viewportSize();
    const height = await page.evaluate(() => Math.max(...[...document.querySelectorAll('main, main *')].filter((e) => e.scrollHeight > e.clientHeight + 4 && getComputedStyle(e).overflowY !== 'visible').map((e) => e.scrollHeight), document.documentElement.scrollHeight));
    await page.setViewportSize({ width: size.width, height: Math.min(height + 120, 6000) });
    await page.screenshot({ path: `${OUT}/${name}.png` });
    await page.setViewportSize(size);
  };
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) problems.push(`overflow: ${label}`); };
  const settle = () => page.waitForLoadState('networkidle');

  const typeCheck = async (r, label, selector, text) => {
    const loc = page.locator(selector).first();
    await loc.click();
    await loc.fill('');
    await loc.pressSequentially(text, { delay: 20 });
    const res = await loc.evaluate((el, text) => ({ focused: document.activeElement === el, value: el.value, ok: document.activeElement === el && el.value === text }), text);
    r[`focus ${label}`] = res.ok ? 'ok' : `FAIL focused=${res.focused} value=${JSON.stringify(res.value)}`;
    if (!res.ok) problems.push(`${r.lang}: focus ${label}`);
  };
  const selectClip = (label) => page.evaluate((label) => {
    const out = [];
    const canvas = document.createElement('canvas').getContext('2d');
    for (const s of document.querySelectorAll('select')) {
      if (!s.offsetParent) continue;
      const cs = getComputedStyle(s);
      canvas.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const avail = s.clientWidth - parseFloat(cs.paddingInlineStart) - parseFloat(cs.paddingInlineEnd);
      const widest = Math.max(...[...s.options].map((o) => canvas.measureText(o.text).width));
      if (widest > avail + 0.5) out.push(`${label}: ${s.getAttribute('aria-label') || s.id} needs ${widest.toFixed(1)}px, has ${avail.toFixed(1)}px`);
    }
    return out;
  }, label);
  const checkSelects = async (r, label) => { const c = await selectClip(`${r.lang} ${label}`); if (c.length) { r[`selects ${label}`] = c; problems.push(...c); } };
  const check = (r, key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${r.lang}: ${key} ${detail ?? ''}`); };
  const download = async (button) => {
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 90000 }), button.click()]);
    const path = `${OUT}/${dl.suggestedFilename()}`;
    await dl.saveAs(path);
    return { name: dl.suggestedFilename(), head: fs.readFileSync(path).subarray(0, 4).toString('latin1'), size: fs.statSync(path).size };
  };

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  if (BROWSER_PATH) await call('PATCH', '/api/settings', { 'pdf.browser_path': BROWSER_PATH });
  await call('PATCH', '/api/settings', { 'company.name_fa': 'بازرگانی نمونه', 'company.name_en': 'Sample Trading Co.', 'company.phone': '+98 21 1234 5678' });
  const results = [];
  try {
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      await call('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);
      const soon = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);

      // ---- data: buyer, products, case with two items, two offers (USD, EUR) selected ----
      const buyer = (await call('POST', '/api/parties', { confirm_duplicate: true, name_en: `Buyer ${tag}`, name_fa: `خریدار ${tag}`, roles: ['buyer'], country_iso2: lang === 'fa' ? 'IR' : 'AE' })).body.party;
      await call('POST', '/api/contacts', { party_id: buyer.id, name_en: 'Reza', methods: [{ type: 'email', value: `reza${tag}@buyer.example` }] });
      const product = async (name) => (await call('POST', '/api/products', { name_en: `${name} ${tag}`, confirm_duplicate: true })).body.product;
      const p1 = await product('Ball valve DN50'); const p2 = await product('Centrifugal pump');
      const kase = (await call('POST', '/api/cases', { title: `Quote flow ${tag}`, party_id: buyer.id })).body;
      const items = (await call('POST', '/api/line-items/bulk', { case_id: kase.id, items: [
        { name: `Ball valve DN50 ${tag}`, quantity: '10', unit_code: 'pc', product_id: p1.id },
        { name: `Centrifugal pump ${tag}`, quantity: '2', unit_code: 'pc', product_id: p2.id }] })).body.items;
      for (const [item, currency, price, country] of [[items[0], 'USD', '12.5', 'CN'], [items[1], 'EUR', '300', 'DE']]) {
        const sup = (await call('POST', '/api/parties', { confirm_duplicate: true, name_en: `Supplier ${currency} ${tag}`, roles: ['supplier'], country_iso2: country })).body.party;
        const offer = (await call('POST', '/api/offers', { case_id: kase.id, party_id: sup.id, channel: 'email', currency, valid_until: soon(30),
          no_followup_reason: 'comparing offers', items: [{ line_item_id: item.id, unit_price: price }] })).body;
        const sel = await call('POST', `/api/line-items/${item.id}/select`, { offer_item_id: offer.items[0].id });
        if (sel.status !== 200) problems.push(`${lang}: select offer ${sel.status}`);
      }

      // ---- cost sheet from the import template ----
      await page.goto(`${BASE}/cases/${kase.id}?tab=costing`);
      await page.getByText(t('costing.empty')).waitFor();
      await page.getByRole('button', { name: t('costing.newSheet') }).click();
      const dialog = page.getByRole('dialog');
      await page.waitForFunction(() => document.querySelector('#ns-cur')?.value === 'IRR', null, { timeout: 5000 }).catch(() => {});
      check(r, 'newSheet defaults', (await dialog.locator('#ns-deal').inputValue()) === 'import' && (await dialog.locator('#ns-cur').inputValue()) === 'IRR');
      await checkSelects(r, 'new sheet dialog');
      await dialog.getByRole('button', { name: t('costing.create') }).click();
      await page.locator('[data-sheet]').waitFor();
      await page.getByRole('alert').filter({ hasText: 'USD' }).waitFor();
      check(r, 'purchase prefilled from offers', (await page.locator('[data-grid="0-value"]').inputValue()) === '12.5000' && (await page.locator('[data-grid="1-value"]').inputValue()) === '300.0000');

      // FX: USD then EUR (the form follows the missing pair)
      check(r, 'fx form follows missing pair', (await page.locator('#fx-from').inputValue()) === 'USD');
      await page.fill('#fx-rate', '600000');
      await typeCheck(r, 'fx rate kind', '#fx-kind', lang === 'fa' ? 'بازار آزاد' : 'free market');
      await typeCheck(r, 'fx source', '#fx-src', lang === 'fa' ? 'صرافی' : 'exchange shop');
      await page.getByRole('button', { name: t('costing.fx.save') }).click();
      await page.getByRole('alert').filter({ hasText: 'EUR' }).waitFor();
      await page.waitForFunction(() => document.querySelector('#fx-from')?.value === 'EUR');
      await page.fill('#fx-rate', '650000');
      await page.getByRole('button', { name: t('costing.fx.save') }).click();
      await page.getByRole('alert').filter({ hasText: 'EUR' }).waitFor({ state: 'detached' });
      await settle();

      // lines grid: fill every empty value with the keyboard (Enter moves down in the same column)
      const rows = await page.locator('[data-grid$="-value"]').count();
      let moves = 0; let movesOk = 0;
      for (let i = 0; i < rows; i++) {
        const input = page.locator(`[data-grid="${i}-value"]`);
        if (await input.inputValue()) continue;
        const isPercent = (await input.getAttribute('aria-label')) === t('costing.lines.percent');
        await input.click();
        await input.pressSequentially(isPercent ? '4' : '10000000', { delay: 15 });
        await input.press('Enter');
        if (i < rows - 1) { moves++; if (await page.evaluate((n) => document.activeElement?.getAttribute('data-grid') === `${n}-value`, i + 1)) movesOk++; }
        await settle();
      }
      check(r, 'grid Enter moves down', moves > 0 && moves === movesOk, `${movesOk}/${moves}`);
      await page.locator('[data-grid="3-value"]').click();
      await page.keyboard.press('ArrowUp');
      check(r, 'grid ArrowUp', await page.evaluate(() => document.activeElement?.getAttribute('data-grid') === '2-value'));
      await page.keyboard.press('Escape');
      const duty = page.locator('tr', { has: page.getByText(t('costing.kinds.customs_duty'), { exact: true }) });
      const dutyOk = await page.waitForFunction((el) => el.innerText.trim() !== '—', await duty.locator('td').nth(6).elementHandle(), { timeout: 8000 }).then(() => true, () => false);
      check(r, 'customs duty line computed', dutyOk);
      await checkSelects(r, 'lines grid');

      // pricing: margin 20 %
      await page.selectOption('#pr-method', 'margin');
      await settle();
      await page.locator('#pr-target').fill('20');
      await page.locator('#pr-target').press('Tab');
      await settle();
      const want = lang === 'fa' ? '۲۰ %' : '20 %';
      const marginOk = await page.waitForFunction((w) => document.querySelector('[data-testid="totals"]')?.innerText.includes(w), want, { timeout: 8000 }).then(() => true, () => false);
      check(r, 'total margin 20 %', marginOk, (await page.locator('[data-testid="totals"]').innerText()).replace(/\s+/g, ' ').slice(0, 200));
      await page.locator('[data-testid="item-margin"]').first().waitFor();
      await page.getByRole('button', { name: items[1].name }).click();
      check(r, 'per-item breakdown', await page.locator('[data-testid="breakdown"]').isVisible());
      await typeCheck(r, 'sheet notes', '#sh-notes', lang === 'fa' ? 'یادداشت برگه' : 'sheet note');
      await page.locator('#sh-notes').press('Tab');
      await settle();
      await shot(`${lang}-1280-costing-draft`);
      await overflow(`${lang} costing 1280`);
      await checkSelects(r, 'costing');

      // finalize, gate, create quote
      await page.getByRole('button', { name: t('costing.finalize'), exact: true }).click();
      await page.getByText(t('costing.readOnly')).waitFor();
      const gate = page.locator('[data-testid="gate-checklist"]');
      const failing = await gate.locator('li[data-ok="false"]').allInnerTexts();
      check(r, 'gate passes', failing.length === 0, failing.join(' | '));
      check(r, 'header computed exposure', await page.locator('[data-testid="computed-exposure"]').isVisible());
      await shot(`${lang}-1280-costing-final`);
      await page.getByRole('button', { name: t('costing.gate.createQuote') }).click();
      await page.waitForURL(/tab=quotes/);
      await page.locator('[data-quote]').waitFor();
      const number = (await page.locator('[data-quote] .font-mono').first().innerText()).trim();
      check(r, 'quote number', /^PI-\d{4}-\d{4}$/.test(number), number);
      r.number = number;
      check(r, 'quote language follows buyer country', (await page.locator('#q-lang').inputValue()) === lang);
      await typeCheck(r, 'quote payment terms', '#q-pay', lang === 'fa' ? '۳۰٪ پیش‌پرداخت' : '30% advance, rest before shipment');
      await page.locator('#q-pay').press('Tab');
      await settle();
      await checkSelects(r, 'quote draft');
      await shot(`${lang}-1280-quote-draft`);

      // approve, PDF and Word
      await page.getByRole('button', { name: t('quotes.approve'), exact: true }).click();
      await page.locator('[data-quote]').getByText(t('sourcing.status.quote.approved')).first().waitFor();
      const pdf = await download(page.getByRole('button', { name: 'PDF' }));
      check(r, 'pdf download', pdf.head === '%PDF' && pdf.size > 5000, JSON.stringify(pdf));
      await settle();
      const docx = await download(page.getByRole('button', { name: 'Word' }));
      check(r, 'word download', docx.head.startsWith('PK') && docx.size > 5000, JSON.stringify(docx));
      r.files = [pdf.name, docx.name];
      await page.goto(`${BASE}/cases/${kase.id}?tab=quotes`);
      await page.locator('[data-quote]').waitFor();
      check(r, 'outputs listed', (await page.getByRole('link', { name: new RegExp(esc(number)) }).count()) >= 2);

      // mark sent
      await page.getByRole('button', { name: t('quotes.markSent') }).click();
      const sent = page.getByRole('dialog');
      check(r, 'mark-sent follow-up preview', (await sent.locator('[data-testid="qs-preview"]').innerText()).length > 5);
      await checkSelects(r, 'mark-sent dialog');
      await sent.getByRole('button', { name: t('quotes.markSent') }).click();
      await sent.waitFor({ state: 'detached' });
      await page.locator('[data-quote]').getByText(t('sourcing.status.quote.sent')).first().waitFor();

      // partial acceptance: first row accepted, second rejected with a reason
      await page.getByRole('button', { name: t('quotes.recordOutcome') }).click();
      const oc = page.getByRole('dialog');
      const outcomeSelects = oc.getByLabel(t('quotes.outcome'), { exact: true });
      await outcomeSelects.nth(0).selectOption('accepted');
      await outcomeSelects.nth(1).selectOption('rejected');
      check(r, 'rejection needs a reason', await oc.getByRole('button', { name: t('common.save') }).isDisabled() && await oc.getByText(t('quotes.reasonRequiredHint')).isVisible());
      await checkSelects(r, 'outcomes dialog');
      await oc.getByLabel(t('quotes.reason'), { exact: true }).nth(1).selectOption('price');
      await typeCheck(r, 'competitor price', `[aria-label="${t('quotes.competitorPrice')}"] >> nth=1`, '95000000');
      await oc.getByRole('button', { name: t('common.save') }).click();
      await oc.waitFor({ state: 'detached' });
      await page.locator('[data-quote]').getByText(t('sourcing.status.quote.partially_accepted')).first().waitFor();
      check(r, 'header shows latest quote', (await page.getByText(t('quotes.latest')).count()) > 0);
      await shot(`${lang}-1280-quote-outcome`);
      await overflow(`${lang} quote 1280`);

      // product page, party page, command center
      await page.goto(`${BASE}/sourcing/catalog/${p2.id}`);
      await page.locator('[data-testid="product-quotes"]').waitFor();
      const pq = await page.locator('[data-testid="product-quotes"]').innerText();
      check(r, 'product page: quotes we sent', pq.includes(number) && pq.includes(t('quotes.outcomes.rejected')), pq.slice(0, 200));
      await shot(`${lang}-1280-product`);
      await page.goto(`${BASE}/parties/${buyer.id}?tab=quotes`);
      await page.locator('[data-testid="party-quotes"]').waitFor();
      check(r, 'party page: quotes', (await page.locator('[data-testid="party-quotes"]').innerText()).includes(number));
      await page.goto(`${BASE}/command-center`);
      await page.locator('[data-testid="won-lost"]').waitFor();
      check(r, 'command center: sales section', await page.getByText(t('cc.sales.awaitingApproval')).isVisible() && await page.getByText(t('cc.sales.staleFx')).isVisible());
      await shot(`${lang}-1280-command-center`);
      await overflow(`${lang} command center 1280`);

      // settings pages and quote terms templates
      await page.goto(`${BASE}/settings/costing`);
      await page.getByText(t('costing.templates.title')).first().waitFor();
      await page.getByRole('button', { name: t('costing.params.new') }).click();
      await checkSelects(r, 'tax parameter dialog');
      await typeCheck(r, 'tax parameter name', '#tp-name', lang === 'fa' ? 'حقوق ورودی' : 'Import duty');
      await page.keyboard.press('Escape');
      await checkSelects(r, 'costing settings');
      await shot(`${lang}-1280-settings-costing`);
      await page.goto(`${BASE}/settings/letterhead`);
      await page.locator('#lh-company\\.name_en').waitFor();
      await typeCheck(r, 'letterhead address', `[id="lh-company.address-${lang}"]`, lang === 'fa' ? 'تهران، خیابان آزادی' : 'Azadi St., Tehran');
      await shot(`${lang}-1280-settings-letterhead`);
      await page.goto(`${BASE}/sourcing/templates?kind=quote_terms`);
      await page.getByText(lang === 'fa' ? 'فارسی' : 'English').first().waitFor({ state: 'attached' }).catch(() => {});
      check(r, 'quote terms templates listed', (await page.locator('li').filter({ hasText: 'letter' }).count()) + (await page.getByText(t('sourcing.channels.letter')).count()) >= 2);

      // 1024 px and dark
      await page.setViewportSize({ width: 1024, height: 800 });
      for (const [tab, name] of [['costing', 'costing'], ['quotes', 'quote']]) {
        await page.goto(`${BASE}/cases/${kase.id}?tab=${tab}`);
        await page.locator(tab === 'costing' ? '[data-sheet]' : '[data-quote]').waitFor();
        await settle();
        await overflow(`${lang} ${name} 1024`);
        await checkSelects(r, `${name} 1024`);
        await shot(`${lang}-1024-${name}`);
      }
      await page.goto(`${BASE}/settings/costing`); await settle(); await overflow(`${lang} settings costing 1024`); await checkSelects(r, 'settings costing 1024');
      await call('PATCH', '/api/me', { theme: 'dark' });
      await page.setViewportSize({ width: 1280, height: 900 });
      for (const tab of ['costing', 'quotes']) {
        await page.goto(`${BASE}/cases/${kase.id}?tab=${tab}`);
        await page.locator(tab === 'costing' ? '[data-sheet]' : '[data-quote]').waitFor();
        await settle();
        await shot(`${lang}-1280-dark-${tab}`);
      }
      await call('PATCH', '/api/me', { theme: 'light' });
      results.push(r);
    }
  } catch (e) {
    problems.push(`exception: ${e.message.split('\n')[0]}`);
    await shot('exception');
  }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
