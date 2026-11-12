import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a throw-away backend with fixture data (never the real database).
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 30_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8791", trace: "retain-on-failure" },
  webServer: {
    command: "../backend/.venv/bin/python ../backend/tests/e2e_server.py",
    url: "http://127.0.0.1:8791/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testIgnore: /responsive/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /responsive/, dependencies: ["desktop"] },
    { name: "tablet", use: { ...devices["Desktop Chrome"], viewport: { width: 820, height: 1180 } }, testMatch: /responsive/, dependencies: ["desktop"] },
  ],
});
