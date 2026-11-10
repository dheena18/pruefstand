/**
 * `basePath` of this build (`/pruefstand` on GitHub Pages, empty locally), inlined at build time from
 * `NEXT_BASE_PATH` through `next.config.ts`. This file has no Node imports, so client code can use it;
 * `data.ts` re-exports `dataUrl` (UI12-05: one helper builds every runtime URL).
 */
export const BASE_PATH: string = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/**
 * URL of a file of the published data tree below `basePath`, e.g. `dataUrl("cases/<run>/1.json")`.
 *
 * @param relative Path inside the data tree, no leading slash needed.
 * @param base Override of `basePath` (tests).
 */
export function dataUrl(relative: string, base: string = BASE_PATH): string {
  return `${base}/data/${relative.replace(/^\/+/, "")}`;
}
