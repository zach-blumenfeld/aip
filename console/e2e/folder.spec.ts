import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { CLI_ENV, FIRST_REVISION_DIR, FOLDER_WORKDIR } from "./aip";
import { answer, done, entry, fill, pausedAt, pick, runIdOf, start } from "./pages";

// The console started on a folder (`aip-console ./billing-support-agent`): no server, so no catalog, source
// view or audit. The folder's procedure is compiled and drawn by the CLI on this machine, runs are local and
// unrecorded, and history is this machine's run files of the folder.

test("folder mode shows the folder's procedure and hides the server pages", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByTestId("console-target")).toContainText(FIRST_REVISION_DIR);
  await expect(page.locator(".top-nav").getByRole("link")).toHaveText(["procedure", "run", "history"]);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("billing_support_agent");
  // The step graph first, from `aip compile --json` on the folder; data flow says an agent steers the route.
  await expect(page.getByTestId("step-node")).toHaveCount(6);
  await expect(page.locator('[data-testid="step-node"][data-step="triage"]')).toHaveAttribute("data-kind", "Task_Agent");
  await page.getByRole("radio", { name: "data flow" }).check();
  await expect(page.locator('[data-testid="data-flow-row"][data-key="tone"]').getByTestId("source-class")).toHaveText("agent");
  await page.getByRole("radio", { name: "right", exact: true }).check();
  await expect(page.getByTestId("step-graph")).toHaveAttribute("data-direction", "right");
  await page.getByRole("radio", { name: "down", exact: true }).check();
  await expect(page.getByTestId("diagnostics")).toHaveCount(0);

  // The source slice comes from the folder's own file.
  await page.locator('[data-testid="step-node"][data-step="reply"]').click();
  await expect(page.getByTestId("step-source")).toContainText("Task_Agent With reply");

  for (const hash of ["#/audit", "#/p/billing_support_agent", "#/server"]) {
    await page.goto(`./${hash}`);
    await expect(page.getByTestId("folder-mode")).toContainText("no catalog");
  }
});

test("the folder runs locally, both branches, with no server, and its runs are listed from this machine", async ({ page }) => {
  // Angry: the agent's answer steers the route, the script runs, the ticket lands in the working directory.
  const message = "Charged twice for March and nobody answers. Fix it today or I cancel.";
  await start(page, null, { message });
  let triage = await pausedAt(page, "triage");
  await pick(triage, "billing", "true");
  await pick(triage, "tone", "angry");
  await answer(triage);
  await done(page);
  await expect(page.getByTestId("run-recorded")).toHaveCount(0);        // nothing to record on

  // A local run: its run file holds the whole history.
  const runId = await runIdOf(page);
  const runFile = JSON.parse(readFileSync(path.join(CLI_ENV.AIP_HOME, "runs", `${runId}.json`), "utf8")) as
    { run: { history: { step: string; result: Record<string, unknown> }[] } };
  const ticket = runFile.run.history.find((h) => h.step === "escalate")!.result.ticket_id;
  const file = path.join(FOLDER_WORKDIR, "tickets", `${ticket}.json`);
  expect(existsSync(file)).toBe(true);
  expect(JSON.parse(readFileSync(file, "utf8")).message).toBe(message);

  // Calm: the reply task is answered here too.
  await page.getByRole("button", { name: "new run" }).click();
  await fill(page.getByTestId("pause-start"), "message", "Could you explain the $12 on my bill?");
  await page.getByTestId("pause-start-submit").click();
  triage = await pausedAt(page, "triage");
  await pick(triage, "billing", "true");
  await pick(triage, "tone", "calm");
  await answer(triage);
  const reply = await pausedAt(page, "reply");
  await fill(reply, "reply", "The $12 is your monthly plan.");
  await answer(reply);
  await done(page);
  await expect(page.getByTestId("run-result")).toContainText("$12 on my bill");

  // History in folder mode: this machine's runs of the folder, each a draft's; one opens from its run file.
  await page.goto("./#/runs");
  await expect(page.getByTestId("run-filters")).toHaveCount(0);
  const row = page.locator(`[data-testid="run-row"][data-run-id="${runId}"]`);
  await expect(row).toHaveAttribute("data-status", "done");
  await expect(row).toHaveAttribute("data-agent", "console");
  await row.getByRole("link").first().click();
  await expect(page.getByTestId("run-status")).toHaveText("done");
  await expect(entry(page, "by_tone").getByTestId("route-to")).toHaveText("escalate");
  // Its path, over the folder's graph: the agent said angry, so the reply was never reached.
  const drawn = page.getByTestId("run-path");
  await expect(drawn.locator('[data-testid="step-edge"][data-from="by_tone"][data-to="escalate"]')).toHaveAttribute("data-taken", "true");
  await expect(drawn.locator('[data-testid="step-node"][data-step="reply"]')).toHaveAttribute("data-visited", "false");

  // Run traffic in folder mode counts this machine's runs of the folder as it compiles now.
  await page.goto("./");
  await page.getByRole("radio", { name: "run traffic" }).check();
  await expect(page.getByTestId("traffic-summary")).toHaveAttribute("data-runs", "2", { timeout: 30_000 });
  await expect(page.locator('[data-testid="step-edge"][data-from="by_tone"][data-to="reply"]')).toHaveAttribute("data-runs", "1");
});
