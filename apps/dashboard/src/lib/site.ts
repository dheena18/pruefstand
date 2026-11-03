import licences from "@/content/licences.json";

import { defaultDataDir, loadRun, loadRunIndex } from "./data";

/** `basePath` of this build (`/pruefstand` on GitHub Pages, empty locally); inlined at build time. */
export const BASE_PATH: string = process.env["NEXT_PUBLIC_BASE_PATH"] ?? "";

/** Origin of the Try-it demo API; the "Try it" link exists only when it is set at build (UI-25). */
export const DEMO_API_URL: string = process.env["NEXT_PUBLIC_DEMO_API_URL"] ?? "";

export const GITHUB_URL = "https://github.com/dheena18/pruefstand";

export type Licences = typeof licences;
export { licences };

export interface FooterInfo {
  /** `pruefstand_version` of the newest exported run, or null for an empty export. */
  version: string | null;
  /** `created_at` of the newest exported run: the export has no timestamp of its own. */
  exportedAt: string | null;
}

/** Version and export time for the footer, read from the (validated) data tree at build time. */
export async function footerInfo(dir: string = defaultDataDir()): Promise<FooterInfo> {
  const newest = (await loadRunIndex(dir)).runs[0];
  if (newest === undefined) return { version: null, exportedAt: null };
  const run = await loadRun(newest.run_id, dir);
  return { version: run.pruefstand_version, exportedAt: newest.created_at };
}
