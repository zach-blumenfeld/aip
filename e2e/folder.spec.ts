import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { CLI_ENV, FIRST_REVISION_DIR, FOLDER_WORKDIR } from "./aip";

// The console started on a folder (`aip-console ./billing-support`): no server, so no catalog, history or
// governance; the run page runs the folder locally through the same CLI, and its script's files land in the
// console's working directory.

test("folder mode hides the server pages", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByTestId("console-target")).toContainText(FIRST_REVISION_DIR);
  const nav = page.locator(".top-nav");
  await expect(nav.getByRole("link")).toHaveText(["run", "studio"]);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("billing-support");
  for (const hash of ["#/governance", "#/runs", "#/p/billing-support", "#/server"]) {
    await page.goto(`./${hash}`);
    await expect(page.getByTestId("folder-mode")).toContainText("no catalog");
  }
});

test("the folder runs locally, both branches, with no server", async ({ page }) => {
  // Angry: the decision is answered here, the script runs, the ticket lands in the working directory.
  const message = "Charged twice for March and nobody answers. Fix it today or I cancel.";
  await page.goto("./#/run");
  await page.getByTestId("pause-start").getByLabel("message", { exact: true }).fill(message);
  await page.getByRole("button", { name: "Start" }).click();
  const decision = page.getByTestId("pause-decision");
  await expect(decision).toBeVisible({ timeout: 20_000 });
  await decision.getByRole("group", { name: "billing" }).getByRole("radio", { name: /^yes/ }).check();
  await decision.getByRole("group", { name: "tone" }).getByRole("radio", { name: /^angry/ }).check();
  await decision.getByRole("button", { name: "Answer" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 20_000 });
  await expect(page.getByTestId("trace").getByRole("listitem")).toHaveText([/triage.*manual/, /by-tone.*escalate/, /escalate.*execution/]);

  // A local run: its id is not a link to a server's history, and its run file holds the whole history.
  const runId = (await page.getByTestId("run-id").textContent())!.trim();
  expect(runId).toMatch(/^[0-9a-f]{16}$/);
  await expect(page.getByTestId("run-id").locator("xpath=ancestor::a")).toHaveCount(0);
  const runFile = JSON.parse(readFileSync(path.join(CLI_ENV.AIP_HOME, "runs", `${runId}.json`), "utf8")) as
    { history: { step: string; result: Record<string, unknown> }[] };
  const ticket = runFile.history.find((h) => h.step === "escalate")!.result.ticket_id;
  const file = path.join(FOLDER_WORKDIR, "tickets", `${ticket}.json`);
  expect(existsSync(file)).toBe(true);
  expect(JSON.parse(readFileSync(file, "utf8")).message).toBe(message);

  // Calm: the client task is answered here too.
  await page.getByRole("button", { name: "new run" }).click();
  await page.getByTestId("pause-start").getByLabel("message", { exact: true }).fill("Could you explain the $12 on my bill?");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(decision).toBeVisible({ timeout: 20_000 });
  await decision.getByRole("group", { name: "billing" }).getByRole("radio", { name: /^yes/ }).check();
  await decision.getByRole("group", { name: "tone" }).getByRole("radio", { name: /^calm/ }).check();
  await decision.getByRole("button", { name: "Answer" }).click();
  const task = page.getByTestId("pause-client-task");
  await expect(task).toBeVisible({ timeout: 20_000 });
  await task.getByLabel("reply", { exact: true }).fill("The $12 is your monthly plan.");
  await task.getByRole("button", { name: "Answer" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 20_000 });
  await expect(page.getByTestId("final-state")).toContainText("$12 on my bill");
});
