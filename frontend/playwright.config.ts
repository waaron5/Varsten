import { defineConfig } from "playwright/test";

const port = Number(process.env.PLAYWRIGHT_PORT ?? 3000);
const host = process.env.PLAYWRIGHT_HOST ?? "localhost";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://${host}:${port}`;
const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./playwright/tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev:next -- -p ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      ...process.env,
      APP_BASE_URL: baseURL,
      AUTH0_AUDIENCE: process.env.AUTH0_AUDIENCE ?? "https://api.varsten.test",
      AUTH0_BASE_URL: baseURL,
      AUTH0_CLIENT_ID: process.env.AUTH0_CLIENT_ID ?? "playwright-client",
      AUTH0_CLIENT_SECRET: process.env.AUTH0_CLIENT_SECRET ?? "playwright-client-secret",
      AUTH0_DOMAIN: process.env.AUTH0_DOMAIN ?? "varsten-playwright.us.auth0.com",
      AUTH0_SECRET:
        process.env.AUTH0_SECRET ??
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      NEXT_PUBLIC_API_BASE: apiBase,
      NEXT_PUBLIC_E2E_AUTH_BYPASS: "1",
    },
  },
});
