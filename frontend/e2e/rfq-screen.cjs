// v0.3.2 browser check (Playwright, run against a dev server on 127.0.0.1:8765 with user admin/admin12345):
// compact RFQ tab (collapse defaults, order, collapsed line, expand/collapse all, keyboard + aria-expanded,
// read-only sent text, "..." menu, no reply-by sentence without a date) and the contact person on offers.
// Creates test data in the dev database. Fa and en at 1280 and 1024 px.
// Usage: NODE_PATH=$(npm root -g) node e2e/rfq-screen.cjs <screenshot dir> src/i18n
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(8000);
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
  const shot = async (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) problems.push(`overflow: ${label}`); };
  const check = (r, key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${r.lang}: ${key} ${detail ?? ''}`); };

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  const results = [];
  try {
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      await call('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);
      const soon = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
      const party = async (name, contactName, country) => {
        const p = (await call('POST', '/api/parties', { confirm_duplicate: true, name_en: `${name} ${tag}`, roles: ['supplier'], country_iso2: country })).body.party;
        const c = (await call('POST', '/api/contacts', { party_id: p.id, name_en: contactName, methods: [{ type: 'email', value: `${contactName.toLowerCase()}${tag}@x.example` }] })).body;
        return { ...p, contact: c };
      };
      const a = await party('Alborz Steel', 'Abbas', 'CN');
      const b = await party('Behran Pipes', 'Bahram', 'AE');
      const c = await party('Caspian Valves', 'Cyrus', 'IR');
      const kase = (await call('POST', '/api/cases', { title: `RFQ screen ${tag}` })).body;
      const items = (await call('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: 'Ball valve DN50' }, { name: 'Gate valve DN80' }, { name: 'Gasket' }] })).body.items;
      const rfq = async (body) => (await call('POST', '/api/rfqs', { case_id: kase.id, items: items.map((i) => ({ line_item_id: i.id })), ...body })).body;
      const send = (rid, body = { followup: { action: 'chase', due_on: soon(3) } }) => call('POST', `/api/rfqs/recipients/${rid}/mark-sent`, body);

      // four RFQs in different states (oldest first): answered, cancelled, sent (no respond_by), draft (via UI)
      const answered = await rfq({ respond_by: soon(5), recipients: [{ party_id: a.id }, { party_id: b.id }] });
      for (const x of answered.recipients) await send(x.id);
      const offer = (await call('POST', '/api/offers', { case_id: kase.id, party_id: a.id, contact_id: a.contact.id, channel: 'email', currency: 'USD',
        valid_until: soon(30), no_followup_reason: 'x', rfq_recipient_id: answered.recipients[0].id,
        items: items.map((i) => ({ line_item_id: i.id, unit_price: '10' })) })).body;
      await call('POST', `/api/rfqs/recipients/${answered.recipients[1].id}/decline`, {});
      const cancelled = await rfq({ respond_by: soon(5), recipients: [{ party_id: b.id }] });
      await call('POST', `/api/rfqs/${cancelled.id}/cancel`, { reason: 'test' });
      const sent = await rfq({ recipients: [{ party_id: c.id, language: lang, channel: 'email' }] });
      await send(sent.recipients[0].id, { no_followup_reason: 'test' });

      await page.goto(`${BASE}/cases/${kase.id}?tab=rfqs`);
      await page.getByRole('button', { name: t('sourcing.rfq.new'), exact: true }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByText('Ball valve DN50', { exact: true }).click();  // items with offers are not pre-selected
      await dialog.getByPlaceholder(t('sourcing.rfq.searchSuppliers')).fill(tag);
      await dialog.locator('li', { hasText: `Caspian Valves ${tag}` }).last().getByRole('button', { name: t('common.add') }).click();
      await dialog.getByRole('button', { name: t('sourcing.rfq.create') }).click();
      await page.waitForSelector('[role=dialog]', { state: 'detached' });
      await page.waitForTimeout(500);
      const all = (await call('GET', `/api/rfqs?case_id=${kase.id}`)).body;
      const draft = all.find((x) => x.status === 'draft');
      check(r, 'uniqueDefaultTitle', draft && draft.title === 'RFQ 4 - Ball valve DN50', draft && draft.title);
      const titles = all.map((x) => x.title);
      check(r, 'titlesUnique', new Set(titles).size === titles.length, titles.join(' | '));

      // defaults and order
      const state = await page.$$eval('section[data-rfq]', (els) => els.map((e) => ({ id: e.dataset.rfq, open: e.dataset.open === 'true' })));
      check(r, 'order', JSON.stringify(state.map((s) => s.id)) === JSON.stringify([draft.id, sent.id, cancelled.id, answered.id]), JSON.stringify(state));
      check(r, 'defaults', state.map((s) => s.open).join() === 'true,false,false,false', JSON.stringify(state));
      // collapsed line contents
      const head = await page.locator(`section[data-rfq="${answered.id}"] button[aria-expanded]`).first().innerText();
      check(r, 'collapsedLine', head.includes(answered.title) && head.includes(tr(lang, 'sourcing.status.rfq.answered'))
        && head.includes('Abbas') && head.includes(`✓ ${tr(lang, 'sourcing.status.recipient.replied')}`) && head.includes('Bahram'), head.replace(/\n/g, ' / '));
      const lines = await page.$$eval('section[data-rfq][data-open="false"] > div:first-child', (els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
      r.collapsedHeights = lines.join(',');
      await overflow(`${lang} rfq tab 1280`); await shot(`${lang}-rfqs-1280`);
      await page.setViewportSize({ width: 1024, height: 900 }); await page.waitForTimeout(200);
      await overflow(`${lang} rfq tab 1024`); await shot(`${lang}-rfqs-1024`);
      await page.setViewportSize({ width: 1280, height: 900 });

      // expand / collapse all
      await page.getByRole('button', { name: t('sourcing.rfq.expandAll'), exact: true }).click();
      check(r, 'expandAll', (await page.$$eval('section[data-rfq]', (els) => els.every((e) => e.dataset.open === 'true'))));
      await page.getByRole('button', { name: t('sourcing.rfq.collapseAll'), exact: true }).click();
      check(r, 'collapseAll', (await page.$$eval('section[data-rfq]', (els) => els.every((e) => e.dataset.open === 'false'))));

      // keyboard toggle + aria-expanded
      const toggle = page.locator(`section[data-rfq="${sent.id}"] button[aria-expanded]`).first();
      await toggle.focus(); await page.keyboard.press('Enter');
      const afterEnter = await toggle.getAttribute('aria-expanded');
      await page.keyboard.press('Space');
      const afterSpace = await toggle.getAttribute('aria-expanded');
      check(r, 'keyboardToggle', afterEnter === 'true' && afterSpace === 'false', `${afterEnter}/${afterSpace}`);
      await page.keyboard.press('Enter');

      // sent recipient: read-only text, no reply-by sentence (no respond_by)
      const sentCard = page.locator(`section[data-rfq="${sent.id}"]`);
      await sentCard.locator('li[data-recipient] button[aria-expanded]').first().click();
      const sentText = await sentCard.getByTestId('sent-text').innerText();
      check(r, 'sentReadOnly', (await sentCard.locator('textarea').count()) === 0
        && (await sentCard.getByRole('button', { name: t('sourcing.rfq.rerender'), exact: true }).count()) === 0);
      check(r, 'noReplyBy', !/reply by|تا \s*\./i.test(sentText) && !sentText.includes(' .') && !sentText.includes('تا  '), sentText.slice(-200));
      check(r, 'textDir', (await sentCard.getByTestId('sent-text').getAttribute('dir')) === (lang === 'fa' ? 'rtl' : 'ltr'));
      await shot(`${lang}-sent-recipient`);

      // draft recipient: editable
      const draftCard = page.locator(`section[data-rfq="${draft.id}"]`);
      if ((await draftCard.getAttribute('data-open')) !== 'true') await draftCard.locator('button[aria-expanded]').first().click();
      const area = draftCard.locator('textarea').first();
      check(r, 'draftEditable', (await area.count()) === 1 && !(await area.getAttribute('readonly')));

      // "..." menu
      await page.locator(`section[data-rfq="${answered.id}"] button[aria-haspopup=menu]`).click();
      const menu = page.getByRole('menu');
      check(r, 'menu', (await menu.getByRole('menuitem').count()) >= 2 && (await menu.getByText(t('sourcing.rfq.cancel'), { exact: true }).count()) === 1);
      await page.keyboard.press('Escape');

      // record offer from the waiting recipient: supplier and its RFQ contact pre-selected
      await sentCard.locator('li[data-recipient]').getByRole('button', { name: t('sourcing.rfq.recordOffer'), exact: true }).click();
      await page.waitForSelector('#of-contact');
      await page.waitForTimeout(500);
      check(r, 'contactPreselected', (await page.locator('#of-contact').inputValue()) === c.contact.id);
      await shot(`${lang}-offer-form-contact`);
      await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();

      // contact on offer card, comparison matrix, product page
      await page.goto(`${BASE}/cases/${kase.id}?tab=offers`); await page.waitForSelector(`text=Alborz Steel ${tag}`);
      check(r, 'contactOnCard', (await page.locator('section, div').filter({ hasText: `Alborz Steel ${tag}` }).getByText('Abbas', { exact: true }).count()) > 0);
      await overflow(`${lang} offers`);
      await page.goto(`${BASE}/cases/${kase.id}?tab=comparison`); await page.waitForSelector(`text=Alborz Steel ${tag}`);
      check(r, 'contactInMatrix', (await page.locator('td').getByText('Abbas', { exact: true }).count()) > 0);
      await overflow(`${lang} comparison`); await shot(`${lang}-comparison-contact`);
      const made = (await call('POST', `/api/line-items/${items[0].id}/create-product`, { confirm_duplicate: true })).body;
      await page.goto(`${BASE}/sourcing/catalog/${made.product_id}`); await page.waitForSelector(`text=Alborz Steel ${tag}`);
      check(r, 'contactInPriceHistory', (await page.locator('td').getByText('Abbas', { exact: true }).count()) > 0);
      await shot(`${lang}-product-contact`);

      await page.goto(`${BASE}/command-center`); await page.waitForSelector('h1');
      check(r, 'ccNoResponseCard', (await page.getByText(t('cc.sourcing.noResponseResend')).count()) === 1);
      await overflow(`${lang} command center`);
      results.push(r);
    }
  } catch (e) { problems.push(`CRASH: ${e.message.split('\n')[0]}`); await shot('crash'); }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
