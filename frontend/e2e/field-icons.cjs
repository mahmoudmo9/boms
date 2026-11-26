// v0.10.1 (0.4.4) browser check: a field's icons never cover its value. For every field the library marks with
// data-icons (Select, Combobox, LookupField, ValidatedInput, and the country and phone fields built on them) the box of
// each icon (chevron, clear ×, search, state, leading flag) must not intersect the text box of the input (its border
// box minus its padding). Run in fa and en, at the field's own width and at the smallest width the library allows it (its min-width),
// with one icon (no value) and two (a value with the clear button).
// Usage: NODE_PATH=$(npm root -g) node e2e/field-icons.cjs <out dir>
const { chromium } = require('playwright');
const OUT = process.argv[2];
const BASE = process.env.BOMS_CHECK_BASE || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = []; const results = {};
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  const measure = () => page.evaluate(() => {
    const out = [];
    for (const wrap of document.querySelectorAll('[data-icons]')) {
      const field = wrap.querySelector('input, select');
      if (!field || field.offsetParent === null) continue;
      const r = field.getBoundingClientRect(); const cs = getComputedStyle(field);
      const text = { left: r.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth), right: r.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth) };
      if (text.right - text.left < 24) out.push({ field: field.id || field.tagName, icon: 'no room for text', icons: 0, textBox: [Math.round(text.left), Math.round(text.right)], iconBox: [] });
      const marks = [...wrap.querySelectorAll('svg, button, img, [data-slot=leading]')].filter((n) => !field.contains(n) && !n.closest('[role=listbox]') && n.getClientRects().length);
      const icons = marks.length;
      for (const m of marks) {
        const b = m.getBoundingClientRect();
        if (b.width === 0) continue;
        if (b.right > text.left + 0.5 && b.left < text.right - 0.5) out.push({ field: field.id || field.getAttribute('aria-label') || field.tagName, icon: m.tagName.toLowerCase(), icons, textBox: [Math.round(text.left), Math.round(text.right)], iconBox: [Math.round(b.left), Math.round(b.right)] });
      }
    }
    return { overlaps: out, fields: document.querySelectorAll('[data-icons]').length };
  });
  try {
    await page.goto(BASE + '/'); await page.fill('#username', 'admin'); await page.fill('#password', 'admin12345'); await page.click('button[type=submit]');
    await page.waitForSelector('aside');
    await page.evaluate(() => localStorage.setItem('boms.dev', '1'));   // /design is the developer catalogue
    for (const lang of ['fa', 'en']) {
      await page.evaluate(async (language) => { const tok = document.cookie.match(/boms_csrf=([^;]+)/)[1];
        await fetch('/api/me', { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': tok }, body: JSON.stringify({ language }) }); }, lang);
      await page.goto(BASE + '/design'); await page.waitForTimeout(1500);
      for (const size of ['own', 'smallest']) {
        // the smallest size the library lets a field have: width 0, held by the field's own min-width
        if (size === 'smallest') await page.addStyleTag({ content: '[data-icons]{width:0!important;flex:none!important}' });
        await page.waitForTimeout(300);
        const m = await measure();
        results[`${lang} ${size}`] = { fields: m.fields, overlaps: m.overlaps.length };
        for (const o of m.overlaps) problems.push(`${lang} ${size}: ${o.icon} over ${o.field} (icons ${o.icons}) text ${o.textBox} icon ${o.iconBox}`);
        await page.locator('[data-testid=ds-forms], h2:has-text("Combobox"), #ds-cb').first().scrollIntoViewIfNeeded().catch(() => {});
        await page.screenshot({ path: `${OUT}/field-icons-${lang}-${size}.png`, fullPage: true });
        if (size === 'smallest') await page.reload();
      }
      // one icon and two: the combobox with a value shows the clear button, without one only the chevron
      await page.waitForTimeout(800);
      const cb = page.locator('input#ds-cb').first();
      const two = await measure();
      await cb.fill(''); await page.keyboard.press('Escape');
      const clear = page.locator('input#ds-cb ~ [data-slot=icons] button').first();
      if (await clear.count()) await clear.dispatchEvent('mousedown');
      await page.waitForTimeout(200);
      const one = await measure();
      results[`${lang} combobox two icons / one icon`] = [two.overlaps.length, one.overlaps.length];
      for (const o of [...two.overlaps, ...one.overlaps]) problems.push(`${lang} value toggle: ${o.icon} over ${o.field}`);
    }
  } catch (e) { problems.push(`CRASH: ${e.message.split('\n')[0]}`); await page.screenshot({ path: `${OUT}/crash.png` }).catch(() => {}); }
  console.log(JSON.stringify({ results, problems }, null, 1));
  await browser.close();
})();
