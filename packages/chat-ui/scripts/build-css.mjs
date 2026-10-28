// Compiles src/styles/chat-ui.css (Tailwind v4) to dist/chat-ui.css for hosts that do not run Tailwind.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/postcss";
import postcss from "postcss";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const from = resolve(root, "src/styles/chat-ui.css");
const to = resolve(root, "dist/chat-ui.css");

const result = await postcss([tailwindcss({ optimize: { minify: true } })]).process(readFileSync(from, "utf8"), { from, to });
mkdirSync(dirname(to), { recursive: true });
writeFileSync(to, result.css);
console.log(`chat-ui.css written (${(result.css.length / 1024).toFixed(1)} KB)`);
