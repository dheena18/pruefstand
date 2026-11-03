import type { Metadata } from "next";

/** `<link rel="alternate" hreflang>` for both locales of a path below the locale prefix (ui-spec §10.1). */
export function alternatesFor(rest: string): NonNullable<Metadata["alternates"]> {
  const tail = rest === "" ? "/" : `/${rest.replace(/^\/|\/$/g, "")}/`;
  const base = process.env["NEXT_PUBLIC_BASE_PATH"] ?? "";
  return { languages: { de: `${base}/de${tail}`, en: `${base}/en${tail}` } };
}
