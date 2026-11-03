import de from "@/i18n/de.json";
import en from "@/i18n/en.json";

/** Locales of the route prefix; `de` is the default (ui-spec §10.1). */
export const LOCALES = ["de", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export type Params = Record<string, string | number>;

const DICTIONARIES: Record<Locale, Record<string, string>> = { de, en };

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

export function otherLocale(locale: Locale): Locale {
  return locale === "de" ? "en" : "de";
}

/** Index of the `}` that closes the `{` at `open`, or -1. */
function closing(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i += 1) {
    if (text[i] === "{") depth += 1;
    else if (text[i] === "}" && (depth -= 1) === 0) return i;
  }
  return -1;
}

/** The `one {…} other {…}` options of a plural block, by selector. */
function pluralOptions(body: string): Record<string, string> {
  const options: Record<string, string> = {};
  let i = 0;
  while (i < body.length) {
    const open = body.indexOf("{", i);
    if (open < 0) break;
    const end = closing(body, open);
    if (end < 0) break;
    options[body.slice(i, open).trim()] = body.slice(open + 1, end);
    i = end + 1;
  }
  return options;
}

function expand(block: string, params: Params, locale: Locale): string {
  const comma = block.indexOf(",");
  if (comma < 0) return String(params[block.trim()] ?? `{${block}}`);
  const name = block.slice(0, comma).trim();
  const rest = block.slice(comma + 1).trim();
  if (!rest.startsWith("plural,")) return `{${block}}`;
  const count = Number(params[name] ?? 0);
  const options = pluralOptions(rest.slice("plural,".length));
  const category = new Intl.PluralRules(locale).select(count);
  const chosen = options[category] ?? options["other"] ?? "";
  return format(chosen.replaceAll("#", String(count)), params, locale);
}

/**
 * Fill ICU-style `{name}` and `{n, plural, one {…} other {…}}` placeholders (`#` = the count).
 *
 * @example format("{n} Treffer", { n: 3 }, "de") // "3 Treffer"
 */
export function format(message: string, params: Params = {}, locale: Locale = "de"): string {
  let out = "";
  let i = 0;
  while (i < message.length) {
    const open = message.indexOf("{", i);
    if (open < 0) break;
    const end = closing(message, open);
    if (end < 0) break;
    out += message.slice(i, open) + expand(message.slice(open + 1, end), params, locale);
    i = end + 1;
  }
  return out + message.slice(i);
}

/** The message for `key` in `locale`; an unknown key gives the key itself (shown in mono, never hidden). */
export function t(locale: Locale, key: string, params: Params = {}): string {
  const message = DICTIONARIES[locale][key];
  return message === undefined ? key : format(message, params, locale);
}

/** Whether `locale` has a message for `key` (the label-coverage test). */
export function hasKey(locale: Locale, key: string): boolean {
  return key in DICTIONARIES[locale];
}
