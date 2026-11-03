import { BASE_PATH } from "@/lib/site";

/**
 * The no-flash theme script (ui-spec §7): a blocking `<script src>` in `<head>` of every document, a file in
 * `public/` and never inline code. It must block, so Next's `no-sync-scripts` rule does not apply here.
 */
export function ThemeInit() {
  // eslint-disable-next-line @next/next/no-sync-scripts -- blocking by design: sets data-theme before first paint
  return <script src={`${BASE_PATH}/theme-init.js`} />;
}
