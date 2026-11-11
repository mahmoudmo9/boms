// v0.10.0 milestone 0 browser check (Playwright) against the dev server on 127.0.0.1:8765 (admin/admin12345), the fake
// AI provider (e2e/fake_ai_provider.py on 8799) and the stand-in Claude CLI (BOMS_CLAUDE_CLI=e2e/fake_claude_cli.py).
// No network host is contacted. For fa and en:
//  - AI settings: the Claude sign-in block (signed in -> «خروج» -> not signed in, with the numbered steps, the Windows
//    account and the storage folder); a provider at a public address is labelled «ابری», one on 127.0.0.1 «محلی»;
//  - product page: the attribute editor (template, a choice, a number with its unit, a wrong number, the live canonical
//    description in both languages, save, reload, override);
//  - item dialog: the same editor on a line item;
//  - review screen: the region of the field in focus is drawn on the PDF page, and the pasted span is marked.
// Usage: NODE_PATH=$(npm root -g) node e2e/m0-flow.cjs <out dir> src/i18n <rfq.pdf>. Prints JSON; "problems" must be empty.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const OUT = process.argv[2]; const I18N = process.argv[3]; const PDF = process.argv[4];
const BASE = 'http://127.0.0.1:8765';
const SIGNED = path.join(__dirname, '.fake_claude_signed_in');
const L = { fa: JSON.parse(fs.readFileSync(`${I18N}/fa.json`)), en: JSON.parse(fs.readFileSync(`${I18N}/en.json`)) };
const tr = (lang, key) => key.split('.').reduce((o, k) => o[k], L[lang]);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) problems.push(`console: ${m.text().slice(0, 200)}`); });
  page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
  page.on('request', (r) => { const u = r.url(); if (!u.startsWith(BASE) && !u.startsWith('data:') && !u.startsWith('blob:')) problems.push(`external: ${u}`); });
  const call = (method, p, body) => page.evaluate(async ([method, p, body]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const r = await fetch(p, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, p, body]);
  const ok = async (method, p, body) => { const r = await call(method, p, body); if (r.status >= 300) throw new Error(`${method} ${p} -> ${r.status} ${JSON.stringify(r.body).slice(0, 300)}`); return r.body; };
  const uploadPdf = (name) => page.evaluate(async ([name, b64]) => {
    const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const form = new FormData(); form.append('file', new Blob([bytes, new TextEncoder().encode(`\n% ${name}\n`)], { type: 'application/pdf' }), name);
    return (await fetch('/api/documents', { method: 'POST', headers: { 'X-CSRF-Token': tok }, body: form })).json();
  }, [name, fs.readFileSync(PDF).toString('base64')]);
  const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  const poll = async (fn, ms = 15000, every = 300) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await fn(); if (v) return v; await page.waitForTimeout(every); } return null; };
  const overflow = async (label) => { if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) problems.push(`overflow: ${label}`); };
  const results = [];
  let step = '';

  await page.goto(BASE + '/');
  await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
  await page.waitForSelector('aside');
  try {
    const providers = await ok('GET', '/api/ai/providers');
    const fake = providers.find((p) => p.kind === 'openai_compatible');
    const ollama = providers.find((p) => p.kind === 'ollama');
    await ok('PATCH', `/api/ai/providers/${fake.id}`, { base_url: 'http://127.0.0.1:8799', models: ['fake-vl'] });
    await ok('PATCH', `/api/ai/providers/${fake.id}`, { enabled: true });
    await ok('PATCH', `/api/ai/providers/${ollama.id}`, { base_url: 'https://ollama.example.com', models: ['qwen2.5'], enabled: false });   // never called
    await ok('PATCH', '/api/ai/routes/extraction', { primary_provider_id: fake.id, primary_model: 'fake-vl', fallback_provider_id: null, fallback_model: null });
    for (const lang of ['fa', 'en']) {
      const t = (k) => tr(lang, k);
      const r = { lang };
      const check = (key, cond, detail) => { r[key] = cond ? true : `FAIL ${detail ?? ''}`; if (!cond) problems.push(`${lang}: ${key} ${detail ?? ''}`); };
      results.push(r);
      await ok('PATCH', '/api/me', { language: lang, theme: lang === 'fa' ? 'light' : 'dark', calendar: lang === 'fa' ? 'jalali' : 'gregorian', digits: lang === 'fa' ? 'fa' : 'latin' });
      const tag = Math.random().toString(36).slice(2, 7);

      // ---- 1. AI settings: sign-in block and local / cloud labels ----
      step = `${lang} sign-in`;
      fs.writeFileSync(SIGNED, '1');
      await page.goto(`${BASE}/settings/ai`);
      const block = page.locator('[data-testid=claude-signin]');
      await block.waitFor();
      check('signed in state', (await block.getAttribute('data-state')) === 'signed_in', await block.getAttribute('data-state'));
      check('account and storage shown', (await page.locator('[data-testid=claude-account]').innerText()).trim().length > 0 && (await block.innerText()).includes('.claude'));
      check('no sign-in steps while signed in', (await page.locator('[data-testid=claude-steps]').count()) === 0);
      await shot(`${lang}-signin-in`);
      await page.locator('[data-testid=claude-logout]').click();
      check('signed out after «خروج»', await poll(async () => (await block.getAttribute('data-state')) === 'signed_out'));
      check('numbered steps shown', (await page.locator('[data-testid=claude-steps] li').count()) === 5);
      check('help text', (await block.innerText()).includes(t('ai.settings.claude.help')));
      check('off the PC there is no sign-in button but an explanation', (await page.locator('[data-testid=claude-login]').count()) === 0
        && (await block.innerText()).includes(t('ai.settings.claude.notOnThisPc')));
      const cards = page.locator('[data-testid=ai-provider]');
      const labelOf = async (kind) => (await cards.filter({ has: page.locator(`xpath=self::*[@data-kind="${kind}"]`) }).first().innerText());
      check('public Ollama is cloud', (await labelOf('ollama')).includes(t('ai.settings.cloud')) && (await labelOf('ollama')).includes(t('ai.settings.cloudNote')));
      check('127.0.0.1 provider is local', (await labelOf('openai_compatible')).includes(t('ai.settings.local')));
      await overflow(`${lang} ai settings`);
      await shot(`${lang}-signin-out`);

      // ---- 2. product page: the attribute editor ----
      step = `${lang} product attributes`;
      const product = (await ok('POST', '/api/products', { name_en: `Process pump ${tag}`, name_fa: `پمپ فرایندی ${tag}`, confirm_duplicate: true })).product;
      await page.goto(`${BASE}/sourcing/catalog/${product.id}`);
      const card = page.locator('[data-testid=product-description]');
      await card.waitFor();
      const templates = await ok('GET', '/api/product-templates');
      const pump = templates.find((x) => x.key === 'pump');
      await card.locator('[data-testid=attr-template]').selectOption(pump.id);
      await card.locator('[data-testid=attr-type]').selectOption('centrifugal');
      await card.locator('[data-testid=attr-standard]').fill('API 610');
      await card.locator('[data-testid=attr-flow]').fill('abc');
      check('a wrong number is refused in place', await poll(async () => (await card.innerText()).includes(t('nounmod.problem.not_a_number'))));
      check('save is blocked while invalid', await card.locator('[data-testid=product-description-save]').isDisabled());
      await card.locator('[data-testid=attr-flow]').fill(lang === 'fa' ? '۱۲۰' : '120');
      await card.locator('[data-testid=attr-head]').fill('85');
      const en = await poll(async () => { const x = await card.locator('[data-testid=attr-canonical-en]').innerText().catch(() => ''); return x.includes('120 m3/h') && x; });
      check('live canonical description (en)', en === 'PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m', en);
      const fa = await card.locator('[data-testid=attr-canonical-fa]').innerText();
      check('live canonical description (fa)', fa === 'پمپ، گریز از مرکز، API 610، ۱۲۰ مترمکعب بر ساعت، ۸۵ متر', fa);
      check('the unit of a number attribute is shown', (await card.innerText()).includes(lang === 'fa' ? 'مترمکعب بر ساعت' : 'm3/h'));
      await shot(`${lang}-product-attributes`);
      await card.locator('[data-testid=product-description-save]').click();
      const saved = await poll(async () => { const p = await ok('GET', `/api/products/${product.id}`); return p.canonical_en && p; });
      check('saved on the product', saved && saved.canonical_en === 'PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m' && saved.attributes.flow === '120', JSON.stringify(saved && saved.attributes));
      await page.reload();
      await card.waitFor();
      check('shown again after reload', await poll(async () => (await card.locator('[data-testid=attr-flow]').inputValue()) === '120'));
      await card.getByLabel(t('nounmod.override')).check();
      await card.locator('[data-testid=attr-canonical-en-input]').fill(`PUMP FOR UNIT 200 ${tag}`);
      await card.locator('[data-testid=product-description-save]').click();
      check('override kept', await poll(async () => (await ok('GET', `/api/products/${product.id}`)).canonical_en === `PUMP FOR UNIT 200 ${tag}`));
      await overflow(`${lang} product`);

      // ---- 3. item dialog: the same editor on a line item ----
      step = `${lang} item attributes`;
      const kase = await ok('POST', '/api/cases', { title: `Attributes ${tag}` });
      const item = (await ok('POST', '/api/line-items/bulk', { case_id: kase.id, items: [{ name: `Valve ${tag}`, quantity: '4', unit_code: 'pc' }] })).items[0];
      const valve = templates.find((x) => x.key === 'valve');
      await page.goto(`${BASE}/cases/${kase.id}`);
      await page.locator(`#item-${item.id} button`, { hasText: `Valve ${tag}` }).click();
      const dialog = page.locator('[data-testid=item-description]');
      await dialog.locator('summary').click();
      await dialog.locator('[data-testid=attr-template]').selectOption(valve.id);
      await dialog.locator('[data-testid=attr-type]').selectOption('gate');
      await dialog.locator('[data-testid=attr-size]').fill('6');
      check('item: live description', await poll(async () => (await dialog.locator('[data-testid=attr-canonical-en]').innerText().catch(() => '')).startsWith('VALVE, GATE, 6"')));
      await shot(`${lang}-item-attributes`);
      await page.locator('button[form=item-form]').click();
      const it = await poll(async () => { const x = await ok('GET', `/api/line-items/${item.id}`); return x.canonical_en && x; });
      check('item: saved', it && it.canonical_en.startsWith('VALVE, GATE, 6"') && it.attributes.type === 'gate', it && it.canonical_en);

      // ---- 4. review screen: the source of the field in focus ----
      step = `${lang} source highlight`;
      const doc = await uploadPdf(`rfq-${tag}.pdf`);
      const inq = await ok('POST', '/api/inquiries', { source_channel: 'email', subject: `RFQ ${tag}`, document_ids: [doc.id] });
      await page.goto(`${BASE}/sourcing/inquiries/${inq.id}`);
      await page.locator('[data-testid=ai-extract]').first().click();
      await page.locator('label', { hasText: `rfq-${tag}` }).first().click();
      await page.locator('[data-testid=ai-extract-start]').click();
      await page.locator('[data-testid=draft-review][data-status=ready]').waitFor({ timeout: 30000 });
      check('the page is shown as an image', await poll(async () => page.locator('[data-testid=draft-source] img').first().evaluate((i) => i.complete && i.naturalWidth > 0)));
      const second = page.locator('[data-testid=draft-field][data-path="items[1].name"]');
      await second.hover();
      const region = page.locator('[data-testid=source-region]');
      check('a region is drawn for the field in focus', await poll(async () => (await region.count()) >= 1));
      const image = page.locator('[data-testid=draft-source] img').first();
      const where = async () => {       // the region relative to the page image (both move when the dialog scrolls)
        const [b, i] = [await region.first().boundingBox(), await image.boundingBox()];
        return b && i ? { y: (b.y - i.y) / i.height, inside: b.x >= i.x - 1 && b.x + b.width <= i.x + i.width + 1 && b.y >= i.y - 1 && b.y + b.height <= i.y + i.height + 1 } : null;
      };
      const valveAt = await where();
      await page.locator('[data-testid=draft-field][data-path="items[0].name"]').locator('[data-testid=field-edit]').focus();     // keyboard focus counts too
      const pumpAt = await poll(async () => { const w = await where(); return w && valveAt && Math.abs(w.y - valveAt.y) > 0.005 && w; });
      check('the region follows the field in focus (pump line above the valve line)', pumpAt && pumpAt.y < valveAt.y, `${pumpAt && pumpAt.y} vs ${valveAt && valveAt.y}`);
      check('region lies inside the page image', valveAt && valveAt.inside && pumpAt && pumpAt.inside);
      check('found note', (await page.locator('[data-testid=source-found]').getAttribute('data-found')) === 'true');
      await shot(`${lang}-source-highlight`);
      await page.keyboard.press('Escape');
    }
  } catch (e) {
    problems.push(`${step}: ${e.message.split('\n')[0]}`);
    await shot('failure').catch(() => {});
  }
  fs.rmSync(SIGNED, { force: true });
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
