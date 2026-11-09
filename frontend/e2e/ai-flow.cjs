// v0.9.0 M5 browser check (Playwright) against the dev server on 127.0.0.1:8765 (admin/admin12345) with the fake AI
// provider of e2e/fake_ai_provider.py on 127.0.0.1:8799 (an «OpenAI-compatible» provider). No network host is contacted.
// For fa and en: drop a PDF on an inquiry -> review -> accept -> items with canonical descriptions; paste a supplier e-mail
// into an offer -> review -> accept; create a shipment with SHA -> BUZ and a 45G1 container; see codes on the case and
// open «تأیید سند» with a QR payload; AI settings with the cap at 80 %; «کارهای من» and the finance tab unchanged.
// Then the new pages in light/dark at 1280/1024 px (no page overflow, no clipped select).
// Usage: NODE_PATH=$(npm root -g) node e2e/ai-flow.cjs <out dir> src/i18n <rfq.pdf>. Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3]; const PDF = process.argv[4];
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => {
    if (!r.url().includes('/api/') || r.status() < 400) return;
    if (r.status() === 404 && r.url().includes('/preview')) return;
    problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`);
  });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    const ct = r.headers.get('content-type') || '';
    return { status: r.status, body: r.status === 204 ? null : ct.includes('json') ? await r.json() : await r.text() };
  }, [method, path, body]);
  const ok = async (method, path, body) => {
    const r = await call(method, path, body);
    if (r.status >= 300) throw new Error(`${method} ${path} -> ${r.status} ${JSON.stringify(r.body).slice(0, 300)}`);
    return r.body;
  };
  const uploadPdf = (name) => page.evaluate(async ([name, b64]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const unique = new TextEncoder().encode(`\n% ${name}\n`);      // a PDF comment: the same file stays new per run
    const form = new FormData(); form.append('file', new Blob([bytes, unique], { type: 'application/pdf' }), name);
    const r = await fetch('/api/documents', { method: 'POST', headers: { 'X-CSRF-Token': tok }, body: form });
    return r.json();
  }, [name, fs.readFileSync(PDF).toString('base64')]);
  const shot = async (name, full = true) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  const poll = async (fn, ms = 15000, every = 400) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(every); } return null; };
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) problems.push(`overflow: ${label}`); };
  const selectClip = async (label) => problems.push(...await page.evaluate((label) => {
    const out = []; const canvas = document.createElement('canvas').getContext('2d');
    for (const s of document.querySelectorAll('select')) {
      if (!s.offsetParent) continue;
      const cs = getComputedStyle(s); canvas.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const avail = s.clientWidth - parseFloat(cs.paddingInlineStart) - parseFloat(cs.paddingInlineEnd);
      const widest = Math.max(...[...s.options].map((o) => canvas.measureText(o.text).width));
      if (widest > avail + 0.5) out.push(`${label}: select ${s.getAttribute('aria-label') || s.id} needs ${widest.toFixed(1)}px, has ${avail.toFixed(1)}px`);
    }
    return out;
  }, label));
  const soon = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
  const results = [];
  let step = '';

  async function deal(tag) {     // a confirmed PO for the shipment (Phase 8 steps through the API)
    const buyer = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Buyer ${tag}`, roles: ['buyer'], country_iso2: 'AE' })).party;
    const sup = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Supplier ${tag}`, roles: ['supplier'], country_iso2: 'CN' })).party;
    const kase = await ok('POST', '/api/cases', { title: `AI deal ${tag}`, party_id: buyer.id });
    const items = (await ok('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: `Pump ${tag}`, quantity: '2', unit_code: 'pc' },
      { name: `Valve ${tag}`, quantity: '4', unit_code: 'pc' }] })).items;
    const offer = await ok('POST', '/api/offers', { case_id: kase.id, party_id: sup.id, channel: 'email', currency: 'USD', valid_until: soon(60),
      no_followup_reason: 'browser check', items: items.map((i) => ({ line_item_id: i.id, unit_price: '100' })) });
    for (const [i, it] of items.entries()) await ok('POST', `/api/line-items/${it.id}/select`, { offer_item_id: offer.items[i].id });
    const sheet = await ok('POST', '/api/cost-sheets', { case_id: kase.id, deal_type: 'import', pricing_currency: 'USD' });
    for (const line of sheet.lines) {
      if (line.kind === 'purchase') continue;
      await ok('PATCH', `/api/cost-sheets/lines/${line.id}`, line.basis.startsWith('percent') ? { percent: '0', tax_parameter_id: null } : { amount: '0', currency: 'USD' });
    }
    await ok('PATCH', `/api/cost-sheets/${sheet.id}`, { pricing_method: 'margin', target_percent: '20', annual_cost_of_money_percent: '0' });
    await ok('POST', `/api/cost-sheets/${sheet.id}/finalize`, { confirm: true });
    const quote = await ok('POST', '/api/quotes', { case_id: kase.id, language: 'en' });
    await ok('POST', `/api/quotes/${quote.id}/approve`);
    const sent = await ok('POST', `/api/quotes/${quote.id}/mark-sent`, { no_followup_reason: 'browser check' });
    await ok('PUT', `/api/quotes/${quote.id}/outcomes`, { items: sent.items.map((i) => ({ quote_item_id: i.id, outcome: 'accepted' })) });
    let so = await ok('POST', '/api/sales-orders/from-quote', { quote_id: quote.id });
    so = await ok('POST', `/api/sales-orders/${so.id}/confirm`, { no_document_reason: 'browser check' });
    const po = (await ok('POST', `/api/sales-orders/${so.id}/purchase-orders`)).created[0];
    await ok('POST', `/api/purchase-orders/${po.id}/approve`, { confirm_above_cost: true, reason: 'browser check' });
    await ok('POST', `/api/purchase-orders/${po.id}/mark-sent`, {});
    await ok('POST', `/api/purchase-orders/${po.id}/confirm`, { confirmed_ready_on: soon(5) });
    return { kase, sup, quote, so, po };
  }

  async function review(t) {          // the review screen: wait for the draft, accept the confident fields, «ثبت»
    await page.locator('[data-testid=draft-review][data-status=ready]').waitFor({ timeout: 30000 });
    await page.locator('[data-testid=accept-confident]').click();
    await poll(async () => (await page.locator('[data-testid=draft-field][data-decision=open]').count()) < (await page.locator('[data-testid=draft-field]').count()));
    for (let n = await page.locator('[data-testid=draft-field][data-decision=open]').count(); n > 0;) {
      await page.locator('[data-testid=draft-field][data-decision=open] [data-testid=field-accept]').first().click();
      const before = n;
      await poll(async () => (n = await page.locator('[data-testid=draft-field][data-decision=open]').count()) < before, 5000, 150);
      if (n >= before) break;
    }
    await page.locator('[data-testid=draft-commit]').click();
    await page.locator('[data-testid=draft-review]').waitFor({ state: 'detached' }).catch(() => {});
  }

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  try {
    // the fake provider: OpenAI-compatible on 127.0.0.1 (a local provider: nothing is masked, no cost)
    const providers = await ok('GET', '/api/ai/providers');
    const fake = providers.find((p) => p.kind === 'openai_compatible');
    await ok('PATCH', `/api/ai/providers/${fake.id}`, { base_url: 'http://127.0.0.1:8799', models: ['fake-vl'] });
    await ok('PATCH', `/api/ai/providers/${fake.id}`, { enabled: true });
    for (const task of ['extraction', 'party_parse', 'drafting']) await ok('PATCH', `/api/ai/routes/${task}`, { primary_provider_id: fake.id, primary_model: 'fake-vl', fallback_provider_id: null, fallback_model: null });
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      const check = (key, cond, detail) => { r[key] = cond ? true : `FAIL ${detail ?? ''}`; if (!cond) problems.push(`${lang}: ${key} ${detail ?? ''}`); };
      results.push(r);
      await page.setViewportSize({ width: 1280, height: 900 });
      await ok('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);

      // ---- 1. a PDF on an inquiry -> review -> accept -> items with canonical descriptions ----
      step = `${lang} inquiry extraction`;
      const doc = await uploadPdf(`rfq-${tag}.pdf`);
      const inq = await ok('POST', '/api/inquiries', { source_channel: 'email', subject: `RFQ ${tag}`, document_ids: [doc.id] });
      await page.goto(`${BASE}/sourcing/inquiries/${inq.id}`);
      await page.locator('[data-testid=ai-extract]').first().click();
      await page.locator('label', { hasText: `rfq-${tag}` }).first().click();
      await page.locator('[data-testid=ai-extract-start]').click();
      await review(t);
      const canon = await poll(async () => { const c = await page.locator('[data-testid=item-canonical]').allTextContents(); return c.length >= 2 && c; });
      check('inquiry items with canonical descriptions', canon && canon.some((x) => x.includes(lang === 'fa' ? 'پمپ، گریز از مرکز' : 'PUMP, CENTRIFUGAL')), JSON.stringify(canon));
      await shot(`${lang}-inquiry-extracted`);

      // ---- 2. a supplier e-mail pasted into an offer -> review -> accept ----
      step = `${lang} offer`;
      const d = await deal(tag);
      await page.goto(`${BASE}/cases/${d.kase.id}?tab=offers`);
      await page.locator('[data-testid=ai-extract-offer]').click();
      await page.locator('[data-testid=ai-extract-supplier] input').fill(`Supplier ${tag}`);
      await page.locator('[role=option]', { hasText: `Supplier ${tag}` }).first().waitFor();
      await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
      await page.locator('[data-testid=ai-extract-text]').fill('Dear Sir, our offer: item 1 at USD 1200 x 2 = 2400, item 2 at USD 300 x 4 = 1300. FOB Shanghai.');
      await page.locator('[data-testid=ai-extract-start]').click();
      await page.locator('[data-testid=draft-review][data-status=ready]').waitFor({ timeout: 30000 });
      check('offer total difference flagged', (await page.locator('[data-testid=draft-checks]').count()) === 1);
      await shot(`${lang}-offer-review`);
      await review(t);
      const offers = await poll(async () => { const o = await ok('GET', `/api/offers?case_id=${d.kase.id}`); return o.length >= 2 && o; });
      check('offer recorded from the draft', offers && offers.some((o) => o.incoterm === 'FOB'));

      // ---- 3. shipment SHA -> BUZ with a 45G1 container ----
      step = `${lang} shipment`;
      await page.goto(`${BASE}/cases/${d.kase.id}?tab=logistics`);
      await page.getByRole('button', { name: t('execution.shipments.add') }).first().click();
      const dlg = page.locator('[data-testid=shipment-dialog]');
      await dlg.locator('[data-testid=sh-origin-location] input').fill('SHA');
      await page.locator('[role=option]', { hasText: 'CNSHA' }).first().waitFor(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
      await dlg.locator('[data-testid=sh-destination-location] input').fill('BUZ');
      await page.locator('[role=option]', { hasText: 'IRBUZ' }).first().waitFor(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
      await dlg.locator('[data-testid=sh-add-container]').click();
      await dlg.locator('[data-testid=sh-container-number] input').fill('CSQU3054384');
      check('wrong check digit shown', await dlg.locator('[data-testid=sh-container-number][data-state=invalid]').count() === 1);
      await dlg.locator('[data-testid=sh-container-number] input').fill('CSQU3054383');
      check('valid container shown', await dlg.locator('[data-testid=sh-container-number][data-state=valid]').count() === 1);
      await dlg.locator(`select[aria-label="${t('execution.shipments.containerType')}"]`).selectOption('45G1');
      await shot(`${lang}-shipment-dialog`, false);
      await page.locator('[data-testid=shipment-save]').click();
      const route = await poll(async () => (await page.locator('[data-testid=shipment-route]').allTextContents())[0]);
      check('route SHA - BUZ', route && route.includes('SHA') && route.includes('BUZ') && route.includes(lang === 'fa' ? '←' : '→'), route);
      await shot(`${lang}-shipment`);

      // ---- 4. codes on the case and «تأیید سند» with a QR payload ----
      step = `${lang} codes and verify`;
      await page.goto(`${BASE}/cases/${d.kase.id}`);
      const chip = await page.locator('[data-testid=code-chip]').first().textContent();
      check('case code chip', chip && /^CS-\d{4}-\d{4}/.test(chip.trim()), chip);
      const html = (await call('GET', `/api/quotes/${d.quote.id}/print`)).body;
      const payload = /data-payload='(BOMS\|[^']+)'/.exec(html)[1];
      await page.goto(`${BASE}/documents/verify`);
      await page.locator('#verify-payload').fill(payload);
      await page.locator('[data-testid=verify-submit]').click();
      const verified = page.locator('[data-testid=verify-result]');
      await verified.waitFor();
      check('verify genuine', (await verified.getAttribute('data-valid')) === 'true');
      await page.locator('#verify-payload').fill(payload.replace('|v1|', '|v2|'));
      await page.locator('[data-testid=verify-submit]').click();
      check('verify tampered', await poll(async () => (await verified.getAttribute('data-valid')) === 'false'));
      await shot(`${lang}-verify`);

      // ---- 5. AI settings with the cap at 80 % ----
      step = `${lang} ai settings`;
      await page.goto(`${BASE}/settings/ai`);
      const percent = Number(await page.locator('[data-testid=ai-cap]').getAttribute('data-percent'));
      check('cap at 80 %', percent >= 80 && percent < 100, percent);
      check('privacy log has the calls', await page.locator('[data-testid=ai-log] tbody tr').count() >= 2);
      await shot(`${lang}-ai-settings`);

      // ---- 6. «کارهای من» and the finance tab unchanged ----
      step = `${lang} tasks and finance`;
      await page.goto(`${BASE}/tasks`); await page.locator('h1').first().waitFor();
      await page.goto(`${BASE}/cases/${d.kase.id}?tab=finance`); await page.locator('[data-testid=finance-tab]').waitFor();
      r.unchanged = true;

      // ---- layout: the new pages in light/dark at 1280/1024 ----
      step = `${lang} layout`;
      for (const theme of ['light', 'dark']) {
        await ok('PATCH', '/api/me', { theme });
        for (const width of [1280, 1024]) {
          await page.setViewportSize({ width, height: 900 });
          for (const [name, url] of [['ai', '/settings/ai'], ['coding', '/settings/coding'], ['reference', '/settings/reference'],
            ['verify', '/documents/verify'], ["case", `/cases/${d.kase.id}?tab=logistics`]]) {
            await page.goto(BASE + url); await page.waitForTimeout(400);
            await overflow(`${lang} ${theme} ${width} ${name}`); await selectClip(`${lang} ${theme} ${width} ${name}`);
            if (width === 1280) await shot(`${lang}-${theme}-${name}`, false);
          }
        }
      }
      await ok('PATCH', '/api/me', { theme: 'light' });
    }
  } catch (e) {
    problems.push(`${step}: ${e.message.split('\n')[0]}`);
    await shot('failure').catch(() => {});
  }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
