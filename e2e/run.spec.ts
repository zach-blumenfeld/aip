import { cpSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { CHECKED, CHECKED_REVISION_DIR, SERVER, WORKDIR, aip } from "./aip";

// The run console drives `aip run --progress` and `aip resume --progress` through the console's process. The
// CLI has no decision model here, so `triage` pauses for the page to answer; the router then sends angry
// messages to the escalate script, which runs on this machine and files its ticket under the console's
// working directory, and calm ones to the client task.

interface RunRecord {
  status: string;
  history: { step: string; kind: string; result: Record<string, unknown>; attribution?: { resolver: string } }[];
}

async function record(page: Page, runId: string): Promise<RunRecord> {
  const res = await page.request.get(`${SERVER}/runs/${runId}`);
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as RunRecord;
}

async function startAndTriage(page: Page, message: string, tone: "angry" | "calm"): Promise<string> {
  await page.goto("./#/run/billing-support");
  await expect(page.getByTestId("run-status")).toHaveText("not started");
  const start = page.getByTestId("pause-start");
  await expect(start.getByTestId("payload")).toContainText('"message"');     // prefilled from the example input
  await start.getByLabel("message", { exact: true }).fill(message);
  await expect(start.getByTestId("payload")).toContainText(message.slice(0, 20));
  await start.getByRole("button", { name: "Start" }).click();

  const decision = page.getByTestId("pause-decision");
  await expect(decision).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("run-status")).toHaveText("paused");
  await expect(decision.getByTestId("pause-state")).toContainText(message.slice(0, 20));
  await decision.getByRole("group", { name: "billing" }).getByRole("radio", { name: /^yes/ }).check();
  await decision.getByRole("group", { name: "tone" }).getByRole("radio", { name: new RegExp(`^${tone}`) }).check();
  await expect(page.getByTestId("run-id")).toHaveText(/^[0-9a-f]{16}$/);
  const runId = (await page.getByTestId("run-id").textContent())!.trim();
  await decision.getByRole("button", { name: "Answer" }).click();
  return runId;
}

function ticketFile(id: unknown): string {
  return path.join(WORKDIR, "tickets", `${id}.json`);
}

test("an angry message runs the escalation script on this machine", async ({ page }) => {
  const message = "I was charged twice and I want my money back NOW or I cancel!";
  const runId = await startAndTriage(page, message, "angry");

  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 20_000 });
  // the start and end steps print no progress line
  const trace = page.getByTestId("trace").getByRole("listitem");
  await expect(trace).toHaveText([/triage.*decision.*manual/, /by-tone.*router.*escalate/, /escalate.*execution.*s$/]);
  await expect(page.getByTestId("final-state")).toContainText(message);

  // The server recorded what the client's script returned; the ticket file is on this side.
  const run = await record(page, runId);
  expect(run.status).toBe("done");
  const escalate = run.history.find((h) => h.step === "escalate")!;
  expect(escalate.result.queue).toBe("tier2");
  const file = ticketFile(escalate.result.ticket_id);
  expect(existsSync(file)).toBe(true);
  expect(JSON.parse(readFileSync(file, "utf8")).message).toBe(message);

  // The run is in the history, with the decision's attribution.
  await page.getByTestId("run-done").getByRole("link", { name: "history" }).click();
  await expect(page).toHaveURL(new RegExp(`#/runs/${runId}$`));
  await expect(page.getByTestId("run-status")).toHaveText("done");
  const triage = page.locator('[data-testid="run-step"][data-step="triage"]');
  await expect(triage.getByTestId("attribution")).toHaveAttribute("data-resolver", "manual");
  await expect(triage.getByTestId("attribution")).toContainText("resolver manual");
  await expect(triage.locator('[data-question="tone"] [data-testid="answer-value"]')).toHaveText('"angry"');
  await expect(triage.locator('[data-question="tone"] [data-testid="answer-confidence"]')).toContainText("none");
  await expect(page.locator('[data-testid="run-step"][data-step="escalate"]')).toContainText("ran on the client");
});

test("a decision with fallback off stops a client that has no decision model, and says so", async ({ page }) => {
  // The run console with no model reaches `triage` of billing-checked: its decision allows a manual answer, so the
  // page gets the form; the check then fires with reason `absent`, whatever the tone, and the run escalates.
  await page.goto(`./#/run/${CHECKED}`);
  const start = page.getByTestId("pause-start");
  await start.getByLabel("message", { exact: true }).fill("Why was I billed $12? [checked]");
  await start.getByRole("button", { name: "Start" }).click();
  const decision = page.getByTestId("pause-decision");
  await expect(decision).toBeVisible({ timeout: 20_000 });
  await expect(decision.getByTestId("manual-confidence-note")).toContainText("tone_confidence");
  await decision.getByRole("group", { name: "billing" }).getByRole("radio", { name: /^yes/ }).check();
  await decision.getByRole("group", { name: "tone" }).getByRole("radio", { name: /^calm/ }).check();
  const runId = (await page.getByTestId("run-id").textContent())!.trim();
  await decision.getByRole("button", { name: "Answer" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 20_000 });
  await expect(page.getByTestId("trace").getByRole("listitem")).toHaveText([/triage.*manual/, /by-tone.*escalate/, /escalate.*execution/]);
  const run = await record(page, runId);
  const route = run.history.find((h) => h.step === "by-tone")!;
  expect(route.result).toMatchObject({ to: "escalate", confidence: { fired: true, reason: "absent" } });

  // The same skill with `fallback: false` on its decision: the CLI stops before posting anything.
  const strict = path.join(WORKDIR, "billing-strict");
  cpSync(CHECKED_REVISION_DIR, strict, { recursive: true });
  const md = path.join(strict, "SKILL.md");
  writeFileSync(md, readFileSync(md, "utf8").replace(/^name: billing-checked$/m, "name: billing-strict").replace("    fallback: true\n", "    fallback: false\n"));
  const published = aip(["publish", strict]).trim();
  expect(published).toMatch(/billing-strict@/);
  await page.goto("./#/run/billing-strict");
  await page.getByTestId("pause-start").getByLabel("message", { exact: true }).fill("Charged twice. [strict]");
  await page.getByRole("button", { name: "Start" }).click();
  const error = page.getByTestId("run-error");
  await expect(error).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("run-status")).toHaveText("failed");
  await expect(error.getByTestId("error-kind")).toHaveText("no_decision_model");
  await expect(error).toContainText("triage");
  await expect(error.getByTestId("no-decision-model")).toContainText("fallback: false");
  await expect(error.getByRole("button", { name: "Retry" })).toBeVisible();      // resumable once a key is configured
  const object = JSON.parse((await error.getByTestId("error-object").textContent())!) as Record<string, unknown>;
  expect(object).toMatchObject({ error: "no_decision_model", step: "triage", fallback: false, resumable: true });
});

test("a calm message pauses as a client task that is answered in the page", async ({ page }) => {
  const runId = await startAndTriage(page, "Hi, could you tell me why I was billed $12 this month?", "calm");

  const task = page.getByTestId("pause-client-task");
  await expect(task).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("run-status")).toHaveText("paused");
  await expect(page.getByTestId("trace").getByRole("listitem")).toHaveText([/triage/, /by-tone.*reply/]);
  await expect(task.getByTestId("task")).toContainText("Write a short, calm reply");
  await expect(task.getByTestId("task")).toContainText("billed $12");                 // {message} rendered
  await expect(task.getByTestId("task")).toContainText("Refunds");                    // the policy asset rendered
  await expect(task.getByTestId("references")).toContainText("references/help.md");
  await expect(task.getByTestId("pause-state")).toContainText('"tone": "calm"');

  // The answer carries only what `answer_with` asks for.
  await task.getByLabel("reply", { exact: true }).fill("Thanks for asking: the $12 is your monthly plan charge.");
  await expect(task.getByTestId("payload")).toHaveValue(/^\{\s*"reply": "Thanks for asking/);
  await task.getByRole("button", { name: "Answer" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 20_000 });
  await expect(page.getByTestId("trace").getByRole("listitem")).toHaveText([/triage/, /by-tone/, /reply.*client_task/]);
  await expect(page.getByTestId("final-state")).toContainText("billed $12");
  const run = await record(page, runId);
  expect(run.status).toBe("done");
  expect(run.history.map((h) => h.step)).toEqual(["start", "triage", "by-tone", "reply", "end"]);
});

test("a failing script shows the error object, and retry resumes once the cause is fixed", async ({ page }) => {
  const down = path.join(WORKDIR, "ticket-service-down");
  writeFileSync(down, "");
  try {
    const runId = await startAndTriage(page, "[outage] Charged twice, fix it now or I cancel!", "angry");

    const error = page.getByTestId("run-error");
    await expect(error).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("run-status")).toHaveText("failed");
    await expect(error.getByTestId("error-kind")).toHaveText("script_failed");
    await expect(error.getByTestId("exit-code")).toHaveText("1");
    await expect(error.getByTestId("error-stderr")).toHaveText("ticket service unreachable");
    const object = JSON.parse((await error.getByTestId("error-object").textContent())!) as Record<string, unknown>;
    expect(object).toMatchObject({ error: "script_failed", step: "escalate", script: "scripts/escalate.py", exit_code: 1,
                                   run_id: runId, resumable: true });
    expect((await record(page, runId)).status).toBe("failed");

    rmSync(down);
    await error.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 20_000 });
    await expect(page.getByTestId("trace").getByRole("listitem").last()).toHaveText(/escalate.*execution/);
    const run = await record(page, runId);
    expect(run.status).toBe("done");
    expect(run.history.filter((h) => h.step === "escalate").map((h) => h.kind)).toEqual(["error", "execution"]);
  } finally {
    rmSync(down, { force: true });
  }
});

test("cancel stops the running aip", async ({ page }) => {
  await startAndTriage(page, "[slow] Charged twice, fix it now!", "angry");
  await expect(page.getByTestId("run-running")).toBeVisible();
  // Give the CLI time to reach the script, which sleeps for a minute.
  await page.waitForTimeout(3_000);
  await page.getByTestId("run-running").getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("cancelled", { timeout: 10_000 });
  await expect(page.getByTestId("run-problem")).toContainText("Cancelled: aip stopped");
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
});

test("an invalid start input is reported and no run is opened", async ({ page }) => {
  await page.goto("./#/run/billing-support");
  await page.getByTestId("payload").fill("{}");
  await page.getByRole("button", { name: "Start" }).click();
  const error = page.getByTestId("run-error");
  await expect(error).toBeVisible({ timeout: 20_000 });
  await expect(error.getByTestId("error-kind")).toHaveText("invalid_input");
  await expect(error).toContainText("message");
  await expect(page.getByTestId("run-id")).toHaveCount(0);
  await expect(error.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.getByTestId("pause-start")).toBeVisible();          // fix the input and start again
});
