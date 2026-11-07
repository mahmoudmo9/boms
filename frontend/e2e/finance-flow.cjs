// v0.8.0 M4 browser check (Playwright) against the dev server on 127.0.0.1:8765 (admin/admin12345), no network host.
// For fa (IRR sale to an Iranian buyer) and en (USD sale to a foreign buyer), after the Phase 8 steps (set up through the
// API: accepted quote -> sales order -> PO sent and confirmed -> goods received -> a first delivery):
//   partial invoice issued in the UI -> second delivery -> «invoice the rest» issued -> Moadian ID (fa) -> customer
//   payment (en: in USD at a rate) allocated in the UI -> supplier invoice matched with a price difference, approved with a
//   reason -> freight (USD at a rate) and customs actual costs -> claim credit note -> profit table -> close checklist with
//   reasons -> close -> ratings -> finance workspace tabs and CSV / zip export -> «کارهای من» -> command center.
// Then the finance tab, the workspace, «کارهای من» and the command center in light/dark at 1280/1024 px (no page
// overflow, no clipped select). Usage: NODE_PATH=$(npm root -g) node e2e/finance-flow.cjs <out dir> src/i18n
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  page.setDefaultTimeout(12000);
  const problems = [];
  const EXPECTED = [[409, '/approve'], [409, '/close']];          // the matching refusal the UI answers with a reason dialog
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
    const ct = r.headers.get('content-type') || '';
    return { status: r.status, body: r.status === 204 ? null : ct.includes('json') ? await r.json() : null };
  }, [method, path, body]);
  const ok = async (method, path, body) => {
    const r = await call(method, path, body);
    if (r.status >= 300) throw new Error(`${method} ${path} -> ${r.status} ${JSON.stringify(r.body).slice(0, 300)}`);
    return r.body;
  };
  const shot = async (name, full = true) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
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
  const soon = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
  const fin = (caseId) => ok('GET', `/api/cases/${caseId}/finance`);
  const results = [];
  let step = '';

  async function deal(lang, tag) {
    const fa = lang === 'fa';
    const buyer = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Buyer ${tag}`, name_fa: `خریدار ${tag}`, roles: ['buyer'],
      country_iso2: fa ? 'IR' : 'AE', ...(fa ? { national_id: '14000000000', economic_code: '411000000000' } : {}) })).party;
    const sup = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Supplier ${tag}`, name_fa: `تأمین‌کننده ${tag}`, roles: ['supplier'], country_iso2: 'CN' })).party;
    const kase = await ok('POST', '/api/cases', { title: `${fa ? 'معاملهٔ مالی' : 'Finance deal'} ${tag}`, party_id: buyer.id });
    const item = (await ok('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: `${fa ? 'پمپ' : 'Pump'} ${tag}`, quantity: '10', unit_code: 'pc' }] })).items[0];
    const offer = await ok('POST', '/api/offers', { case_id: kase.id, party_id: sup.id, channel: 'email', currency: 'USD', valid_until: soon(60),
      no_followup_reason: 'browser check', items: [{ line_item_id: item.id, unit_price: '100' }] });
    await ok('POST', `/api/line-items/${item.id}/select`, { offer_item_id: offer.items[0].id });
    const pricing = fa ? 'IRR' : 'USD';
    const sheet = await ok('POST', '/api/cost-sheets', { case_id: kase.id, deal_type: 'import', pricing_currency: pricing });
    if (fa) await ok('PUT', `/api/cost-sheets/${sheet.id}/fx`, { from_currency: 'USD', to_currency: 'IRR', rate: '500000', rate_kind: 'free market', as_of: soon(0) });
    for (const line of sheet.lines) {
      if (line.kind === 'purchase') continue;
      const body = line.kind === 'freight_international' ? { amount: fa ? '20000000' : '40', currency: pricing }
        : line.kind === 'customs_duty' ? { basis: 'total', amount: fa ? '30000000' : '60', currency: pricing }
          : line.basis.startsWith('percent') ? { percent: '0', tax_parameter_id: null } : { amount: '0', currency: pricing };
      await ok('PATCH', `/api/cost-sheets/lines/${line.id}`, body);
    }
    await ok('PATCH', `/api/cost-sheets/${sheet.id}`, { pricing_method: 'margin', target_percent: '20', annual_cost_of_money_percent: '36' });
    await ok('POST', `/api/cost-sheets/${sheet.id}/finalize`, { confirm: true });
    const quote = await ok('POST', '/api/quotes', { case_id: kase.id, language: lang });
    await ok('POST', `/api/quotes/${quote.id}/approve`);
    const sent = await ok('POST', `/api/quotes/${quote.id}/mark-sent`, { no_followup_reason: 'browser check' });
    await ok('PUT', `/api/quotes/${quote.id}/outcomes`, { items: sent.items.map((i) => ({ quote_item_id: i.id, outcome: 'accepted' })) });
    let so = await ok('POST', '/api/sales-orders/from-quote', { quote_id: quote.id });
    so = await ok('POST', `/api/sales-orders/${so.id}/confirm`, { no_document_reason: 'browser check' });
    const po = (await ok('POST', `/api/sales-orders/${so.id}/purchase-orders`)).created[0];
    await ok('POST', `/api/purchase-orders/${po.id}/approve`, { confirm_above_cost: true, reason: 'browser check' });
    await ok('POST', `/api/purchase-orders/${po.id}/mark-sent`, {});
    const conf = await ok('POST', `/api/purchase-orders/${po.id}/confirm`, { confirmed_ready_on: soon(5) });
    await ok('POST', '/api/receipts', { purchase_order_id: po.id, received_on: soon(-3), items: [{ purchase_order_item_id: conf.items[0].id, quantity: '10' }] });
    await ok('POST', '/api/deliveries', { sales_order_id: so.id, delivered_on: soon(-2), items: [{ sales_order_item_id: so.items[0].id, quantity: '6' }] });
    return { kase, buyer, sup, so, po: conf };
  }

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  try {
    await ok('PATCH', '/api/settings', { 'company.name_fa': 'بازرگانی نمونه', 'company.name_en': 'Sample Trading', 'company.national_id': '10320000000',
      'company.economic_code': '411111111111' });
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      const check = (key, cond, detail) => { r[key] = cond ? true : `FAIL ${detail ?? ''}`; if (!cond) problems.push(`${lang}: ${key} ${detail ?? ''}`); };
      results.push(r);
      await page.setViewportSize({ width: 1280, height: 900 });
      await ok('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);
      step = `${lang} setup`;
      const d = await deal(lang, tag);
      const caseId = d.kase.id;
      const tabUrl = `${BASE}/cases/${caseId}?tab=finance`;

      // ---- partial invoice, issued ----
      step = `${lang} partial invoice`;
      await page.goto(tabUrl);
      await page.locator('[data-testid=finance-tab]').waitFor();
      await page.locator('[data-testid=invoice-new]').first().click();
      const dlg = page.locator('[data-testid=invoice-dialog]');
      await dlg.locator('input[aria-label]').first().waitFor();
      check('partial defaults to delivered', (await dlg.locator('input[aria-label]').first().inputValue()) === '6');
      await page.locator('[data-testid=invoice-create]').click();
      await page.locator('[data-testid=sales-invoice][data-status=draft] [data-testid=invoice-issue]').click();
      check('partial issued', await poll(async () => (await fin(caseId)).sales_invoices.some((i) => i.status === 'issued')));
      // ---- second delivery, «invoice the rest» ----
      step = `${lang} invoice the rest`;
      await ok('POST', '/api/deliveries', { sales_order_id: d.so.id, delivered_on: soon(-1), items: [{ sales_order_item_id: d.so.items[0].id, quantity: '4' }] });
      await page.reload(); await page.locator('[data-testid=finance-tab]').waitFor();
      await page.locator('[data-testid=invoice-rest]').first().click();
      await page.locator('[data-testid=sales-invoice][data-status=draft] [data-testid=invoice-issue]').click();
      const invoices = await poll(async () => { const x = (await fin(caseId)).sales_invoices; return x.filter((i) => i.status === 'issued').length === 2 && x; });
      check('rest issued', !!invoices);
      check('quantities 6 + 4', invoices && invoices.map((i) => Number(i.lines[0].quantity)).sort().join() === '4,6');
      // Moadian (fa domestic): typed by the owner
      if (lang === 'fa') {
        step = 'fa moadian';
        check('moadian not_sent', invoices && invoices.every((i) => i.moadian_status === 'not_sent'));
        for (const inv of invoices) {
          const li = page.locator(`[data-invoice="${inv.id}"]`);
          if (!(await li.locator('[data-testid=moadian-form]').count())) await li.locator('button').first().click();
          const form = li.locator('[data-testid=moadian-form]');
          await form.locator('select').selectOption('accepted');
          await form.locator('input').first().fill(`A11${tag}${inv.number.slice(-2)}`.toUpperCase());
          await form.locator('[data-testid=moadian-save]').click();
        }
        check('moadian accepted', await poll(async () => (await fin(caseId)).sales_invoices.every((i) => i.status !== 'issued' || i.moadian_status === 'accepted')));
      }
      // ---- customer payment (en: in USD at a rate), allocated in the UI ----
      step = `${lang} customer payment`;
      const total = invoices.reduce((s, i) => s + Number(i.total), 0);
      const msIn = await ok('POST', '/api/payment-milestones', { sales_order_id: d.so.id, kind: 'balance', amount: String(total), amount_currency: d.so.currency });
      await ok('POST', `/api/payment-milestones/${msIn.id}/payments`, { amount: String(total), paid_on: soon(0), reference: `IN-${tag}`,
        ...(d.so.currency !== 'IRR' ? { fx_rate_to_base: '540000', rate_source: 'exchange' } : {}) });
      await page.reload(); await page.locator('[data-testid=finance-tab]').waitFor();
      await page.locator('[data-testid=payment-record] [data-testid=allocate]').first().click();
      await page.locator('[data-testid=allocation-dialog] input').first().waitFor();
      await page.locator('[data-testid=allocation-confirm]').click();
      check('customer payment allocated', await poll(async () => (await fin(caseId)).sales_invoices.every((i) => i.payment_status === 'paid')));
      if (lang === 'en') check('USD payment base amount', (await fin(caseId)).payments.some((p) => Number(p.base_amount) === total * 540000));
      // ---- supplier invoice matched with a price difference, approved with a reason ----
      step = `${lang} supplier invoice`;
      await page.locator('[data-testid=supplier-invoice-new]').click();
      await page.locator('#pi-no').fill(`SUP-${tag}`);
      await page.locator('[data-testid=supplier-invoice-save]').click();
      const si = page.locator('[data-testid=supplier-invoice]').first();
      await si.locator('[data-testid=matching-table]').waitFor();
      await si.locator('input[id^="pp-"]').fill('105');
      await si.locator('[data-testid=supplier-prices-save]').click();
      await poll(async () => (await fin(caseId)).purchase_invoices[0]?.matching.differences.length > 0);
      await page.locator('[data-testid=supplier-approve]').click();
      await page.locator('#reason-text').fill(t('finance.supplier.flags.price_difference'));
      await page.locator('[data-testid=reason-save]').click();
      check('supplier invoice approved with reason', await poll(async () => (await fin(caseId)).purchase_invoices[0]?.status === 'approved'));
      await shot(`${lang}-supplier-matching`);
      // ---- actual costs ----
      step = `${lang} actual costs`;
      for (const [kind, amount, currency, rate] of [['freight_international', '40', 'USD', '530000'], ['customs_duty', '32000000', 'IRR', null]]) {
        await page.locator('[data-testid=cost-new]').click();
        await page.locator('#ac-kind').selectOption(kind);
        await page.locator('#ac-desc').fill(`${kind} ${tag}`);
        await page.locator('#ac-amount').fill(amount);
        await page.locator('[data-testid=cost-dialog] select').nth(1).selectOption(currency);
        if (rate) await page.locator('#ac-rate').fill(rate);
        await page.locator('[data-testid=cost-save]').click();
        await page.locator('[data-testid=cost-dialog]').waitFor({ state: 'detached' });
      }
      check('two actual costs', await poll(async () => (await fin(caseId)).actual_costs.filter((c) => !c.read_only).length === 2));
      // ---- claim credit note from the supplier ----
      step = `${lang} claim`;
      const claim = await ok('POST', '/api/claims', { direction: 'against_supplier', kind: 'defect', purchase_order_id: d.po.id });
      await ok('POST', `/api/claims/${claim.id}/status`, { status: 'resolved', resolution: 'credit_note', resolution_amount: '50', resolution_amount_currency: 'USD' });
      // ---- profit table ----
      step = `${lang} profit`;
      await page.reload(); await page.locator('[data-testid=profit-table]').waitFor();
      check('profit rows', await page.locator('[data-testid=profit-row-purchase]').count() === 1 && await page.locator('[data-testid=profit-row-customs_duty]').count() === 1);
      if (lang === 'en') check('both currencies', (await page.locator('[data-testid=profit-table] thead').innerText()).includes('IRR'));
      await page.locator('[data-testid=profit-card]').scrollIntoViewIfNeeded();
      await shot(`${lang}-finance-tab`);
      // ---- close checklist with reasons, close ----
      step = `${lang} close`;
      const close = page.locator('[data-testid=close-card]');
      await close.waitFor();
      const codes = await close.locator('[data-problem]').evaluateAll((els) => els.map((e) => e.getAttribute('data-problem')));
      check('checklist lists the open payables', codes.includes('supplier_invoices_unpaid') && codes.includes('costs_unpaid'), codes.join());
      for (const input of await close.locator('[data-problem] input').all()) await input.fill('پرداخت پس از بستن');
      const cancelBox = close.locator('input[type=checkbox]');
      if (await cancelBox.count()) await cancelBox.check();
      await shot(`${lang}-close-checklist`);
      await page.locator('[data-testid=close-deal]').click();
      await page.locator('[data-testid=closed-card]').waitFor();
      check('case closed', (await ok('GET', `/api/cases/${caseId}`)).status === 'closed');
      check('items closed', (await ok('GET', `/api/cases/${caseId}`)).items.every((i) => i.status === 'closed'));
      // ---- ratings ----
      step = `${lang} ratings`;
      for (const block of await page.locator('[data-testid=ratings] [data-rating]').all()) {
        for (const sel of await block.locator('select').all()) await sel.selectOption('4');
        await block.locator('[data-testid=rating-save]').click();
        await block.locator(`text=${t('finance.ratings.saved')}`).waitFor();
      }
      check('two ratings', (await ok('GET', `/api/cases/${caseId}/ratings`)).ratings.length === 2);
      await shot(`${lang}-closed-ratings`);
      // ---- finance workspace tabs and exports ----
      step = `${lang} workspace`;
      for (const tab of ['receivables', 'payables', 'invoices', 'payments', 'deals', 'vat']) {
        await page.goto(`${BASE}/finance?tab=${tab}`);
        await page.locator(`[data-testid=fin-tab-${tab}]`).waitFor();
        await page.waitForTimeout(300);
        await shot(`${lang}-finance-${tab}`);
      }
      const csvCheck = await page.evaluate(async () => {
        const r = await fetch('/api/finance/exports/sales_invoices.csv'); const b = new Uint8Array(await r.arrayBuffer());
        const z = await fetch('/api/finance/exports/all.zip'); const zb = new Uint8Array(await z.arrayBuffer());
        return { bom: b[0] === 0xef && b[1] === 0xbb && b[2] === 0xbf, head: new TextDecoder().decode(b.slice(3, 80)), zip: zb[0] === 0x50 && zb[1] === 0x4b };
      });
      check('csv BOM', csvCheck.bom);
      check('csv header language', csvCheck.head.startsWith(lang === 'fa' ? 'شماره' : 'Number'), csvCheck.head);
      check('zip', csvCheck.zip);
      // ---- «کارهای من» and the command center ----
      step = `${lang} tasks`;
      await page.goto(`${BASE}/tasks`);
      await page.locator('[data-testid=tasks-group-overdue]').waitFor();
      await page.locator('#task-title').fill(lang === 'fa' ? 'تماس با حسابدار' : 'Call the accountant');
      await page.locator('[data-testid=task-quick-add] button:has-text("' + t('followups.quick.tomorrow') + '")').click();
      await page.locator('[data-testid=task-quick-add] button.bg-accent, [data-testid=task-quick-add] button:has-text("' + t('tasks.add') + '")').last().click();
      check('manual task added', await poll(async () => (await ok('GET', '/api/tasks')).groups.week.some((x) => x.source_kind === 'manual')));
      await shot(`${lang}-my-tasks`);
      step = `${lang} command center`;
      await page.goto(`${BASE}/command-center`);
      await page.locator('[data-testid=cc-finance]').waitFor();
      await page.locator('[data-testid=cc-tasks]').waitFor();
      await shot(`${lang}-command-center`);
      r.caseId = caseId;
    }

    // ---- layout: light / dark, 1280 / 1024 ----
    const caseId = results[0].caseId;
    for (const lang of ['fa', 'en']) {
      await ok('PATCH', '/api/me', { language: lang });
      for (const theme of ['light', 'dark']) {
        await ok('PATCH', '/api/me', { theme });
        for (const width of [1280, 1024]) {
          await page.setViewportSize({ width, height: 900 });
          for (const [name, url, sel] of [['finance-tab', `/cases/${results[lang === 'fa' ? 0 : 1].caseId}?tab=finance`, '[data-testid=finance-tab]'],
            ['workspace', '/finance?tab=invoices', '[data-testid=fin-tab-invoices]'], ['tasks', '/tasks', '[data-testid=tasks-group-today]'],
            ['cc', '/command-center', '[data-testid=cc-finance]']]) {
            step = `${lang} ${theme} ${width} ${name}`;
            await page.goto(BASE + url);
            await page.locator(sel).waitFor();
            await page.waitForTimeout(250);
            await overflow(step); await selectClip(step);
            await shot(`${lang}-${theme}-${width}-${name}`, false);
          }
        }
      }
      await ok('PATCH', '/api/me', { theme: 'light' });
    }
    void caseId;
  } catch (e) {
    problems.push(`${step}: ${e.message.split('\n')[0]}`);
    await shot('failure').catch(() => {});
  }
  await ok('PATCH', '/api/me', { language: 'fa', theme: 'light', calendar: 'jalali', digits: 'fa' }).catch(() => {});
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
