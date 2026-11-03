"use client";

import { useParams } from "next/navigation";

import { ErrorPanel } from "@/components/ErrorPanel";
import { isLocale } from "@/lib/i18n";

/** Client error boundary (ui-spec §4.8): the error class and a reload button, never a stack trace. */
export default function LocaleError({ error }: { error: Error & { digest?: string } }) {
  const params = useParams<{ locale?: string }>();
  const locale = params.locale !== undefined && isLocale(params.locale) ? params.locale : "de";
  return (
    <ErrorPanel
      locale={locale}
      kind={error.name}
      onReload={() => {
        window.location.reload();
      }}
    />
  );
}
