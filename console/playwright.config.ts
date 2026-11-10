import { defineConfig } from "@playwright/test";
import { AGENT_MODEL, AGENT_MODEL_PORT, AIP_PORT, AIP_REPO, CLI_ENV, CONSOLE_PORT, FIRST_REVISION_DIR, FOLDER_PORT, FOLDER_WORKDIR, MODEL, MODEL_PORT, SERVER, STORE, WORKDIR } from "./e2e/aip";

// Five processes, started in order:
//   1. e2e/model.mjs, a decision model with the TypeSafe API shape that answers from marks in the text, and
//      e2e/agent.mjs, a stand-in agent model (Chat Completions) that answers the Studio's runs from a script
//   2. e2e/prepare.mjs writes a fresh .aip-e2e/, the bundle is built, and `aip server` from this repository
//      (AIP_REPO, default `..`) starts on a Relate store under .aip-e2e/store
//   3. the console against that server (bin/aip-console.mjs --server), the way `npx aip-console` runs it
//   4. the console in folder mode, over the first revision's folder, with no server
// Global setup then publishes the procedures. The `console` project runs every spec but folder.spec.ts
// against (3); the `folder` project runs folder.spec.ts against (4).
//
// The server also reads a config file beside the client's (AIP_CONFIG moves both) and the environment;
// the specs assume a server with no tokens, so neither may leak in from this machine.
const isolated = { AIP_CONFIG: CLI_ENV.AIP_CONFIG, AIP_SERVER_CONFIG: "" };

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 90_000,
  // The specs share one server and one working directory: a run made by one is in another's history.
  workers: 1,
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
  // In CI the list is the log a reader opens, and the annotations mark the failures on the commit.
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  webServer: [
    {
      command: `node e2e/model.mjs ${MODEL_PORT}`,
      url: `${MODEL}/v1/models`,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: `node e2e/agent.mjs ${AGENT_MODEL_PORT}`,
      url: `${AGENT_MODEL}/models`,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: `node e2e/prepare.mjs && npm run build && ` +
        `uv run --project "${AIP_REPO}" aip server --backend relate --path "${STORE}" --port ${AIP_PORT}`,
      env: isolated,
      url: `${SERVER}/health`,
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
