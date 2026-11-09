import { defineConfig } from "@playwright/test";
import { AIP_PORT, CLI_ENV, CONSOLE_PORT, E2E, FIRST_REVISION_DIR, FOLDER_PORT, FOLDER_WORKDIR, SERVER, WORKDIR, AIP_REPO } from "./e2e/aip";

// Three servers, started in order:
//   1. e2e/prepare.mjs writes a fresh .aip-e2e/, the bundle is built, and a filesystem-backed `aip server` from the
//      sibling aip repo (AIP_REPO, default ../aip) starts over .aip-e2e/root
//   2. the console against that server (bin/aip-console.mjs --server), the way `npx aip-console` runs it
//   3. the console in folder mode, over the first revision's folder, with no server
// Global setup then publishes the two revisions of billing-support. The `console` project runs every spec but
// folder.spec.ts against (2); the `folder` project runs folder.spec.ts against (3).
const isolated = { AIP_CONFIG: CLI_ENV.AIP_CONFIG, TYPESAFE_API_KEY: "" };

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  // PLAYWRIGHT_CHANNEL=chrome drives an installed Google Chrome instead of the
  // downloaded Chromium (handy offline or before `npx playwright install`).
  use: {
    trace: "retain-on-failure",
    channel: process.env.PLAYWRIGHT_CHANNEL,
  },
  projects: [
    { name: "console", testIgnore: /folder\.spec\.ts/, use: { baseURL: `http://localhost:${CONSOLE_PORT}/` } },
    { name: "folder", testMatch: /folder\.spec\.ts/, use: { baseURL: `http://localhost:${FOLDER_PORT}/` } },
  ],
  reporter: process.env.CI ? "github" : "list",
  webServer: [
    {
      command: `node e2e/prepare.mjs && npm run build && ` +
        `uv run --project "${AIP_REPO}" --group dev aip server --backend filesystem --root "${E2E}/root" --port ${AIP_PORT}`,
      // The server also reads ~/.config/aip/server.toml and the environment; the specs assume a server with no
      // tokens, so neither may leak in from this machine.
      env: isolated,
      url: `${SERVER}/catalog`,
      reuseExistingServer: false,
      stdout: "pipe",
      timeout: 180_000,
    },
    {
      command: `node bin/aip-console.mjs --server ${SERVER} --port ${CONSOLE_PORT} --workdir "${WORKDIR}"`,
      env: CLI_ENV,
      url: `http://localhost:${CONSOLE_PORT}/console/config`,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: `node bin/aip-console.mjs "${FIRST_REVISION_DIR}" --port ${FOLDER_PORT} --workdir "${FOLDER_WORKDIR}"`,
      env: CLI_ENV,
      url: `http://localhost:${FOLDER_PORT}/console/config`,
      reuseExistingServer: false,
      stdout: "pipe",
    },
  ],
});
