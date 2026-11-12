// The design-system lint (v0.10.0 section 1.1). Fails the build when a file under src/ holds
//   1. a physical left/right Tailwind utility instead of a logical one (ms/me/ps/pe/start/end);
//   2. a colour literal (#hex, rgb(), hsl(), a named Tailwind palette colour);
//   3. a pixel font size (text-[13px], font-size: 13px, fontSize: 13);
//   4. an arbitrary spacing value (p-[13px], gap-[0.4rem], m-[5vh] ...).
// The only file that may hold such values is src/design/tokens.css. Print and output templates are rendered by the
// backend and are not under src/. Tests are skipped (they assert values, they do not style anything).
// Usage: node scripts/check-design.mjs [dir]   (default: src). Exported for the test.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, sep } from "node:path";
import { fileURLToPath } from "node:url";

const PHYSICAL = /(?<![\w-])(?:-?(?:ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br|scroll-ml|scroll-mr|scroll-pl|scroll-pr)-[\w[\]./%-]+|text-left|text-right|float-left|float-right|clear-left|clear-right|border-l|border-r|rounded-l|rounded-r)(?![\w-])/g;
const PALETTE = "black|white|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone";
const RULES = [
  { id: "colour literal", re: /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])/g, skip: (line, m) => /(?:href|to|id|htmlFor|url\()=?["'`(]?[^"'`]*$/.test(line.slice(0, m.index)) || /&$/.test(line.slice(0, m.index)) },
  { id: "colour literal", re: /\b(?:rgba?|hsla?|oklch|oklab|color-mix)\(/g },
  { id: "colour literal", re: new RegExp(`(?<![\\w-])(?:bg|text|border|ring|outline|fill|stroke|from|via|to|shadow|divide|decoration|accent|caret)-(?:${PALETTE})(?:-\\d{2,3})?(?:/\\d+)?(?![\\w-])`, "g") },
  { id: "pixel font size", re: /(?<![\w-])text-\[[^\]]*\d(?:px|pt|rem|em)\]/g },
  { id: "pixel font size", re: /font-size\s*:\s*[\d.]+(?:px|pt)/g },
  { id: "pixel font size", re: /fontSize\s*[:=]\s*\{?\s*["'`]?[\d.]+(?:px|pt)?["'`]?\s*[,}\n]/g },
  { id: "arbitrary spacing", re: /(?<![\w-])-?(?:p|m|gap|space|inset|top|bottom|start|end|scroll-m|scroll-p)(?:[xytbse]|-[xy])?-\[[^\]]+\]/g },
];

export function checkText(text, file = "") {
  const out = [];
  text.split("\n").forEach((line, i) => {
    if (/design-lint-ignore/.test(line)) return;
    for (const match of line.matchAll(/className=\{?[`"]([^`"]*)[`"]|class(?:Name)?:\s*"([^"]*)"/g)) {
      for (const bad of (match[1] ?? match[2] ?? "").matchAll(PHYSICAL)) {
        out.push({ file, line: i + 1, rule: "physical direction", text: bad[0], hint: "use ms/me/ps/pe/start/end" });
      }
    }
    for (const rule of RULES) {
      for (const m of line.matchAll(rule.re)) {
        if (rule.skip?.(line, m)) continue;
        out.push({ file, line: i + 1, rule: rule.id, text: m[0].trim(), hint: "use a token (src/design/tokens.css)" });
      }
    }
  });
  return out;
}

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

export function checkDir(dir) {
  const allowed = join("design", "tokens.css");
  return files(dir)
    .filter((f) => !f.endsWith(allowed) && !/\.test\.tsx?$/.test(f) && !f.split(sep).includes("i18n"))
    .flatMap((f) => checkText(readFileSync(f, "utf-8"), f));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const problems = checkDir(process.argv[2] ?? "src");
  for (const p of problems) console.error(`${p.file}:${p.line}: ${p.rule} "${p.text}" - ${p.hint}`);
  if (problems.length) process.exit(1);
  console.log("design lint: ok (logical properties, no colour literal, no pixel font size, no arbitrary spacing)");
}
