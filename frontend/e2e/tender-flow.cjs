// v0.6.0 M4 browser check against the OFFLINE fake Setad host (no real Setad, no network), once in fa and once in en:
// star a listing -> fetch its details -> convert -> decision -> case -> Tender tab prefilled from Setad -> an addendum
// that extends the proposal deadline -> envelope items from the company documents library -> bid bond issued ->
// cost sheet -> financial proposal (summary mode) approved, PDF and Word -> submit -> result lost with a reason ->
// bid-bond release follow-up visible -> command center. Then the Tender tab, Settings -> Tenders, Settings -> Company
// documents and the guarantees list in light and dark at 1280 and 1024 px (no page overflow, no clipped selects), and
// focus kept while typing in Tender tab inputs.
// The dev server must run with BOMS_SETAD_FAKE=tests.connectors.setad.fakesite and BOMS_SETAD_HEADLESS=1.
// Usage: NODE_PATH=$(npm root -g) node e2e/tender-flow.cjs <screenshot dir> src/i18n [pdf browser path]
// Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const { execFileSync } = require('child_process');
const psql = (sql) => execFileSync('psql', ['-h', '127.0.0.1', '-U', process.env.BOMS_DB_USER || 'boms_dev',
  process.env.BOMS_DB_NAME || 'boms_dev', '-Atc', sql], { env: { ...process.env, PGPASSWORD: process.env.BOMS_DB_PASSWORD || 'devpass-local' } }).toString().trim();
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
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  // 422 below_cost on approve is an expected answer the UI handles (approve anyway with a reason)
  page.on('response', async (r) => {
    if (!r.url().includes('/api/') || r.status() < 400 || r.status() === 424) return;
    if (r.status() === 422 && r.url().includes('/approve')) return;
    problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`);
  });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const shot = async (name, full = false) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  const poll = async (fn, ms, every = 500) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(every); } return null; };
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
  // a day N days from now as typed in the user's calendar (latin digits; the input accepts both)
  const typed = (lang, days) => page.evaluate(([lang, days]) => {
    const d = new Date(Date.now() + days * 86400000);
    const parts = new Intl.DateTimeFormat(lang === 'fa' ? 'en-u-ca-persian-nu-latn' : 'en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(d);
    const get = (k) => parts.find((p) => p.type === k).value.replace(/\D/g, '');
    return `${get('year')}/${get('month')}/${get('day')}`;
  }, [lang, days]);
  const soon = (d) => new Date(Date.now() + d * 86400000).toISOString().slice(0, 10);
  const results = [];
  let step = '';

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  try {
    await call('PATCH', '/api/settings', { 'company.name_fa': 'بازرگانی نمونه', 'company.name_en': 'Sample Trading', 'company.national_id': '10320000000',
      'company.economic_code': '411111111111', 'company.signer_name': { fa: 'علی رضایی', en: 'Ali Rezaei' },
      'company.signer_title': { fa: 'مدیرعامل', en: 'CEO' }, ...(BROWSER_PATH ? { 'pdf.browser_path': BROWSER_PATH } : {}) });
    step = 'connect';
    await call('PATCH', '/api/me', { language: 'fa', theme: 'light', calendar: 'jalali', digits: 'fa' });
    await page.goto(`${BASE}/tenders`);
    const ag = (await call('GET', '/api/setad/agent')).body;
    if (!ag.alive || !ag.connected) {
      await page.getByRole('button', { name: tr('fa', 'setad.connect') }).click();
      if (!await poll(async () => (await call('GET', '/api/setad/agent')).body.connected, 90000)) throw new Error('agent did not connect');
    }
    // fetch: a full fetch of the tenders lane (one captcha pause on the fake host) unless enough tender listings exist
    step = 'fetch';
    if (Number(psql("SELECT count(*) FROM ext.listing WHERE source = 'setad_tender'")) < 2) {
      await page.locator('[data-testid=tab-setad_tender]').click();
      await page.getByRole('button', { name: tr('fa', 'setad.fullFetch') }).click();
      const done = await poll(async () => (await call('GET', '/api/setad/agent')).body.runs?.setad_tender?.status === 'done', 240000, 1000);
      if (!done) throw new Error('tender fetch did not finish');
      await page.reload();
      await shot('fa-fetched-tenders');
    }

    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      const check = (key, ok, detail) => { r[key] = ok ? true : `FAIL ${detail ?? ''}`; if (!ok) problems.push(`${lang}: ${key} ${detail ?? ''}`); };
      results.push(r);
      await page.setViewportSize({ width: 1280, height: 900 });
      await call('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });

      // company document in the library (quick-add from SetadSuite's titles, UI)
      step = `${lang} library`;
      await page.goto(`${BASE}/settings/company-documents`);
      await page.locator('[data-testid=add-doc]').waitFor();
      const quick = page.locator('button', { hasText: '+ ' }).first();
      await quick.click();
      await page.locator('[data-testid=doc-dialog]').waitFor();
      await page.locator('#cd-expires').fill(await typed(lang, 400)); await page.locator('#cd-expires').blur();
      const docTitle = await page.locator('#cd-title').inputValue();
      await page.locator('[data-testid=doc-save]').click();
      await page.locator('[data-testid=company-documents] li', { hasText: docTitle }).first().waitFor();
      await shot(`${lang}-library`);

      // 1. a listing not converted yet: star it and fetch its details in the panel
      step = `${lang} star`;
      const id = psql(`SELECT l.id FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
        WHERE l.source = 'setad_tender' AND coalesce(s.status, 'new') NOT IN ('converted', 'dismissed') ORDER BY l.external_no LIMIT 1`);
      if (!id) throw new Error('no tender listing left to convert');
      await page.goto(`${BASE}/tenders?include_old=1&deadline=any&listing=${id}`);
      const panel = page.locator('[data-testid=listing-panel]');
      await panel.waitFor();
      const star = panel.getByRole('button', { name: `★ ${t('listings.star')}` });
      if ((await call('GET', `/api/listings/${id}`)).body.screening?.status !== 'starred') { await star.click(); await panel.getByText(t('listings.status.starred')).first().waitFor(); }
      step = `${lang} detail`;
      if ((await call('GET', `/api/listings/${id}`)).body.detail === null) {
        await panel.getByRole('button', { name: t('listings.fetchDetail') }).click();
        check('detail fetched', await poll(async () => (await call('GET', `/api/listings/${id}`)).body.detail !== null, 90000));
        await page.reload(); await panel.waitFor();
      }
      const listing = (await call('GET', `/api/listings/${id}`)).body;

      // 2. convert -> inquiry -> decision -> case (a tender case is created with its Tender record)
      step = `${lang} convert`;
      await panel.getByRole('button', { name: t('listings.convert'), exact: true }).click();
      await page.locator('[data-testid=convert-dialog]').waitFor();
      const buyerSel = page.locator('#convert-buyer');
      if (await buyerSel.locator('option[value=""]').count() === 0) await buyerSel.selectOption('new');
      const without = page.getByRole('checkbox', { name: t('listings.convertWithout') });
      if (await without.count()) await without.click();
      await page.locator('[data-testid=convert-submit]').click();
      const dup = page.getByRole('checkbox', { name: t('listings.createAnyway') });
      await Promise.race([page.waitForURL(/\/sourcing\/inquiries\//, { timeout: 20000 }), dup.waitFor({ timeout: 20000 })]);
      if (!/\/sourcing\/inquiries\//.test(page.url())) { await dup.click(); await page.locator('[data-testid=convert-submit]').click(); await page.waitForURL(/\/sourcing\/inquiries\//); }
      const inquiryId = page.url().split('/').pop();
      const inq = (await call('GET', `/api/inquiries/${inquiryId}`)).body;
      step = `${lang} decision`;
      await page.getByRole('radiogroup', { name: t('sourcing.decision.light') }).getByRole('radio', { name: t('sourcing.decision.lights.green') }).click();
      await page.locator('#dc-reason').fill(lang === 'fa' ? 'تأمین داخلی ممکن است' : 'Domestic sourcing is possible');
      for (const c of ['feasible_sourcing', 'exposure_acceptable', 'requirements_ok']) {
        await page.getByRole('radiogroup', { name: t(`sourcing.decision.checks.${c}`) }).getByRole('radio', { name: t('sourcing.decision.answers.yes') }).click();
      }
      await page.getByRole('button', { name: t('sourcing.decision.save') }).click();
      step = `${lang} case`;
      await page.getByRole('button', { name: t('sourcing.convert.button') }).click();
      await page.waitForURL(/\/cases\//);
      const caseId = page.url().split('/cases/')[1].split(/[?#]/)[0];

      // 3. Tender tab prefilled from Setad
      step = `${lang} tender tab`;
      await page.goto(`${BASE}/cases/${caseId}?tab=tender`);
      await page.locator('[data-testid=tender-tab]').waitFor();
      let d = (await call('GET', `/api/cases/${caseId}/tender`)).body;
      check('tender number from Setad', d.tender_no === inq.external_no, `${d.tender_no} vs ${inq.external_no}`);
      check('dates prefilled', d.dates.length >= 1 && d.dates.every((x) => x.source === 'setad'), JSON.stringify(d.dates.map((x) => [x.kind, x.source])));
      check('envelope checklist from the template', d.envelope_items.length >= 10, String(d.envelope_items.length));
      check('stepper shown', (await page.locator('[data-testid=tender-stepper] li').count()) === 9);
      check('header facts', await page.locator('[data-testid=tender-header]').isVisible());
      const deadline = d.dates.find((x) => x.kind === 'proposal_deadline');
      check('proposal deadline with reminders', !!deadline && deadline.reminders.length >= 1, JSON.stringify(deadline?.reminders));
      const hasBond = d.guarantees.some((g) => g.purpose === 'bid');
      check('bid bond draft when Setad has an amount', !listing.guarantee_amount || hasBond, `${listing.guarantee_amount} / ${hasBond}`);
      await shot(`${lang}-tender-prefilled`);

      // focus kept while typing (participation reason, a new envelope item, the cost amount)
      step = `${lang} focus`;
      for (const sel of ['#t-reason', '[data-testid=envelope-B] input', `input[aria-label="${t('tenders.costs.amount')}"]`]) {
        const el = page.locator(sel).first();
        await el.click();
        await page.keyboard.type(sel === '#t-reason' ? 'abc def' : '12345', { delay: 30 });
        const kept = await el.evaluate((n) => document.activeElement === n);
        check(`focus kept in ${sel}`, kept);
        await el.fill('');
      }
      await page.locator('h1').first().click();

      // 4. addendum that extends the proposal deadline
      step = `${lang} addendum`;
      await page.locator('[data-testid=add-addendum]').click();
      const ad = page.locator('[data-testid=addendum-dialog]');
      await ad.waitFor();
      await page.locator('#ad-no').fill('1');
      await page.locator('#ad-sum').fill(lang === 'fa' ? 'تمدید مهلت ارسال پیشنهاد' : 'Proposal deadline extended');
      const newDay = Math.max(20, Math.ceil((new Date(deadline.at) - Date.now()) / 86400000) + 7);
      await page.locator('#ad-d-proposal_deadline').fill(await typed(lang, newDay)); await page.locator('#ad-d-proposal_deadline').blur();
      await selectClip(`${lang} addendum dialog`);
      await shot(`${lang}-addendum`);
      await page.locator('[data-testid=addendum-save]').click();
      check('addendum moved the deadline', await poll(async () => {
        const x = (await call('GET', `/api/cases/${caseId}/tender`)).body;
        const dl = x.dates.find((y) => y.kind === 'proposal_deadline');
        return x.addenda.length === 1 && dl.source === 'addendum' && new Date(dl.at) > new Date(deadline.at) && x.date_changes.length >= 1;
      }, 10000));
      await page.locator('[data-testid=tender-addenda] li').first().waitFor();

      // 5. envelope items from the library
      step = `${lang} envelopes`;
      const before = (await call('GET', `/api/cases/${caseId}/tender`)).body.envelope_progress.all[0];
      const docItem = page.locator('[data-testid=envelope-item]').filter({ has: page.getByRole('button', { name: t('tenders.library.use') }) }).first();
      const itemId = await docItem.getAttribute('data-item');
      await docItem.getByRole('button', { name: t('tenders.library.use') }).click();
      await page.locator('[data-testid=library-picker]').waitFor();
      await page.locator('[data-testid=library-picker] button', { hasText: docTitle }).first().click();
      await page.locator(`[data-item="${itemId}"]`, { hasText: docTitle }).waitFor();
      check('library document attached', await poll(async () => (await call('GET', `/api/cases/${caseId}/tender`)).body.envelope_items.some((i) => i.company_document?.title === docTitle), 10000));
      await page.locator(`[data-item="${itemId}"] select`).selectOption('ready');
      check('item ready', await poll(async () => (await call('GET', `/api/cases/${caseId}/tender`)).body.envelope_progress.all[0] === before + 1, 10000));
      await shot(`${lang}-envelopes`);

      // a date added in the date/reminder editor: the opening, with reminders typed in Persian digits / commas
      step = `${lang} opening date`;
      await page.getByRole('button', { name: t('tenders.dates.add') }).click();
      await page.locator('[data-testid=date-editor]').waitFor();
      await page.locator('#td-kind').selectOption('opening');
      await page.locator('#td-day').fill(await typed(lang, newDay + 2)); await page.locator('#td-day').blur();
      await page.locator('#td-time').fill('10:00');
      await page.locator('#td-days').fill('x');
      check('invalid reminder days block saving', await page.locator('[data-testid=date-save]').isDisabled());
      await page.locator('#td-days').fill(lang === 'fa' ? '۲، ۱' : '2, 1');
      await selectClip(`${lang} date editor`);
      await shot(`${lang}-date-editor`);
      await page.locator('[data-testid=date-save]').click();
      check('opening date with reminders', await poll(async () => {
        const o = (await call('GET', `/api/cases/${caseId}/tender`)).body.dates.find((x) => x.kind === 'opening');
        return o && o.source === 'manual' && JSON.stringify(o.remind_days_before) === '[2,1]' && o.reminders.length === 2;
      }, 10000));

      // 6. bid bond issued (create one when Setad had no amount)
      step = `${lang} bid bond`;
      if (!hasBond) {
        await page.locator('[data-testid=add-guarantee]').click();
        await page.locator('#g-amount').fill('250000000');
        await page.getByRole('dialog').getByRole('button', { name: t('common.save') }).click();
        await page.locator('[data-testid=guarantees] li').first().waitFor();
      }
      const bond = page.locator('[data-testid=guarantees] li').first();
      await bond.getByRole('button', { name: t('tenders.guarantee.steps.issued'), exact: true }).click();
      await page.locator('[data-testid=status-dialog]').waitFor();
      await page.locator('#gs-valid').fill(await typed(lang, newDay + 120)); await page.locator('#gs-valid').blur();
      await page.locator('[data-testid=status-save]').click();
      check('bid bond issued', await poll(async () => (await call('GET', `/api/cases/${caseId}/tender`)).body.bid_bond?.status === 'issued', 10000));
      d = (await call('GET', `/api/cases/${caseId}/tender`)).body;
      const bid = d.guarantees.find((g) => g.purpose === 'bid');
      check('guarantee expiry reminders', bid.reminders.some((x) => x.purpose === 'guarantee_expiry'), JSON.stringify(bid.reminders));
      check('bid-bond envelope item follows the bond', d.envelope_items.filter((i) => i.kind === 'bid_bond').every((i) => i.status === 'ready' && i.guarantee_id === bid.id),
        JSON.stringify(d.envelope_items.filter((i) => i.kind === 'bid_bond').map((i) => [i.status, i.guarantee_id])));
      await page.reload(); await page.locator('[data-testid=tender-tab]').waitFor();
      await shot(`${lang}-bond`);

      // 7. cost sheet (offers by API: the RFQ flow is Phase 5), finalized in the UI
      step = `${lang} offers`;
      const items = (await call('GET', `/api/cases/${caseId}`)).body.items;
      const sup = (await call('POST', '/api/parties', { confirm_duplicate: true, name_fa: `تأمین‌کننده ${Date.now() % 100000}`, roles: ['supplier'], country_iso2: 'IR' })).body.party;
      const offer = (await call('POST', '/api/offers', { case_id: caseId, party_id: sup.id, channel: 'phone', currency: 'IRR', valid_until: soon(200),
        no_followup_reason: 'browser check', items: items.map((i) => ({ line_item_id: i.id, unit_price: '15000000' })) })).body;
      for (const [i, it] of items.entries()) await call('POST', `/api/line-items/${it.id}/select`, { offer_item_id: offer.items[i].id });
      step = `${lang} cost sheet`;
      const sheet = (await call('POST', '/api/cost-sheets', { case_id: caseId, deal_type: 'domestic', pricing_currency: 'IRR' })).body;
      await call('POST', `/api/cost-sheets/${sheet.id}/lines/not-applicable`);
      await call('PATCH', `/api/cost-sheets/${sheet.id}`, { pricing_method: 'margin', target_percent: '20' });
      // a tender cost in the costs card, then the costs onto the draft sheet (Tender tab button)
      await page.locator('[data-testid=tender-tab] select[aria-label="' + t('tenders.costs.kind') + '"]').selectOption('travel');
      await page.getByRole('textbox', { name: t('tenders.costs.amount') }).fill('3500000');
      await page.locator('[data-testid=cost-totals]').locator('..').getByRole('button', { name: t('common.add'), exact: true }).click();
      check('cost added', await poll(async () => (await call('GET', `/api/cases/${caseId}/tender`)).body.costs.some((c) => c.kind === 'travel'), 10000));
      await page.locator('[data-testid=costs-to-sheet]').click();
      await page.getByText(t('tenders.costs.added')).waitFor();
      await page.goto(`${BASE}/cases/${caseId}?tab=costing`);
      await page.locator('[data-sheet]').waitFor();
      await page.getByRole('button', { name: t('costing.finalize'), exact: true }).click();
      await page.getByRole('dialog').getByRole('button', { name: t('costing.finalize'), exact: true }).click();
      await page.getByText(t('costing.readOnly')).waitFor();

      // 8. financial proposal (summary / buyer form mode) approved; PDF and Word
      step = `${lang} proposal`;
      await page.goto(`${BASE}/cases/${caseId}?tab=tender`);
      await page.locator('[data-testid=new-proposal]').click();
      const prop = page.locator('[data-testid=proposal]');
      await prop.waitFor();
      await page.locator('[data-testid=approve-proposal]').click();
      const anyway = page.getByRole('button', { name: t('tenders.proposal.approveAnyway') });
      await Promise.race([prop.getByText(t('tenders.proposal.statuses.approved')).waitFor(), anyway.waitFor()]);
      if (await anyway.isVisible().catch(() => false)) {
        await page.getByRole('textbox', { name: t('tenders.proposal.reason') }).fill('browser check');
        await anyway.click();
        await prop.getByText(t('tenders.proposal.statuses.approved')).waitFor();
      }
      d = (await call('GET', `/api/cases/${caseId}/tender`)).body;
      const p = d.proposals.find((x) => x.status === 'approved');
      check('proposal approved', !!p);
      const html = await (await page.request.get(`${BASE}/api/tender-proposals/${p.id}/print`)).text();
      check('proposal print: number, words, signer', [inq.external_no, p.words, 'علی رضایی'].every((s) => html.includes(s)));
      for (const fmt of ['PDF', 'Word']) {
        step = `${lang} output ${fmt}`;
        const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 90000 }), prop.getByRole('button', { name: fmt, exact: true }).click()]);
        const name = dl.suggestedFilename();
        check(`${fmt} file name`, name.includes(inq.external_no) && name.includes('proposal-v') && !name.includes('DRAFT'), name);
        await dl.saveAs(`${OUT}/${lang}-${name}`);
        const head = fs.readFileSync(`${OUT}/${lang}-${name}`).subarray(0, 4).toString('latin1');
        check(`${fmt} file content`, fmt === 'PDF' ? head === '%PDF' : head.startsWith('PK'), head);
        r[`${fmt}_file`] = name;
      }
      await page.goto(`${BASE}/cases/${caseId}?tab=tender`);
      await page.locator('[data-testid=tender-tab]').waitFor();
      await shot(`${lang}-proposal`);

      // 9. submit (blockers listed; the remaining items need an override reason) -> result lost with reason
      step = `${lang} submit`;
      const blockers = page.locator('[data-testid=blockers] li');
      check('blockers listed', (await blockers.count()) >= 1);
      await shot(`${lang}-blockers`);
      d = (await call('GET', `/api/cases/${caseId}/tender`)).body;
      if (d.blockers.length) await page.getByRole('textbox', { name: t('tenders.submit.override') }).fill(lang === 'fa' ? 'باقی موارد در ستاد بارگذاری شد' : 'The rest was uploaded in Setad');
      await page.locator('[data-testid=mark-submitted]').click();
      check('submitted', await poll(async () => !!(await call('GET', `/api/cases/${caseId}/tender`)).body.submitted_at, 10000));
      d = (await call('GET', `/api/cases/${caseId}/tender`)).body;
      check('opening follow-up', d.other_reminders.some((x) => x.purpose === 'opening'), JSON.stringify(d.other_reminders));
      step = `${lang} result`;
      await page.locator('#tr-result').selectOption('lost');
      await page.locator('#tr-reason').selectOption({ index: 1 });
      await page.locator('#tr-winner').fill(lang === 'fa' ? 'شرکت رقیب' : 'Rival Co');
      await page.locator('#tr-price').fill('900000000');
      await page.locator('[data-testid=save-result]').click();
      check('result lost', await poll(async () => (await call('GET', `/api/cases/${caseId}/tender`)).body.result === 'lost', 10000));
      await page.locator('[data-testid=release-followup]').first().waitFor();
      check('bid-bond release follow-up visible', await page.locator('[data-testid=release-followup]').first().isVisible());
      const cs = (await call('GET', `/api/cases/${caseId}`)).body;
      check('case lost', cs.status === 'lost', cs.status);
      await shot(`${lang}-result`, true);

      // 10. command center
      step = `${lang} command center`;
      await page.goto(`${BASE}/command-center`);
      const cc = page.locator('[data-testid=cc-tenders]');
      await cc.waitFor();
      await cc.scrollIntoViewIfNeeded();
      check('cc tenders section', (await cc.innerText()).includes(t('cc.tenders.title')));
      await shot(`${lang}-cc`);

      // 11. layout: light/dark at 1280 and 1024 px
      for (const theme of ['light', 'dark']) {
        await call('PATCH', '/api/me', { theme });
        for (const width of [1280, 1024]) {
          await page.setViewportSize({ width, height: 900 });
          for (const [name, path, ready] of [['tender', `/cases/${caseId}?tab=tender`, '[data-testid=tender-tab]'], ['tender-settings', '/settings/tenders', '[data-testid=reason-rows]'],
            ['company-docs', '/settings/company-documents', '[data-testid=company-documents]'], ['guarantees', '/cases/guarantees', '[data-testid=guarantee-list]']]) {
            step = `${lang} ${theme} ${width} ${name}`;
            await page.goto(BASE + path);
            await page.locator(ready).first().waitFor();
            await page.waitForLoadState('networkidle');
            await overflow(step); await selectClip(step);
            if (name === 'tender') {
              const narrow = await page.evaluate(() => [...document.querySelectorAll('[data-testid=envelope-item] > span:first-child')].filter((e) => e.getBoundingClientRect().width < 200).length);
              if (narrow) problems.push(`${step}: ${narrow} envelope item titles narrower than 200px`);
            }
            await shot(`${lang}-${theme}-${width}-${name}`, name === 'tender');
          }
        }
      }
      await call('PATCH', '/api/me', { theme: 'light' });
    }
    step = 'disconnect';
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${BASE}/tenders`);
    await page.getByRole('button', { name: tr('en', 'setad.disconnect') }).click();
    await poll(async () => !(await call('GET', '/api/setad/agent')).body.connected, 30000);
  } catch (e) {
    problems.push(`exception at ${step}: ${e.message.split('\n')[0]}`);
    await shot('exception', true);
  }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
