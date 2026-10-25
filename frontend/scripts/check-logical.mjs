// Fails if any source file uses physical left/right Tailwind utilities instead of logical ones.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const FORBIDDEN = /(?<![\w-])(?:-?(?:ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br|scroll-ml|scroll-mr|scroll-pl|scroll-pr)-[\w[\]./%-]+|text-left|text-right|float-left|float-right|clear-left|clear-right|border-l|border-r|rounded-l|rounded-r)(?![\w-])/g;

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

let problems = 0;
for (const file of files("src")) {
  readFileSync(file, "utf-8").split("\n").forEach((line, i) => {
    for (const match of line.matchAll(/className=\{?[`"]([^`"]*)[`"]|class(?:Name)?:\s*"([^"]*)"/g)) {
      const classes = match[1] ?? match[2] ?? "";
      for (const bad of classes.matchAll(FORBIDDEN)) {
        console.error(`${file}:${i + 1}: physical direction class "${bad[0]}" - use ms/me/ps/pe/start/end`);
        problems += 1;
      }
    }
  });
}
if (problems) process.exit(1);
console.log("logical-properties check: ok");
