// v0.7.0 M4 browser check (Playwright) against the dev server on 127.0.0.1:8765 (admin/admin12345), no network host:
// 1. an import deal end to end, in fa and in en: accepted quote (set up through the API) -> sales order with the signed
//    document -> customer prepayment received -> POs for two suppliers (one fa, one en) -> approve, PDF and Word, mark
//    sent -> confirmation -> supplier prepayment -> process steps with order registration and kotaj numbers -> shipment
//    with B/L, containers and an ETA delay -> inspection pass -> receipt with a short line -> claim against the supplier
//    -> two partial deliveries -> sales order delivered -> command center;
// 2. a domestic deal from a Setad proforma (a Setad listing of the dev database converted through the API): sales order
//    -> one PO -> delivery with a warehouse receipt;
// 3. the four tabs, Settings -> Execution, the command center and the party page in light/dark at 1280/1024 px (no page
//    overflow, no clipped select) and focus kept while typing.
// Usage: NODE_PATH=$(npm root -g) node e2e/execution-flow.cjs <screenshot dir> src/i18n <headless chrome path>
// The Setad listing is picked with psql on the dev database (BOMS_DB_* from the environment). Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3]; const BROWSER_PATH = process.argv[4] || null;
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);
const psql = (sql) => execFileSync('psql', ['-h', '127.0.0.1', '-U', process.env.BOMS_DB_USER || 'boms_dev',
  process.env.BOMS_DB_NAME || 'boms_dev', '-Atc', sql], { env: { ...process.env, PGPASSWORD: process.env.BOMS_DB_PASSWORD || 'devpass-local' } }).toString().trim();

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  page.setDefaultTimeout(12000);
  const problems = [];
  // expected refusals the UI answers: the prepayment gate on sending, a step done without its document, a price above the sheet
  const EXPECTED = [[409, '/mark-sent'], [422, '/process-steps/'], [409, '/approve']];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => {
    if (!r.url().includes('/api/') || r.status() < 400) return;
    if (EXPECTED.some(([s, p]) => r.status() === s && r.url().includes(p))) return;
    problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`);
  });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const ok = async (method, path, body, want) => {
    const r = await call(method, path, body);
    if (want ? r.status !== want : r.status >= 300) throw new Error(`${method} ${path} -> ${r.status} ${JSON.stringify(r.body).slice(0, 300)}`);
    return r.body;
  };
  const shot = async (name, full = false) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  const poll = async (fn, ms = 10000, every = 300) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(every); } return null; };
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
  const file = (name) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from(`%PDF-1.4\n% ${name} ${Math.random()}\n`) });
  const pick = async (scope, id, name) => { await scope.locator(`#${id}`).setInputFiles(file(name)); await scope.locator(`[data-testid="${id}-set"]`).waitFor(); };
  const soon = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
  const typed = (lang, days) => page.evaluate(([lang, days]) => {
    const d = new Date(Date.now() + days * 86400000);
    const parts = new Intl.DateTimeFormat(lang === 'fa' ? 'en-u-ca-persian-nu-latn' : 'en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(d);
    const get = (k) => parts.find((p) => p.type === k).value.replace(/\D/g, '');
    return `${get('year')}/${get('month')}/${get('day')}`;
  }, [lang, days]);
  const ex = (caseId) => ok('GET', `/api/cases/${caseId}/execution`);
  const results = [];
  let step = '';

  /** A case with two items, offers from an Iranian supplier (USD) and a German one (EUR), a final import cost sheet,
   * and a quote sent and accepted. */
  async function importDeal(lang, tag) {
    const buyer = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Buyer ${tag}`, name_fa: `خریدار ${tag}`, roles: ['buyer'], country_iso2: lang === 'fa' ? 'IR' : 'AE' })).party;
    await ok('POST', '/api/contacts', { party_id: buyer.id, name_en: 'Reza', name_fa: 'رضا', is_primary: true });
    const kase = await ok('POST', '/api/cases', { title: `${lang === 'fa' ? 'معاملهٔ وارداتی' : 'Import deal'} ${tag}`, party_id: buyer.id });
    const items = (await ok('POST', '/api/line-items/bulk', { case_id: kase.id, items: [
      { name: `${lang === 'fa' ? 'شیر توپی' : 'Ball valve'} DN50 ${tag}`, quantity: '10', unit_code: 'pc' },
      { name: `${lang === 'fa' ? 'پمپ سانتریفیوژ' : 'Centrifugal pump'} ${tag}`, quantity: '2', unit_code: 'pc' }] })).items;
    const suppliers = [];
    for (const [item, currency, price, country, fa] of [[items[0], 'USD', '12.5', 'IR', true], [items[1], 'EUR', '300', 'DE', false]]) {
      const sup = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Supplier ${currency} ${tag}`, ...(fa ? { name_fa: `تأمین‌کننده ${tag}` } : {}), roles: ['supplier'], country_iso2: country })).party;
      suppliers.push(sup);
      const offer = await ok('POST', '/api/offers', { case_id: kase.id, party_id: sup.id, channel: 'email', currency, valid_until: soon(60), payment_terms: '30% advance, 70% before shipment',
        no_followup_reason: 'browser check', items: [{ line_item_id: item.id, unit_price: price }] });
      await ok('POST', `/api/line-items/${item.id}/select`, { offer_item_id: offer.items[0].id });
    }
    const sheet = await ok('POST', '/api/cost-sheets', { case_id: kase.id, deal_type: 'import', pricing_currency: 'IRR' });
    for (const [from, rate] of [['USD', '600000'], ['EUR', '650000']]) await ok('PUT', `/api/cost-sheets/${sheet.id}/fx`, { from_currency: from, to_currency: 'IRR', rate, rate_kind: 'free market', as_of: soon(0) });
    for (const line of sheet.lines) {
      if (line.kind !== 'purchase' && line.basis === 'total') await ok('PATCH', `/api/cost-sheets/lines/${line.id}`, { amount: '10000000', currency: 'IRR' });
      else if (line.basis.startsWith('percent')) await ok('PATCH', `/api/cost-sheets/lines/${line.id}`, { percent: '4', tax_parameter_id: null });
    }
    await ok('PATCH', `/api/cost-sheets/${sheet.id}`, { pricing_method: 'margin', target_percent: '20' });
    await ok('POST', `/api/cost-sheets/${sheet.id}/finalize`, { confirm: true });
    const quote = await ok('POST', '/api/quotes', { case_id: kase.id, language: lang });
    await ok('POST', `/api/quotes/${quote.id}/approve`);
    const sent = await ok('POST', `/api/quotes/${quote.id}/mark-sent`, { no_followup_reason: 'browser check' });
    await ok('PUT', `/api/quotes/${quote.id}/outcomes`, { items: sent.items.map((i) => ({ quote_item_id: i.id, outcome: 'accepted' })) });
    return { kase, items, suppliers, buyer, quote };
  }

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  try {
    await ok('PATCH', '/api/settings', { 'company.name_fa': 'بازرگانی نمونه', 'company.name_en': 'Sample Trading', 'company.national_id': '10320000000',
      'execution.delay_warning_days': 3, ...(BROWSER_PATH ? { 'pdf.browser_path': BROWSER_PATH } : {}) });
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      const check = (key, cond, detail) => { r[key] = cond ? true : `FAIL ${detail ?? ''}`; if (!cond) problems.push(`${lang}: ${key} ${detail ?? ''}`); };
      results.push(r);
      await page.setViewportSize({ width: 1280, height: 900 });
      await ok('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);
      step = `${lang} setup`;
      const deal = await importDeal(lang, tag);
      const caseId = deal.kase.id;

      // ---- 1. sales order with the signed document ----
      step = `${lang} sales order`;
      await page.goto(`${BASE}/cases/${caseId}?tab=order`);
      await page.locator('[data-testid=so-candidates]').waitFor();
      await page.locator('[data-testid=create-so]').click();
      const so = page.locator('[data-testid=sales-order]');
      await so.waitFor();
      const soId = await so.getAttribute('data-so');
      const ref = so.locator('input[id^="so-ref-"]');
      await ref.click(); await page.keyboard.type('CR-778-' + tag, { delay: 25 });
      check('focus kept in customer ref', await ref.evaluate((n) => document.activeElement === n));
      await page.locator('h1').first().click();
      check('customer ref saved', await poll(async () => (await ok('GET', `/api/sales-orders/${soId}`)).customer_ref === 'CR-778-' + tag));
      await page.locator('[data-testid=so-confirm]').click();
      const confirmDialog = page.locator('[data-testid=confirm-dialog]');
      await pick(confirmDialog, 'so-signed', 'signed-contract.pdf');
      await page.locator('[data-testid=confirm-save]').click();
      check('order confirmed with the signed document', await poll(async () => { const x = await ok('GET', `/api/sales-orders/${soId}`); return x.status === 'confirmed' && x.signed_document_id; }));
      await shot(`${lang}-order`);

      // ---- 2. customer prepayment received ----
      step = `${lang} prepayment in`;
      await page.locator('[data-testid=milestones-in-add]').waitFor();
      await page.getByRole('button', { name: `+ ${t('execution.milestones.quickPrepayment')}` }).click();
      await page.locator('#ms-value').fill('30');
      const msLabel = page.locator('#ms-label');
      await msLabel.fill(''); await msLabel.click(); await page.keyboard.type(lang === 'fa' ? 'پیش‌پرداخت قرارداد' : 'Contract prepayment', { delay: 20 });
      check('focus kept in milestone label', await msLabel.evaluate((n) => document.activeElement === n));
      await page.locator('[data-testid=milestone-save]').click();
      await page.locator('[data-testid=milestones-in] [data-testid=record-payment]').click();
      await page.locator('#pay-ref').fill('TRX-' + tag);
      await page.locator('[data-testid=payment-save]').click();
      check('prepayment received', await poll(async () => (await ok('GET', `/api/sales-orders/${soId}`)).milestones[0]?.status === 'done'));
      check('cash position shows it', await poll(async () => (await page.locator('[data-testid=cash-position]').innerText()).includes(t('execution.cash.received'))));
      await shot(`${lang}-prepayment`);

      // ---- 3. POs for two suppliers: approve, PDF and Word, mark sent, confirmation, supplier prepayment ----
      step = `${lang} purchase orders`;
      await page.goto(`${BASE}/cases/${caseId}?tab=purchase`);
      await page.locator('[data-testid=create-pos]').click();
      check('two POs', await poll(async () => (await ex(caseId)).purchase_orders.length === 2));
      const pos = (await ex(caseId)).purchase_orders;
      check('one fa and one en PO', pos.map((p) => p.language).sort().join() === 'en,fa', pos.map((p) => p.language).join());
      for (const po of pos) {
        const scope = page.locator(`[data-testid=purchase-order][data-po="${po.id}"]`);
        await scope.waitFor();
        const cardRoot = page.locator(`[data-po-card="${po.id}"]`);
        await cardRoot.locator('[data-testid=po-approve]').click();
        const reason = page.locator('#reason-text');
        if (await reason.isVisible().catch(() => false)) { await reason.fill('price confirmed by phone'); await page.locator('[data-testid=reason-save]').click(); }
        await poll(async () => (await ok('GET', `/api/purchase-orders/${po.id}`)).status === 'approved');
        for (const fmt of ['PDF', 'Word']) {
          const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 90000 }), scope.getByRole('button', { name: fmt, exact: true }).click()]);
          const name = dl.suggestedFilename();
          await dl.saveAs(`${OUT}/${lang}-${name}`);
          const head = fs.readFileSync(`${OUT}/${lang}-${name}`).subarray(0, 4).toString('latin1');
          check(`${po.currency} ${fmt}`, name.startsWith(po.number) && !name.includes('DRAFT') && (fmt === 'PDF' ? head === '%PDF' : head.startsWith('PK')), `${name} ${head}`);
        }
        await cardRoot.locator('[data-testid=po-send]').click();
        await page.locator('[data-testid=sent-save]').click();
        await poll(async () => (await ok('GET', `/api/purchase-orders/${po.id}`)).status === 'sent');
        await cardRoot.locator('[data-testid=po-confirm]').click();
        await page.locator('#po-sref').fill(`SUP-${po.currency}-${tag}`);
        await page.locator('#po-cready').fill(await typed(lang, 20)); await page.locator('#po-cready').blur();
        await page.locator('[data-testid=po-confirm-save]').click();
        check(`${po.currency} confirmed`, await poll(async () => { const x = await ok('GET', `/api/purchase-orders/${po.id}`); return x.status === 'confirmed' && x.followups.some((f) => f.purpose === 'po_ready'); }));
      }
      step = `${lang} supplier prepayment`;
      const usd = pos.find((p) => p.currency === 'USD');
      const outCard = page.locator(`[data-testid=milestones-out-USD-add]`);
      await outCard.click();
      await page.locator('#ms-mode').selectOption('amount');
      await page.locator('#ms-value').fill('37.5');
      await page.locator('[data-testid=milestone-save]').click();
      await page.locator('[data-testid="milestones-out-USD"] [data-testid=record-payment]').click();
      await page.locator('[data-testid=payment-save]').click();
      check('supplier prepayment paid', await poll(async () => (await ok('GET', `/api/purchase-orders/${usd.id}`)).milestones[0]?.status === 'done'));
      await shot(`${lang}-purchase`, true);

      // ---- 4. process steps: order registration and kotaj numbers ----
      step = `${lang} process`;
      await page.goto(`${BASE}/cases/${caseId}?tab=logistics`);
      const reg = page.locator('[data-testid=process-step][data-code=order_registration]');
      await reg.waitFor();
      const regRef = reg.locator('input[id^="ref-"]');
      await regRef.click(); await page.keyboard.type('12345-' + tag, { delay: 25 });
      check('focus kept in step reference', await regRef.evaluate((n) => document.activeElement === n));
      await page.locator('h1').first().click();
      await pick(reg, await reg.locator('input[type=file]').getAttribute('id'), 'order-registration.pdf');
      await reg.locator('select').selectOption('done');
      const kotaj = page.locator('[data-testid=process-step][data-code=declaration_kotaj]');
      await kotaj.locator('input[id^="ref-"]').fill('KTJ-' + tag); await page.locator('h1').first().click();
      await kotaj.locator('select').selectOption('done');                 // needs a document: the reason field appears
      const nodoc = kotaj.locator('input[id^="nodoc-"]');
      await nodoc.waitFor();
      await nodoc.fill(lang === 'fa' ? 'اظهارنامه نزد ترخیص‌کار است' : 'The declaration is with the customs broker'); await nodoc.blur();
      check('steps done with references', await poll(async () => {
        const p = (await ex(caseId)).processes[0];
        const s = (c) => p.steps.find((x) => x.code === c);
        return s('order_registration').status === 'done' && s('order_registration').reference === '12345-' + tag && s('declaration_kotaj').status === 'done'
          && s('declaration_kotaj').reference === 'KTJ-' + tag;
      }));
      await shot(`${lang}-process`);

      // ---- 5. shipment with B/L, containers and an ETA delay; inspection pass ----
      step = `${lang} shipment`;
      await page.locator('[data-testid=add-shipment]').click();
      const sd = page.locator('[data-testid=shipment-dialog]');
      await sd.waitFor();
      await page.locator('#sh-po').selectOption(usd.id);
      await page.locator('#sh-dn').fill('MEDU' + tag.toUpperCase());
      await page.locator('#sh-cont').fill('MSCU1234567, TGHU7654321');
      await page.locator('#sh-eta').fill(await typed(lang, 25)); await page.locator('#sh-eta').blur();
      await sd.getByRole('textbox', { name: new RegExp(lang === 'fa' ? 'شیر توپی' : 'Ball valve') }).fill('10');
      await selectClip(`${lang} shipment dialog`);
      await page.locator('[data-testid=shipment-save]').click();
      const sh = page.locator('[data-testid=shipment]');
      await sh.waitFor();
      const shId = await sh.getAttribute('data-shipment');
      await sh.locator(`input[id^="sh-eta-"]`).fill(await typed(lang, 32)); await sh.locator(`input[id^="sh-eta-"]`).blur();
      check('ETA delay event and warning', await poll(async () => {
        const s = (await ex(caseId)).shipments[0];
        return s.events.some((e) => e.kind === 'delay') && (await page.locator('[data-testid=delay-warning]').count()) > 0;
      }));
      check('containers', (await ok('GET', `/api/shipments/${shId}`)).containers.join() === 'MSCU1234567,TGHU7654321');
      await page.locator('#in-result').selectOption('pass');
      await page.locator('[data-testid=add-inspection]').click();
      check('inspection pass', await poll(async () => (await ex(caseId)).inspections.some((i) => i.result === 'pass')));
      await shot(`${lang}-logistics`, true);

      // ---- 6. receipt with a short line -> claim against the supplier ----
      step = `${lang} receipt`;
      await page.goto(`${BASE}/cases/${caseId}?tab=purchase`);
      const usdScope = page.locator(`[data-testid=purchase-order][data-po="${usd.id}"]`);
      await usdScope.locator('[data-testid=po-receipt]').click();
      const rd = page.locator('[data-testid=receipt-dialog]');
      await rd.locator('input[dir=ltr]').last().fill('9');
      await rd.locator('select').last().selectOption('short');
      await page.locator('[data-testid=receipt-save]').click();
      await usdScope.locator('[data-testid=open-claim]').click();
      await page.waitForURL(/tab=delivery/);
      check('claim against the supplier', await poll(async () => (await ex(caseId)).claims.some((c) => c.direction === 'against_supplier' && c.kind === 'shortage' && c.receipt_id)));

      // ---- 7. two partial deliveries -> sales order delivered ----
      step = `${lang} deliveries`;
      await page.locator('[data-testid=add-delivery]').click();
      const dd = page.locator('[data-testid=delivery-dialog]');
      const qty = (name) => dd.getByRole('textbox', { name: new RegExp(`${t('execution.delivery.quantity')} .*${name}`) });
      await qty(lang === 'fa' ? 'شیر توپی' : 'Ball valve').fill('6');
      await qty(lang === 'fa' ? 'پمپ' : 'Centrifugal pump').fill('0');
      await pick(dd, 'dl-doc', 'warehouse-receipt-1.pdf');
      await page.locator('[data-testid=delivery-save]').click();
      check('first delivery partial', await poll(async () => { const x = await ex(caseId); const s = x.sales_orders[0];
        return x.deliveries.length === 1 && s.status === 'in_progress' && s.progress.items_delivered === 0; }));
      await page.reload(); await page.locator('[data-testid=delivery-tab]').waitFor();
      check('item progress shown', (await page.locator('[data-testid=item-progress][data-complete=false]').count()) >= 1);
      await page.locator('[data-testid=add-delivery]').click();
      await page.locator('#dl-recv').fill(lang === 'fa' ? 'انبار مشتری' : 'Customer warehouse');
      await page.locator('[data-testid=delivery-save]').click();
      check('order delivered', await poll(async () => (await ex(caseId)).sales_orders[0].status === 'delivered'));
      check('items delivered', await poll(async () => (await ok('GET', `/api/cases/${caseId}`)).items.every((i) => i.status === 'delivered')));
      await page.reload(); await page.locator('[data-testid=delivery-tab]').waitFor();
      check('header shows delivery progress', (await page.locator('[data-testid=execution-header]').innerText()).length > 0);
      await shot(`${lang}-delivery`, true);

      // ---- 8. command center ----
      step = `${lang} command center`;
      await page.goto(`${BASE}/command-center`);
      const cc = page.locator('[data-testid=cc-execution]');
      await cc.waitFor(); await cc.scrollIntoViewIfNeeded();
      check('cc execution section', (await cc.innerText()).includes(t('cc.execution.title')));
      await shot(`${lang}-cc`);

      // ---- 9. layout: light/dark, 1280/1024 ----
      for (const theme of ['light', 'dark']) {
        await ok('PATCH', '/api/me', { theme });
        for (const width of [1280, 1024]) {
          await page.setViewportSize({ width, height: 900 });
          for (const [name, path, ready] of [['order', `/cases/${caseId}?tab=order`, '[data-testid=order-tab]'], ['purchase', `/cases/${caseId}?tab=purchase`, '[data-testid=purchase-tab]'],
            ['logistics', `/cases/${caseId}?tab=logistics`, '[data-testid=logistics-tab]'], ['delivery', `/cases/${caseId}?tab=delivery`, '[data-testid=delivery-tab]'],
            ['settings', '/settings/execution', '[data-testid=process-templates]'], ['execution', '/execution', '[data-testid=cc-execution]'],
            ['party', `/parties/${deal.suppliers[0].id}?tab=orders`, '[data-testid=party-purchase-orders]']]) {
            step = `${lang} ${theme} ${width} ${name}`;
            await page.goto(BASE + path);
            await page.locator(ready).first().waitFor();
            await page.waitForLoadState('networkidle');
            await overflow(step); await selectClip(step);
            await shot(`${lang}-${theme}-${width}-${name}`, name !== 'settings');
          }
        }
      }
      await ok('PATCH', '/api/me', { theme: 'light' });
    }

    // ---- 10. a domestic deal from a Setad proforma: sales order -> one PO -> delivery with a warehouse receipt ----
    step = 'setad domestic setup';
    const r = { lang: 'fa-setad' }; results.push(r);
    const check = (key, cond, detail) => { r[key] = cond ? true : `FAIL ${detail ?? ''}`; if (!cond) problems.push(`setad: ${key} ${detail ?? ''}`); };
    await page.setViewportSize({ width: 1280, height: 900 });
    await ok('PATCH', '/api/me', { language: 'fa', theme: 'light', calendar: 'jalali', digits: 'fa' });
    const lid = psql(`SELECT l.id FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
      WHERE l.source = 'setad_purchase' AND coalesce(s.status, 'new') NOT IN ('converted', 'dismissed') ORDER BY l.external_no LIMIT 1`);
    if (!lid) throw new Error('no Setad purchase listing left to convert');
    await ok('POST', `/api/listings/${lid}/screen`, { action: 'star' });
    const conv = await ok('POST', `/api/listings/${lid}/convert`, { create_party: true, confirm_duplicate: true, without_missing_files: true });
    await ok('PUT', `/api/inquiries/${conv.inquiry_id}/decision`, { light: 'green', reason: 'browser check', feasible_sourcing: 'yes', exposure_acceptable: 'yes', requirements_ok: 'yes' });
    const kase = await ok('POST', `/api/inquiries/${conv.inquiry_id}/convert`, {});
    const items = (await ok('GET', `/api/cases/${kase.id}`)).items;
    const sup = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_fa: `تأمین‌کنندهٔ داخلی ${Date.now() % 100000}`, roles: ['supplier'], country_iso2: 'IR' })).party;
    const offer = await ok('POST', '/api/offers', { case_id: kase.id, party_id: sup.id, channel: 'phone', currency: 'IRR', valid_until: soon(60),
      no_followup_reason: 'browser check', items: items.map((i) => ({ line_item_id: i.id, unit_price: '15000000' })) });
    for (const [i, it] of items.entries()) await ok('POST', `/api/line-items/${it.id}/select`, { offer_item_id: offer.items[i].id });
    const sheet = await ok('POST', '/api/cost-sheets', { case_id: kase.id, deal_type: 'domestic', pricing_currency: 'IRR' });
    await ok('POST', `/api/cost-sheets/${sheet.id}/lines/not-applicable`);
    await ok('PATCH', `/api/cost-sheets/${sheet.id}`, { pricing_method: 'margin', target_percent: '20' });
    await ok('POST', `/api/cost-sheets/${sheet.id}/finalize`, { confirm: true });
    let quote = await ok('POST', '/api/quotes', { case_id: kase.id });
    if (quote.approval?.failures?.some((f) => f.code === 'validity_shorter_than_required')) await ok('POST', `/api/quotes/${quote.id}/validity-override`, { reason: 'browser check' });
    await ok('POST', `/api/quotes/${quote.id}/approve`);
    quote = await ok('POST', `/api/quotes/${quote.id}/mark-sent`, { no_followup_reason: 'browser check' });
    check('Setad proforma', !!quote.setad, JSON.stringify(quote.setad));
    await ok('PUT', `/api/quotes/${quote.id}/outcomes`, { items: quote.items.map((i) => ({ quote_item_id: i.id, outcome: 'accepted' })) });
    step = 'setad domestic flow';
    await page.goto(`${BASE}/cases/${kase.id}?tab=order`);
    await page.locator('[data-testid=create-so]').click();
    await page.locator('[data-testid=so-confirm]').click();
    await page.getByRole('checkbox').check();
    await page.locator('[data-testid=confirm-save]').click();
    check('order confirmed without a signed document', await poll(async () => (await ex(kase.id)).sales_orders[0].status === 'confirmed'));
    check('domestic checklist', await poll(async () => (await ex(kase.id)).processes[0]?.deal_type === 'domestic'));
    await page.goto(`${BASE}/cases/${kase.id}?tab=purchase`);
    await page.locator('[data-testid=create-pos]').click();
    const po = await poll(async () => (await ex(kase.id)).purchase_orders[0]);
    check('one PO', !!po && (await ex(kase.id)).purchase_orders.length === 1);
    await page.locator('[data-testid=po-approve]').click();
    await poll(async () => (await ok('GET', `/api/purchase-orders/${po.id}`)).status === 'approved');
    await page.locator('[data-testid=po-send]').click();
    await page.locator('[data-testid=sent-save]').click();
    check('PO sent', await poll(async () => (await ok('GET', `/api/purchase-orders/${po.id}`)).status === 'sent'));
    await page.goto(`${BASE}/cases/${kase.id}?tab=delivery`);
    await page.locator('[data-testid=add-delivery]').click();
    await pick(page.locator('[data-testid=delivery-dialog]'), 'dl-doc', 'رسید-انبار.pdf');
    await page.locator('#dl-recv').fill('انباردار');
    await page.locator('[data-testid=delivery-save]').click();
    check('delivered with a warehouse receipt', await poll(async () => {
      const x = await ex(kase.id);
      return x.sales_orders[0].status === 'delivered' && x.deliveries[0]?.receipt_document_id;
    }));
    check('domestic «PO sent» step ticked', (await ex(kase.id)).processes[0].steps.find((s) => s.code === 'po_sent').status === 'done');
    await shot('fa-setad-delivery', true);
  } catch (e) {
    problems.push(`exception at ${step}: ${e.message.split('\n')[0]}`);
    await shot('exception', true);
  }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
