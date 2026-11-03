import type { NextConfig } from "next";

// Static export for GitHub Pages (ui-spec §2.1, §2.4). `NEXT_BASE_PATH` is `/pruefstand` in production and in
// the `basepath-smoke` job, empty everywhere else. No headers, no rewrites: Pages cannot send either (§7.4).
const basePath = process.env["NEXT_BASE_PATH"] ?? "";

const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  ...(basePath === "" ? {} : { basePath }),
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
  reactStrictMode: true,
  poweredByHeader: false,
};

export default config;
