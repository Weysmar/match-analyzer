import { defineConfig, devices } from "@playwright/test";

/**
 * The end-to-end journey (the end criterion of step 8), in French and in English, on a 375 px phone.
 * `scripts/e2e.sh` starts the stack first. Nothing is recorded: a trace or a screenshot would hold
 * the names of the replay's players.
 */
export default defineConfig({
  testDir: "./e2e",
  // One account and one replay go through the whole journey: no two tests at once.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 180_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: ["fr", "en"].map((language) => ({
    name: language,
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width: 375, height: 812 },
      locale: language === "fr" ? "fr-FR" : "en-US",
      extraHTTPHeaders: { "Accept-Language": language === "fr" ? "fr-FR,fr" : "en-US,en" },
    },
  })),
});
