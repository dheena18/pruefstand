// The only place in e2e/ that calls `page.route` (X1.2): delay a REAL fixture response until the test releases it,
// then `route.continue()`. Never fulfil, abort or change a body (lint rule `no-restricted-syntax` enforces it).
import type { Page } from "@playwright/test";

export interface Delay {
  /** Resolves with the number of requests currently held. */
  held(): number;
  /** Lets every held (and later) request through. */
  release(): void;
}

/** Holds every request whose URL matches `pattern` until `release()` is called. */
export async function delayRequests(page: Page, pattern: string | RegExp): Promise<Delay> {
  let open!: () => void;
  const gate = new Promise<void>((resolve) => {
    open = resolve;
  });
  let count = 0;
  await page.route(pattern, async (route) => {
    count += 1;
    await gate;
    count -= 1;
    await route.continue();
  });
  return { held: () => count, release: () => open() };
}
