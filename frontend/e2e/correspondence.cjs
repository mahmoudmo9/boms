// v0.10.1 (0.4.6) browser check: case correspondence. On an RFQ recipient that was sent with a chase follow-up:
// drop the supplier's reply saved as .eml -> it is read (subject, text) -> «پاسخ بدون قیمت» (replied) -> the reply is
// on the case with its .eml, the recipient is «replied» and the open chase is done. On a second recipient:
// «پیگیری» -> write the chase -> the mailto -> «ارسال شد» -> the chase is on the case, counted on the recipient, and
// the follow-up is rescheduled. A .msg is refused with the steps. Then the «مکاتبات» tab lists them. In fa and en.
// Usage: NODE_PATH=$(npm root -g) node e2e/correspondence.cjs <out dir> src/i18n. Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);
const eml = (from, subject, body) => Buffer.from([`From: Wang Lei <${from}>`, 'To: owner@trading.example', `Subject: ${subject}`,
  'Date: Fri, 20 Nov 2026 09:30:00 +0000', 'MIME-Version: 1.0', 'Content-Type: text/plain; charset=utf-8', '', body, ''].join('\r\n'));
(async () => {
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  const problems = []; const results = [];
  const expected = ['415 POST /api/interactions/eml/preview'];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => { if (!r.url().includes('/api/') || r.status() < 400) return; const k = `${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`;
    if (!expected.includes(k)) problems.push(k); });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const ok = async (m, p, b) => { const r = await call(m, p, b); if (r.status >= 300) throw new Error(`${m} ${p} -> ${r.status} ${JSON.stringify(r.body).slice(0, 200)}`); return r.body; };
  const poll = async (fn, ms = 10000) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(300); } return null; };
  let step = 'login';
  try {
    await page.goto(BASE + '/'); await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
    await page.waitForSelector('aside');
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang }; results.push(r);
      const check = (k, c, d) => { r[k] = c ? true : `FAIL ${d ?? ''}`; if (!c) problems.push(`${lang}: ${k} ${d ?? ''}`); };
      await ok('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);
      step = `${lang} data`;
      const mk = async (name) => {
        const p = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `${name} ${tag}`, roles: ['supplier'], country_iso2: 'CN' })).party;
        const address = `${name.toLowerCase()}${tag}@valves.example`;
        const c = await ok('POST', '/api/contacts', { party_id: p.id, name_en: 'Wang Lei', methods: [{ type: 'email', value: address }] });
        return { ...p, address, contact: c };
      };
      const a = await mk('Alpha'); const b = await mk('Beta');
      const kase = await ok('POST', '/api/cases', { title: `Mail ${tag}` });
      const items = (await ok('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: 'Ball valve', quantity: '4' }] })).items;
      const rfq = await ok('POST', '/api/rfqs', { case_id: kase.id, items: items.map((i) => ({ line_item_id: i.id })),
        recipients: [{ party_id: a.id, channel: 'email', contact_id: a.contact.id }, { party_id: b.id, channel: 'email', contact_id: b.contact.id }] });
      for (const rec of rfq.recipients) await ok('POST', `/api/rfqs/recipients/${rec.id}/mark-sent`, { followup: { action: 'Chase RFQ response', due_on: '2099-01-05' } });
      const openChases = async (pid) => (await ok('GET', `/api/followups?party_id=${pid}&status=open`)).items.length;
      check('chase open after sending', (await openChases(a.id)) === 1);
      await page.goto(`${BASE}/cases/${kase.id}?tab=rfqs&rfq=${rfq.id}`);
      const rowA = page.locator(`[data-recipient="${rfq.recipients[0].id}"]`);
      const rowB = page.locator(`[data-recipient="${rfq.recipients[1].id}"]`);

      step = `${lang} msg refused`;
      await rowA.getByTestId('reply-no-price').click();
      const dialog = page.getByTestId('reply-dialog');
      await dialog.locator('[data-testid=reply-eml] input[type=file]').setInputFiles({ name: 'reply.msg', mimeType: 'application/vnd.ms-outlook',
        buffer: Buffer.concat([Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]), Buffer.from(tag + 'x'.repeat(600))]) });
      check('.msg refused with the steps', Boolean(await poll(async () => (await page.getByTestId('msg-refused').count()) > 0)));

      step = `${lang} reply from .eml`;
      await dialog.locator('[data-testid=reply-eml] input[type=file]').setInputFiles({ name: 'reply.eml', mimeType: 'message/rfc822',
        buffer: eml(a.address, `Re: [${rfq.code}] Request for Quotation`, `We are checking with the factory. ${tag}`) });
      check('the .eml text fills the reply', Boolean(await poll(async () => (await dialog.locator('#reply-text').inputValue()).includes('checking with the factory'))));
      await page.screenshot({ path: `${OUT}/${lang}-reply-dialog.png` });
      await dialog.getByRole('radio', { name: t('rfqReply.kinds.replied'), exact: true }).click();
      await page.getByTestId('reply-save').click();
      await dialog.waitFor({ state: 'detached' });
      const recA = await poll(async () => { const x = (await ok('GET', `/api/rfqs/${rfq.id}`)).recipients.find((y) => y.id === rfq.recipients[0].id); return x.status === 'replied' ? x : null; });
      check('recipient replied', Boolean(recA));
      check('the chase closed', (await openChases(a.id)) === 0);
      const thread = await ok('GET', `/api/interactions/case/${kase.id}`);
      const reply = thread.items.find((i) => i.direction === 'in' && i.party_id === a.id);
      check('reply on the case with its .eml', Boolean(reply && reply.raw_document_id && reply.ref_code === rfq.code), JSON.stringify(reply ?? {}).slice(0, 160));

      step = `${lang} chase`;
      await rowB.getByTestId('chase-open').click();
      const chase = page.getByTestId('chase-dialog');
      await chase.getByTestId('chase-body').fill(lang === 'fa' ? 'آیا قیمت آماده است؟' : 'Is the price ready?');
      const href = await chase.getByTestId('chase-mailto').getAttribute('href');
      check('mailto to the recipient with the text', href.startsWith(`mailto:${b.address}?`) && decodeURIComponent(href).includes(lang === 'fa' ? 'قیمت آماده' : 'price ready'), href);
      await chase.getByRole('button', { name: t('followups.quick.week'), exact: true }).click();
      await page.screenshot({ path: `${OUT}/${lang}-chase-dialog.png` });
      await page.getByTestId('chase-sent').click();
      await chase.waitFor({ state: 'detached' });
      check('chase counted on the recipient', Boolean(await poll(async () => (await rowB.getByTestId('chase-count').count()) > 0)));
      const open = (await ok('GET', `/api/followups?party_id=${b.id}&status=open`)).items;
      check('follow-up rescheduled, not added', open.length === 1 && open[0].due_on !== '2099-01-05', JSON.stringify(open.map((x) => x.due_on)));

      step = `${lang} thread tab`;
      await page.goto(`${BASE}/cases/${kase.id}?tab=correspondence`);
      await page.getByTestId('thread-list').waitFor();
      const n = await page.getByTestId('thread-item').count();
      check('thread lists sent RFQs, the reply and the chase', n === 4, String(n));
      await page.screenshot({ path: `${OUT}/${lang}-thread.png`, fullPage: true });
    }
  } catch (e) { problems.push(`CRASH at ${step}: ${e.message.split('\n')[0]}`); await page.screenshot({ path: `${OUT}/crash.png` }).catch(() => {}); }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
