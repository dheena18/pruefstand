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
        files: ["scripts/**", "test/**", "e2e/**"],
        rules: { "no-console": "off" },
    },
    {
        // X1.2: no API mocks. `page.route` is for delays only (e2e/delay.ts); fulfilling or aborting a request is forbidden.
        files: ["e2e/**"],
        rules: {
            "no-restricted-syntax": [
                "error",
                {
                    selector: "CallExpression[callee.property.name=/^(fulfill|abort)$/]",
                    message:
                        "e2e/ may only delay real responses (route.continue after a promise); never fulfill or abort (X1.2).",
                },
            ],
        },
    },
);
