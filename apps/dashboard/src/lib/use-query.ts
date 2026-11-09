import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

/**
 * The URL query for the query-driven pages (ui-spec §6, UI11-09). The page renders its static default view as the
 * `<Suspense>` fallback; the client reader that calls this hook applies the query after hydration and marks
 * `<main data-hydrated="true">` so Playwright can wait for it.
 */
export function useQueryString(): string {
  const params = useSearchParams();
  useEffect(() => {
    document.querySelector("main")?.setAttribute("data-hydrated", "true");
  }, []);
  return params.toString();
}
