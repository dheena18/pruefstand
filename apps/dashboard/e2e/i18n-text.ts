// i18n messages of the dashboard for the e2e specs: a message as a regex whose `{x}` placeholders match anything.
import { readFileSync } from "node:fs";
import path from "node:path";

import type { Locale } from "./checks";

const LOCALES: Locale[] = ["de", "en"];
const messages = Object.fromEntries(
  LOCALES.map((l) => [
    l,
    JSON.parse(
      readFileSync(path.join(import.meta.dirname, "..", "src", "i18n", `${l}.json`), "utf8"),
    ) as Record<string, string>,
  ]),
) as Record<Locale, Record<string, string>>;

/** i18n text as a regex: placeholders `{x}` match anything. */
export function textOf(locale: Locale, key: string): RegExp {
  const raw = messages[locale][key];
  if (raw === undefined) throw new Error(`unknown i18n key ${key}`);
  const source = raw
    .split(/\{[a-z_]+\}/)
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".+?");
  return new RegExp(source);
}
