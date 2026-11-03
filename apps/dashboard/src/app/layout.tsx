import type { ReactNode } from "react";

import "./globals.css";

/**
 * Pass-through root layout (ui-spec §2.1): it renders no `<html>`. The locale layout, the root redirect page
 * and the site 404 each return their own document, so every document gets its own `lang`.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
