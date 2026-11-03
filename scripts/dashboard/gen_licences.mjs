// `pnpm gen:licences`: DATA_LICENSES.md -> apps/dashboard/src/content/licences.json AND the package data
// read by `render_html` (ui-spec §4.7, UI9-23). The machine-readable block is the fenced JSON code block
// tagged `dashboard-licences` in DATA_LICENSES.md section 10. CI regenerates and fails on a diff.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const source = path.join(root, "DATA_LICENSES.md");
const targets = [
  path.join(root, "apps/dashboard/src/content/licences.json"),
  path.join(root, "packages/pruefstand/src/pruefstand/report/templates/_licences.json"),
];

const FIELDS = ["id", "name", "shown_here", "licence", "licence_url", "attribution", "url"];

/** Extract and check the document from the Markdown text. */
export function extractLicences(markdown) {
  const match = /```json dashboard-licences\n([\s\S]*?)\n```/.exec(markdown);
  if (match === null) throw new Error("DATA_LICENSES.md has no ```json dashboard-licences block");
  const doc = JSON.parse(match[1]);
  for (const key of ["footer_line", "odbl_offer", "sources"]) {
    if (!(key in doc)) throw new Error(`dashboard-licences block lacks "${key}"`);
  }
  for (const lang of ["de", "en"]) {
    if (typeof doc.footer_line[lang] !== "string") throw new Error(`footer_line.${lang} missing`);
  }
  for (const s of doc.sources) {
    if (JSON.stringify(Object.keys(s)) !== JSON.stringify(FIELDS)) {
      throw new Error(`source ${s.id ?? "?"}: fields must be ${FIELDS.join(", ")} in this order`);
    }
    if (/memerag/i.test(JSON.stringify(s))) throw new Error("MEMERAG is never listed (not redistributed)");
  }
  return doc;
}

export function render(doc) {
  return JSON.stringify(doc, null, 2) + "\n";
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const text = render(extractLicences(readFileSync(source, "utf8")));
  for (const target of targets) {
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, text);
  }
  console.log(`wrote ${targets.length} licence files from DATA_LICENSES.md`);
}
