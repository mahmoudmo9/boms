// v0.10.1 (0.4.1) browser check, with the fake AI provider of e2e/fake_ai_provider.py on 127.0.0.1:8799 (no network):
// on an RFQ recipient, «پیش‌نویس با هوش» with an instruction and a preset chip -> the draft (the fake echoes the
// instruction) -> «ساخت دوباره» keeps the first draft -> «انتخاب این متن» -> the recipient's subject keeps «[CODE]», its
// editor and the mailto link hold the chosen text. Then the owner edits the text, drafts again and chooses «افزودن به
// انتها»: his text stays and the draft follows it. In fa and en.
// Usage: NODE_PATH=$(npm root -g) node e2e/ai-compose.cjs <out dir> src/i18n. Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const I18N = process.argv[3];
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);
(async () => {
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  const problems = []; const results = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, path, body]);
  const ok = async (m, p, b) => { const r = await call(m, p, b); if (r.status >= 300) throw new Error(`${m} ${p} -> ${r.status} ${JSON.stringify(r.body).slice(0, 200)}`); return r.body; };
  const poll = async (fn, ms = 15000) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(300); } return null; };
  let step = 'login';
  try {
    await page.goto(BASE + '/'); await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
    await page.waitForSelector('aside');
    step = 'provider';
    const fake = (await ok('GET', '/api/ai/providers')).find((p) => p.kind === 'openai_compatible');
    await ok('PATCH', `/api/ai/providers/${fake.id}`, { base_url: 'http://127.0.0.1:8799', models: ['fake-vl'] });
    await ok('PATCH', `/api/ai/providers/${fake.id}`, { enabled: true });
    await ok('PATCH', '/api/ai/routes/drafting', { primary_provider_id: fake.id, primary_model: 'fake-vl', fallback_provider_id: null, fallback_model: null });
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang }; results.push(r);
      const check = (k, c, d) => { r[k] = c ? true : `FAIL ${d ?? ''}`; if (!c) problems.push(`${lang}: ${k} ${d ?? ''}`); };
      await ok('PATCH', '/api/me', { language: lang, theme: 'light', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);
      step = `${lang} data`;
      const sup = (await ok('POST', '/api/parties', { confirm_duplicate: true, name_en: `Compose Valves ${tag}`, roles: ['supplier'], country_iso2: 'CN' })).party;
      await ok('POST', '/api/contacts', { party_id: sup.id, name_en: 'Wang Lei', methods: [{ type: 'email', value: `c${tag}@valves.example` }] });
      const kase = await ok('POST', '/api/cases', { title: `Compose ${tag}` });
      const items = (await ok('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: 'Ball valve DN50', quantity: '4' }] })).items;
      const rfq = await ok('POST', '/api/rfqs', { case_id: kase.id, items: items.map((i) => ({ line_item_id: i.id })), recipients: [{ party_id: sup.id, channel: 'email' }] });
      step = `${lang} compose`;
      await page.goto(`${BASE}/cases/${kase.id}?tab=rfqs&rfq=${rfq.id}`);
      const row = page.locator(`[data-recipient="${rfq.recipients[0].id}"]`);
      await row.getByTestId('ai-draft-message').click();
      const drawer = page.getByTestId('draft-composer');
      await drawer.waitFor();
      const instruction = lang === 'fa' ? 'زمان تحویل و MOQ را هم بپرس' : 'also ask lead time and MOQ';
      await drawer.getByTestId('ai-instruction').fill(instruction);
      await drawer.getByTestId('ai-presets').getByRole('button', { name: t('ai.compose.presets.tone.formal'), exact: true }).click();
      const full = await drawer.getByTestId('ai-instruction').inputValue();
      check('preset extends the instruction', full === `${instruction}، ${t('ai.compose.presets.tone.formal')}`, full);
      await drawer.getByTestId('ai-draft-start').click();
      check('first draft ready', await poll(async () => (await drawer.locator('[data-testid=ai-draft][data-status=ready]').count()) === 1));
      check('the instruction reached the model', (await drawer.getByTestId('ai-draft-body').first().innerText()).includes(`[instruction: ${full}]`));
      await drawer.getByTestId('ai-instruction').fill('');
      await drawer.getByTestId('ai-draft-start').click();                                       // «ساخت دوباره»
      check('regenerate keeps the earlier draft', await poll(async () => (await drawer.locator('[data-testid=ai-draft][data-status=ready]').count()) === 2));
      await page.screenshot({ path: `${OUT}/${lang}-composer.png` });
      step = `${lang} choose`;
      await drawer.locator('[data-testid=ai-draft]').last().getByTestId('ai-draft-choose').click();   // the first draft, with the instruction
      await drawer.waitFor({ state: 'detached' });
      const body = await row.getByRole('textbox', { name: t('sourcing.rfq.message') }).inputValue();
      const subject = await row.getByRole('textbox', { name: t('sourcing.rfq.subject') }).inputValue();
      check('editor holds the chosen body', body.startsWith('Dear Sir or Madam') && body.includes('[instruction:'), body.slice(0, 80));
      check('subject keeps the code', subject === `[${rfq.code}] Request for Quotation`, subject);
      const href = await poll(async () => { const a = row.locator('a[href^="mailto:"]'); return (await a.count()) ? a.getAttribute('href') : null; });
      check('mailto holds the chosen text', Boolean(href) && decodeURIComponent(href).includes('Please quote the items below.'), href);
      await page.screenshot({ path: `${OUT}/${lang}-chosen.png` });
      step = `${lang} append`;
      const box = row.getByRole('textbox', { name: t('sourcing.rfq.message') });
      await box.fill('My own opening line.');
      await row.getByTestId('ai-draft-message').click();
      await drawer.waitFor();
      await drawer.getByTestId('ai-draft-start').click();
      await poll(async () => (await drawer.locator('[data-testid=ai-draft][data-status=ready]').count()) >= 2);
      await drawer.locator('[data-testid=ai-draft][data-status=ready]').first().getByTestId('ai-draft-choose').click();
      await page.getByTestId('ai-append').click();
      await drawer.waitFor({ state: 'detached' });
      const appended = await box.inputValue();
      check('append keeps the owner text first', appended.startsWith('My own opening line.\n\nDear Sir or Madam'), appended.slice(0, 80));
      const stored = (await ok('GET', `/api/rfqs/${rfq.id}`)).recipients[0];
      check('stored text matches the editor', stored.message_text === appended);
    }
  } catch (e) { problems.push(`CRASH at ${step}: ${e.message.split('\n')[0]}`); await page.screenshot({ path: `${OUT}/crash.png` }).catch(() => {}); }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
