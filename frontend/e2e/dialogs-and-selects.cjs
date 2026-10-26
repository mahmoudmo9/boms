// v0.3.1 browser check (Playwright, run against a dev server on 127.0.0.1:8765 with user admin/admin12345):
// focus in free-text dialogs (types multi-character strings key by key), select clipping in fa and en,
// mark-sent follow-up preview, selection-lost badge, danger zones. Creates test data in the dev database.
// Usage: NODE_PATH=$(npm root -g) node e2e/dialogs-and-selects.cjs <screenshot dir> src/i18n [focus-only]
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3]; const FOCUS_ONLY = process.argv[4] === 'focus-only';
const BASE = 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(8000);
  const problems = [];
  const expected = new Set(['409 DELETE /api/parties/:id', '404 GET /api/inquiries/:id', '404 GET /api/cases/:id']);
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => {
    const key = `${r.status()} ${r.request().method()} ${r.url().replace(BASE, '').split('?')[0].replace(/[0-9a-f-]{36}/g, ':id')}`;
    if (r.url().includes('/api/') && r.status() >= 400 && !expected.has(key)) problems.push(key);
  });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const shot = async (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) problems.push(`overflow: ${label}`); };

  // types a multi-character string key by key; the field must keep focus and hold the whole string
  const focusResults = {};
  const typeCheck = async (label, selector, text) => {
    const loc = page.locator(selector);
    await loc.waitFor();
    await loc.click();
    await loc.fill('');
    await loc.pressSequentially(text, { delay: 20 });
    const res = await page.evaluate(([sel, text]) => {
      const el = document.querySelector(sel);
      if (!el) return { ok: false, focused: false, value: null, active: 'field gone (dialog closed)' };
      return { focused: document.activeElement === el, value: el.value, ok: document.activeElement === el && el.value === text,
        active: document.activeElement?.getAttribute('aria-label') || document.activeElement?.id || document.activeElement?.tagName };
    }, [selector, text]);
    focusResults[label] = res.ok ? 'ok' : `FAIL focused=${res.focused} value=${JSON.stringify(res.value)} active=${res.active}`;
    if (!res.ok) { problems.push(`focus: ${label}`); await shot(`focus-fail-${label.replace(/ /g, '-')}`); if (FOCUS_ONLY) await page.keyboard.press('Escape'); }
  };

  // every visible <select>: the longest option text must fit inside the content box
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
  const clip = {};
  const checkSelects = async (label) => { const c = await selectClip(label); clip[label] = c.length ? c : 'ok'; problems.push(...c); };

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
    const mk = async (body) => (await call('POST', '/api/parties', { confirm_duplicate: true, ...body })).body.party;
    const a = await mk({ name_en: `Alpha Valves ${tag}`, roles: ['supplier'], country_iso2: 'CN' });
    await call('POST', '/api/contacts', { party_id: a.id, name_en: 'Wang Lei', methods: [{ type: 'email', value: `s${tag}@alpha.example` }] });
    const b = await mk({ name_fa: `شیرآلات بهار ${tag}`, roles: ['supplier'], country_iso2: 'IR' });
    const kase = (await call('POST', '/api/cases', { title: `Case ${tag}` })).body;
    const items = (await call('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: 'Ball valve DN50' }, { name: 'Gate valve DN80' }, { name: 'Spare gasket' }] })).body.items;
    const soon = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);

    // --- RFQ builder: selects must not clip (change 6) --------------------------------------------
    await page.goto(`${BASE}/cases/${kase.id}?tab=rfqs`);
    await page.getByRole('button', { name: t('sourcing.rfq.new'), exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByPlaceholder(t('sourcing.rfq.searchSuppliers')).fill(tag);
    await dialog.locator('li', { hasText: `Alpha Valves ${tag}` }).last().getByRole('button', { name: t('common.add') }).click();
    await dialog.locator('li', { hasText: `شیرآلات بهار ${tag}` }).last().getByRole('button', { name: t('common.add') }).click();
    await page.waitForTimeout(300);
    await checkSelects(`${lang} rfq builder`);
    await shot(`${lang}-rfq-builder`);
    await page.setViewportSize({ width: 1024, height: 900 });
    await page.waitForTimeout(200);
    await checkSelects(`${lang} rfq builder 1024px`);
    await overflow(`${lang} rfq builder 1024px`); await shot(`${lang}-rfq-builder-1024`);
    await page.setViewportSize({ width: 1280, height: 900 });
    await dialog.getByRole('button', { name: t('common.cancel'), exact: true }).click();

    const rfq1 = (await call('POST', '/api/rfqs', { case_id: kase.id, respond_by: soon(5), items: items.slice(0, 2).map((i) => ({ line_item_id: i.id })),
      recipients: [{ party_id: a.id }, { party_id: b.id }] })).body;
    const rfq2 = (await call('POST', '/api/rfqs', { case_id: kase.id, items: [{ line_item_id: items[2].id }], recipients: [{ party_id: b.id }], title: `No date ${tag}` })).body;

    // --- mark-sent dialog shows the follow-up (change 5) ------------------------------------------
    await page.goto(`${BASE}/cases/${kase.id}?tab=rfqs&rfq=${rfq1.id}`);
    await page.waitForSelector('text=Wang Lei');
    await checkSelects(`${lang} rfq recipient cards`);
    await page.locator('li', { hasText: `Alpha Valves ${tag}` }).getByRole('button', { name: t('sourcing.rfq.markSent'), exact: true }).click();
    const ms = page.getByRole('dialog');
    const preview = await ms.getByTestId('ms-preview').innerText();
    r.previewShown = preview.includes(tr('en', 'sourcing.rfq.chaseAction'));  // Alpha (CN) gets English texts
    await typeCheck(`${lang} mark-sent action`, '#ms-action', lang === 'fa' ? 'پیگیری تلفنی با آقای وانگ' : 'Call Mr Wang about prices');
    r.previewFollowsEdit = (await ms.getByTestId('ms-preview').innerText()).includes(lang === 'fa' ? 'پیگیری تلفنی' : 'Call Mr Wang');
    await shot(`${lang}-mark-sent-dialog`);
    await ms.getByRole('button', { name: t('sourcing.rfq.markSent'), exact: true }).click();
    await page.waitForSelector('[role=dialog]', { state: 'detached' });
    const sentEv = (await call('GET', `/api/events?entity_type=rfq&entity_id=${rfq1.id}&action=sent`)).body.items[0].data;
    r.followupRecorded = !!sentEv.followup_id;
    // RFQ without respond_by: needs a date or an explicit no-follow-up reason
    await call('POST', `/api/rfqs/recipients/${rfq1.recipients.find((x) => x.party_id === b.id).id}/mark-sent`, { no_followup_reason: 'test' });
    await page.goto(`${BASE}/cases/${kase.id}?tab=rfqs&rfq=${rfq2.id}`);
    await page.getByRole('button', { name: t('sourcing.rfq.markSent'), exact: true }).first().click();
    const ms2 = page.getByRole('dialog');
    r.needsDateShown = (await ms2.getByTestId('ms-preview').innerText()).includes(t('sourcing.rfq.followupNeedsDate').slice(0, 12));
    r.sendDisabledWithoutDate = await ms2.getByRole('button', { name: t('sourcing.rfq.markSent'), exact: true }).isDisabled();
    await ms2.getByText(t('sourcing.rfq.noFollowup'), { exact: true }).click();
    await typeCheck(`${lang} mark-sent no-follow-up reason`, '#ms-reason', lang === 'fa' ? 'خودشان تماس می‌گیرند' : 'They will call back');
    await ms2.getByRole('button', { name: t('sourcing.rfq.markSent'), exact: true }).click();
    await page.waitForSelector('[role=dialog]', { state: 'detached' });
    r.noFollowupSent = (await call('GET', `/api/rfqs/${rfq2.id}`)).body.status === 'sent';

    // --- offers, selection, change-selection dialog (change 2) ------------------------------------
    const offer = async (party, price) => (await call('POST', '/api/offers', { case_id: kase.id, party_id: party.id, channel: 'email', currency: 'USD',
      valid_until: soon(30), no_followup_reason: 'comparing', items: [{ line_item_id: items[0].id, unit_price: price }, { line_item_id: items[1].id, unit_price: price }] })).body;
    const oa = await offer(a, '100'); const ob = await offer(b, '90');
    await call('POST', `/api/line-items/${items[0].id}/select`, { offer_item_id: oa.items[0].id });
    await page.goto(`${BASE}/cases/${kase.id}?tab=comparison`);
    await page.getByRole('button', { name: t('sourcing.compare.select'), exact: true }).first().click();
    await typeCheck(`${lang} change-selection reason`, '#sel-reason', lang === 'fa' ? 'زمان تحویل کوتاه‌تر' : 'Shorter lead time');
    await shot(`${lang}-change-selection`);
    if (FOCUS_ONLY) await call('POST', `/api/line-items/${items[0].id}/select`, { offer_item_id: ob.items[0].id, reason: 'x' });
    else await page.getByRole('dialog').getByRole('button', { name: t('sourcing.compare.select'), exact: true }).click();
    await page.waitForSelector('[role=dialog]', { state: 'detached' });
    r.selectionChanged = (await call('GET', `/api/line-items/${items[0].id}`)).body.selected_offer_item_id === ob.items[0].id;

    // --- selection lost badge + command center list (change 1) ------------------------------------
    await call('POST', `/api/offers/${ob.id}/status`, { status: 'withdrawn', note: 'test' });
    const lostItem = (await call('GET', `/api/line-items/${items[0].id}`)).body;
    r.statusAfterWithdraw = lostItem.status;
    await page.goto(`${BASE}/cases/${kase.id}?tab=items`);
    await page.waitForSelector(`text=${t('sourcing.coverage.title')}`);
    r.badge = await page.getByText(t('sourcing.selectionLost'), { exact: true }).count() === 1;
    await checkSelects(`${lang} case items`);
    await overflow(`${lang} case items`); await shot(`${lang}-selection-lost-badge`);
    await page.goto(`${BASE}/command-center`); await page.waitForSelector('h1');
    r.ccList = await page.locator('a', { hasText: 'Ball valve DN50' }).count() > 0;
    await shot(`${lang}-command-center`);

    // --- no-coverage dialog (the reported defect) --------------------------------------------------
    await page.goto(`${BASE}/cases/${kase.id}?tab=items`);
    await page.waitForSelector(`text=${t('sourcing.coverage.title')}`);
    await page.getByRole('button', { name: t('sourcing.markNoCoverage'), exact: true }).last().click();
    await typeCheck(`${lang} no-coverage reason`, '#nc-reason, #item-reason', lang === 'fa' ? 'این قلم دیگر تولید نمی‌شود' : 'Not produced any more');
    await shot(`${lang}-no-coverage`);
    if (FOCUS_ONLY) { results.push(r); continue; }
    await page.getByRole('dialog').getByRole('button', { name: t('common.save'), exact: true }).click();
    await page.waitForSelector('[role=dialog]', { state: 'detached' });
    if (FOCUS_ONLY) { results.push(r); continue; }

    // --- cancel item ---------------------------------------------------------------------------
    await page.getByRole('button', { name: t('sourcing.item.cancel'), exact: true }).first().click();
    await typeCheck(`${lang} cancel item reason`, '#item-reason', lang === 'fa' ? 'مشتری حذف کرد' : 'Customer dropped it');
    await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();

    // --- item dialog notes --------------------------------------------------------------------------
    await page.locator(`#item-${items[2].id}`).getByRole('button', { name: t('common.edit'), exact: true }).click().catch(() => {});
    if (await page.locator('#it-notes').count()) {
      await typeCheck(`${lang} item notes`, '#it-notes', lang === 'fa' ? 'یادداشت چند کلمه‌ای' : 'A note of several words');
      await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();
    }

    // --- reject inquiry ----------------------------------------------------------------------------
    const inq = (await call('POST', '/api/inquiries', { source_channel: 'email', subject: `Inquiry ${tag}`, items: [{ name: 'Pipe' }] })).body;
    await page.goto(`${BASE}/sourcing/inquiries/${inq.id}`); await page.waitForSelector('h1');
    await page.getByRole('button', { name: t('sourcing.inquiry.reject'), exact: true }).click();
    await typeCheck(`${lang} reject inquiry reason`, '#rj-reason', lang === 'fa' ? 'خارج از حوزهٔ کاری ما' : 'Outside our scope');
    await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();

    // --- inquiry danger zone ------------------------------------------------------------------------
    await typeCheck(`${lang} inquiry danger zone`, '#cascade-confirm', `Inquiry ${tag}`);
    await shot(`${lang}-inquiry-danger-zone`);
    await page.getByRole('button', { name: t('sourcing.inquiry.cascadeButton') }).click();
    await page.waitForURL(`${BASE}/sourcing`);
    r.inquiryDeleted = (await call('GET', `/api/inquiries/${inq.id}`)).status === 404;

    // --- cancel follow-up note (party page) ---------------------------------------------------------
    await page.goto(`${BASE}/parties/${a.id}`); await page.waitForSelector('h1');
    const cancelFu = page.getByRole('button', { name: t('followups.cancel'), exact: true }).first();
    if (await cancelFu.count()) {
      await cancelFu.click();
      await typeCheck(`${lang} cancel follow-up note`, '#fu-note', lang === 'fa' ? 'دیگر لازم نیست' : 'No longer needed');
      await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();
    } else focusResults[`${lang} cancel follow-up note`] = 'not found';

    // --- delete a supplier that has RFQs: 409 with counts, no 500 (change 3) --------------------------
    await typeCheck(`${lang} party danger zone`, '#pd-purge', `Alpha Valves ${tag}`);
    await page.getByRole('button', { name: t('delete.cascadeButton') }).click();
    await page.waitForSelector('[role=alert]');
    const note = await page.locator('[role=alert]').innerText();
    r.partyInUse = note.includes(t('delete.counts.rfq_recipients')) && note.includes(t('delete.counts.offers'));
    await shot(`${lang}-party-in-use`);

    // --- template editor ----------------------------------------------------------------------------
    await page.goto(`${BASE}/sourcing/templates`); await page.waitForSelector('h1');
    await page.getByRole('button', { name: t('sourcing.templates.new'), exact: true }).click();
    await typeCheck(`${lang} template name`, '#tp-name', lang === 'fa' ? 'قالب آزمایشی' : 'Test template');
    await typeCheck(`${lang} template body`, '#tp-body', 'Dear {contact_name}, please quote');
    await checkSelects(`${lang} template editor`);
    await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();

    // --- product form ---------------------------------------------------------------------------------
    await page.goto(`${BASE}/sourcing/catalog`); await page.waitForSelector('h1');
    await checkSelects(`${lang} catalog`);
    await page.getByRole('button', { name: t('sourcing.catalog.new'), exact: true }).click();
    await typeCheck(`${lang} product name fa`, '#np-fa', 'پلی اتیلن سنگین');
    await typeCheck(`${lang} product name en`, '#np-en', 'HDPE film grade');
    await typeCheck(`${lang} product aliases`, '#np-alias', 'PE-HD');
    await checkSelects(`${lang} product form`);
    await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();

    // --- other select screens -------------------------------------------------------------------------
    for (const [path, name] of [['/sourcing', 'inquiries'], ['/cases', 'cases'], [`/cases/${kase.id}?tab=offers`, 'offers']]) {
      await page.goto(BASE + path); await page.waitForSelector('h1'); await page.waitForTimeout(300);
      await checkSelects(`${lang} ${name}`);
    }
    await page.goto(`${BASE}/cases/${kase.id}?tab=offers`);
    await page.getByRole('button', { name: t('sourcing.offer.record'), exact: true }).click();
    await page.getByRole('dialog').locator('button', { hasText: `Alpha Valves ${tag}` }).first().click();
    await page.waitForTimeout(300);
    await checkSelects(`${lang} offer form`);
    await page.getByRole('dialog').getByRole('button', { name: t('common.cancel'), exact: true }).click();

    // --- case danger zone (last: deletes the test case) ----------------------------------------------
    await page.goto(`${BASE}/cases/${kase.id}?tab=history`); await page.waitForSelector('h1');
    await typeCheck(`${lang} case danger zone`, '#cascade-confirm', kase.title);
    await shot(`${lang}-case-danger-zone`);
    await page.getByRole('button', { name: t('sourcing.case.cascadeButton') }).click();
    await page.waitForURL(`${BASE}/cases`);
    r.caseDeleted = (await call('GET', `/api/cases/${kase.id}`)).status === 404;
    r.interactionsKept = (await call('GET', `/api/interactions?party_id=${a.id}`)).body.items.length >= 2;
    results.push(r);
  }
  } catch (e) { problems.push(`CRASH: ${e.message.split('\n')[0]}`); await shot('crash'); }
  console.log(JSON.stringify({ results, focus: focusResults, selects: clip, problems }, null, 1));
  await browser.close();
})();
