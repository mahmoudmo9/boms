// v0.5.0 end-to-end browser check against the OFFLINE fake Setad host (no real Setad, no network):
// connect -> full fetch with one captcha pause -> filter -> star -> detail -> download -> convert -> decision -> case ->
// cost sheet -> Setad proforma (PDF and Word) -> command center.
// The dev server must run with BOMS_SETAD_FAKE=tests.connectors.setad.fakesite and BOMS_SETAD_HEADLESS=1 so the agent it
// starts inherits them (the fake host routes *.setadiran.ir inside the agent's browser and aborts everything else).
// Usage: NODE_PATH=$(npm root -g) node e2e/setad-flow.cjs <screenshot dir> src/i18n [pdf browser path]
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3]; const BROWSER_PATH = process.argv[4] || '';
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const problems = [];
  const timings = {};
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400 && r.status() !== 424) problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const shot = async (name) => page.screenshot({ path: `${OUT}/${name}.png` });
  const r = { lang: 'fa' };
  const check = (key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${key} ${detail ?? ''}`); };
  const poll = async (fn, ms, every = 500) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(every); } return null; };
  const t = (k) => tr('fa', k);
  const soon = (d) => new Date(Date.now() + d * 86400000).toISOString().slice(0, 10);
  let step = '';

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  try {
    await call('PATCH', '/api/me', { language: 'fa', theme: 'light', calendar: 'jalali', digits: 'fa' });
    await call('PATCH', '/api/settings', { 'company.name_fa': 'بازرگانی نمونه', 'company.national_id': '10320000000',
      'company.economic_code': '411111111111', 'company.signer_name': { fa: 'علی رضایی', en: 'Ali Rezaei' },
      'company.signer_title': { fa: 'مدیرعامل', en: 'CEO' }, ...(BROWSER_PATH ? { 'pdf.browser_path': BROWSER_PATH } : {}) });

    // 1. connect: the agent starts (headless fake browser) and logs in
    step = 'connect';
    await page.goto(`${BASE}/tenders`);
    let t0 = Date.now();
    await page.getByRole('button', { name: t('setad.connect') }).click();
    check('connected', await poll(async () => (await page.locator('[data-testid=agent-state]').innerText()).includes(t('setad.connected')), 90000));
    timings.connect_ms = Date.now() - t0;
    await shot('flow-1-connected');

    // 2. full fetch with one captcha pause
    step = 'full fetch';
    t0 = Date.now();
    await page.getByRole('button', { name: t('setad.fullFetch') }).click();
    const captcha = page.locator('[data-testid=captcha-banner]');
    check('captcha banner shown', await poll(() => captcha.isVisible(), 60000, 250));
    await shot('flow-2-captcha');
    check('captcha banner gone', await poll(async () => !(await captcha.isVisible()), 60000));
    check('fetch finished', await poll(async () => (await page.locator('[data-testid=agent-progress]').count()) === 0
      && (await call('GET', '/api/setad/agent')).body.runs?.setad_purchase?.status === 'done', 180000));
    timings.full_fetch_ms = Date.now() - t0;
    await page.reload();
    const total = await poll(async () => Number((await page.locator('[data-testid=listing-total]').innerText()).replace(/[^\d۰-۹]/g, '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))) || 0, 20000);
    check('listings fetched', total >= 50, String(total));
    await shot('flow-3-listed');

    // 3. filter and star
    step = 'filter';
    await page.locator('[data-testid=listing-search]').fill('پمپ');
    await page.waitForTimeout(800); await page.waitForLoadState('networkidle');
    await page.locator('[data-testid=listing-table] tbody tr button').first().click();
    const panel = page.locator('[data-testid=listing-panel]');
    await panel.waitFor();
    const id = new URL(page.url()).searchParams.get('listing');
    await panel.getByRole('button', { name: `★ ${t('listings.star')}` }).click();
    await panel.getByText(t('listings.status.starred')).first().waitFor();

    // 4. details and attachments (through the agent)
    step = 'detail';
    await panel.getByRole('button', { name: t('listings.fetchDetail') }).click();
    check('detail fetched', await poll(async () => (await call('GET', `/api/listings/${id}`)).body.detail !== null, 90000));
    step = 'download';
    await page.reload(); await panel.waitFor();
    await panel.getByRole('button', { name: t('listings.download') }).click();
    check('files downloaded', await poll(async () => {
      const files = (await call('GET', `/api/listings/${id}`)).body.files;
      return files.length > 0 && files.every((f) => f.state === 'downloaded');
    }, 90000));
    await page.reload(); await panel.waitFor();
    await shot('flow-4-panel');

    // 5. convert to inquiry
    step = 'convert';
    await panel.getByRole('button', { name: t('listings.convert'), exact: true }).click();
    await page.locator('[data-testid=convert-dialog]').waitFor();
    const buyerSel = page.locator('#convert-buyer');
    if (await buyerSel.locator('option[value=""]').count() === 0) await buyerSel.selectOption('new');
    await shot('flow-5-convert');
    await page.locator('[data-testid=convert-submit]').click();
    const dup = page.getByRole('checkbox', { name: t('listings.createAnyway') });
    await Promise.race([page.waitForURL(/\/sourcing\/inquiries\//, { timeout: 20000 }), dup.waitFor({ timeout: 20000 })]);
    if (!/\/sourcing\/inquiries\//.test(page.url())) { await dup.click(); await page.locator('[data-testid=convert-submit]').click(); await page.waitForURL(/\/sourcing\/inquiries\//); }
    const inquiryId = page.url().split('/').pop();
    await page.locator('[data-testid=setad-origin]').waitFor();
    const inq = (await call('GET', `/api/inquiries/${inquiryId}`)).body;
    check('inquiry from setad', inq.source_channel === 'setad' && !!inq.external_no && inq.items.length >= 1 && inq.documents.length >= 1,
      JSON.stringify({ ch: inq.source_channel, items: inq.items.length, docs: inq.documents.length }));
    await shot('flow-6-inquiry');

    // 6. decision (traffic light) and case
    step = 'decision';
    await page.getByRole('radiogroup', { name: t('sourcing.decision.light') }).getByRole('radio', { name: t('sourcing.decision.lights.green') }).click();
    await page.locator('#dc-reason').fill('خرید از تأمین‌کنندهٔ داخلی ممکن است');
    for (const c of ['feasible_sourcing', 'exposure_acceptable', 'requirements_ok']) {
      await page.getByRole('radiogroup', { name: t(`sourcing.decision.checks.${c}`) }).getByRole('radio', { name: t('sourcing.decision.answers.yes') }).click();
    }
    await page.getByRole('button', { name: t('sourcing.decision.save') }).click();
    step = 'case';
    await page.getByRole('button', { name: t('sourcing.convert.button') }).click();
    await page.waitForURL(/\/cases\//);
    const caseId = page.url().split('/cases/')[1].split(/[?#]/)[0];
    await page.locator('[data-testid=setad-origin]').waitFor();
    check('case shows setad origin', true);

    // 7. an offer for each item (API: the RFQ flow is Phase 5), then the cost sheet in the UI
    step = 'offers';
    const items = (await call('GET', `/api/cases/${caseId}`)).body.items;
    const sup = (await call('POST', '/api/parties', { confirm_duplicate: true, name_fa: `تأمین‌کننده ${Date.now() % 100000}`, roles: ['supplier'], country_iso2: 'IR' })).body.party;
    const offer = (await call('POST', '/api/offers', { case_id: caseId, party_id: sup.id, channel: 'phone', currency: 'IRR', valid_until: soon(40),
      no_followup_reason: 'browser check', items: items.map((i) => ({ line_item_id: i.id, unit_price: '15000000' })) })).body;
    for (const [i, it] of items.entries()) await call('POST', `/api/line-items/${it.id}/select`, { offer_item_id: offer.items[i].id });
    step = 'cost sheet';
    const sheet = (await call('POST', '/api/cost-sheets', { case_id: caseId, deal_type: 'domestic', pricing_currency: 'IRR' })).body;
    await call('POST', `/api/cost-sheets/${sheet.id}/lines/not-applicable`);
    await call('PATCH', `/api/cost-sheets/${sheet.id}`, { pricing_method: 'margin', target_percent: '20' });
    await page.goto(`${BASE}/cases/${caseId}?tab=costing`);
    await page.locator('[data-sheet]').waitFor();
    await page.getByRole('button', { name: t('costing.finalize'), exact: true }).click();
    const fin = page.getByRole('dialog');
    await fin.getByRole('button', { name: t('costing.finalize'), exact: true }).click();
    await page.getByText(t('costing.readOnly')).waitFor();
    await shot('flow-7-sheet');

    // 8. Setad proforma
    step = 'quote';
    await page.getByRole('button', { name: t('costing.gate.createQuote') }).click();
    await page.waitForURL(/tab=quotes/);
    await page.locator('[data-quote]').waitFor();
    const quoteId = await page.locator('[data-quote]').getAttribute('data-quote');
    const quote = (await call('GET', `/api/quotes/${quoteId}`)).body;
    check('quote is setad', !!quote.setad && quote.setad.setad_number === inq.external_no, JSON.stringify(quote.setad));
    check('setad terms', quote.terms_text.includes('مدیریت محترم امور تدارکات') && quote.terms_text.includes('سامانه ستاد'));
    const req = inq.required_price_validity;
    const valid = quote.valid_until === req || quote.approval.failures.some((f) => f.code === 'validity_shorter_than_required');
    check('validity follows required', valid, `${quote.valid_until} vs ${req}`);
    if (quote.approval.failures.some((f) => f.code === 'validity_shorter_than_required')) {
      await page.locator('[data-testid=validity-dates]').waitFor();
      await page.getByRole('button', { name: t('costing.gate.override') }).click();
      await page.locator('#qw-reason').fill('اعتبار پیشنهاد تأمین‌کننده کوتاه‌تر است');
      await page.getByRole('dialog').getByRole('button', { name: t('costing.gate.override') }).click();
    }
    await shot('flow-8-quote');
    await page.getByRole('button', { name: t('quotes.approve') }).click();
    await page.getByRole('button', { name: t('quotes.markSent') }).waitFor();
    const html = await (await page.request.get(`${BASE}/api/quotes/${quoteId}/print`)).text();
    check('print: words, ids, signer, number', ['مبلغ به حروف', '10320000000', '411111111111', 'علی رضایی', inq.external_no].every((s) => html.includes(s)));
    for (const fmt of ['PDF', 'Word']) {
      step = `output ${fmt}`;
      const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 90000 }), page.getByRole('button', { name: fmt, exact: true }).click()]);
      const name = dl.suggestedFilename();
      check(`${fmt} file name has the Setad number`, name.includes(inq.external_no) && !name.includes('DRAFT'), name);
      await dl.saveAs(`${OUT}/${name}`);
      r[`${fmt}_file`] = name;
    }

    // 9. command center
    step = 'command center';
    await page.goto(`${BASE}/command-center`);
    const cc = page.locator('[data-testid=cc-setad]');
    await cc.waitFor();
    await cc.scrollIntoViewIfNeeded();
    check('cc setad', (await cc.innerText()).includes(t('cc.setad.title')));
    await shot('flow-9-cc');
    step = 'disconnect';
    await page.goto(`${BASE}/tenders`);
    await page.getByRole('button', { name: t('setad.disconnect') }).click();
    check('disconnected', await poll(async () => !(await call('GET', '/api/setad/agent')).body.connected, 30000));
  } catch (e) {
    problems.push(`exception at ${step}: ${e.message.split('\n')[0]}`);
    await shot('flow-exception');
  }
  console.log(JSON.stringify({ result: r, timings, problems }, null, 1));
  await browser.close();
})();
