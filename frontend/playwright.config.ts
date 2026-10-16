import { defineConfig, devices } from "@playwright/test";

declare const process: { env: Record<string, string | undefined> };

// E2E runs against FastAPI serving the production build (npm run build first):
//   python scripts/dev.py --prod      (or uvicorn api.main:app --app-dir backend --port 8100)
// Set PRISM_E2E_URL to target the Vite dev server instead (http://localhost:5174).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PRISM_E2E_URL ?? "http://127.0.0.1:8100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
