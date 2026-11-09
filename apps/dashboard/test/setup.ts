import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, vi } from "vitest";

// next/link normalises hrefs with the router config of the build (trailingSlash); component tests assert the
// hrefs the components pass, so Link is a plain anchor here. The build output tests cover the real behaviour.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children?: ReactNode;
    scroll?: boolean;
  }) => {
    delete rest.scroll; // a Link-only prop that must not reach the DOM
    return createElement("a", { href, ...rest }, children);
  },
}));

afterEach(() => {
  cleanup();
});
