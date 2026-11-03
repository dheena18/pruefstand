"use client";

import { useParams } from "next/navigation";

import { NotFoundView } from "@/components/NotFoundView";
import { isLocale } from "@/lib/i18n";

/** `notFound()` inside the locale tree: the same view in the route locale (ui-spec §4.8). */
export default function LocaleNotFound() {
  const params = useParams<{ locale?: string }>();
  const locale = params.locale !== undefined && isLocale(params.locale) ? params.locale : "de";
  return <NotFoundView locale={locale} basePath={process.env["NEXT_PUBLIC_BASE_PATH"] ?? ""} />;
}
