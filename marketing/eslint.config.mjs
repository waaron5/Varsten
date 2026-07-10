import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    "**/node_modules/**",
    ".next/**",
    "out/**",
    "build/**",
    "dist/**",
    "coverage/**",
    "next-env.d.ts",
    "varsten-pricing-page-lovable/**",
    "../backend/**",
    "../frontend/.next/**",
    "../frontend/node_modules/**",
    "../sdk/**/dist/**",
    "../sdk/**/node_modules/**",
  ]),
]);

export default eslintConfig;
