import { FlatCompat } from "@eslint/eslintrc";
import tseslint from "typescript-eslint";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

export default tseslint.config(
    {
        ignores: [
            ".next/**",
            "out/**",
            ".sets/**",
            "coverage/**",
            "public/**",
            "fixtures/**",
            "src/types/generated/**",
            "next-env.d.ts",
        ],
    },
    ...compat.extends("next/core-web-vitals", "next/typescript"),
    ...tseslint.configs.strict,
    {
        rules: {
            "@typescript-eslint/no-explicit-any": "error",
            "@typescript-eslint/consistent-type-imports": "error",
            "no-console": "error",
            "@next/next/no-html-link-for-pages": "off",
        },
    },
    {
        // Node build scripts and tests may print.
        files: ["scripts/**", "test/**"],
        rules: { "no-console": "off" },
    },
);
