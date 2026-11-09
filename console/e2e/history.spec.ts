import { expect, test, type Page } from "@playwright/test";
import { aipJson } from "./aip";

// History replays runs the server persisted. Spec files run in parallel workers, so this one drives
// billing-support through both branches itself with the `aip` CLI (as the run console does), then opens
// the resulting runs.

type Outcome = Record<string, unknown> & { run_id: string };

/** Start a run, answer triage by hand; the CLI runs on until the run ends or pauses as a client task. */
function drive(message: string, tone: "angry" | "calm"): Outcome {
  const paused = aipJson(["run", "billing-support"], { message }) as Outcome;
  expect(paused.paused).toBe("decision");
  return aipJson(["resume", paused.run_id], { billing: true, tone }) as Outcome;
}

async function expectTrace(page: Page, visited: string[], notVisited: string[], edges: [string, string][]) {
  const graph = page.getByRole("img", { name: "step graph" });
  await expect(graph).toBeVisible();
  for (const step of visited) await expect(graph.locator(`[data-testid="step-node"][data-step="${step}"]`)).toHaveClass(/visited/);
  for (const step of notVisited) await expect(graph.locator(`[data-testid="step-node"][data-step="${step}"]`)).not.toHaveClass(/visited/);
  for (const [from, to] of edges) {
    await expect(graph.locator(`[data-testid="step-edge"][data-from="${from}"][data-to="${to}"]`)).toHaveAttribute("data-taken", "true");
  }
  const taken = graph.locator('[data-testid="step-edge"][data-taken="true"]');
  await expect(taken).toHaveCount(edges.length);
}

test("the angry run's trace highlights the script step", async ({ page }) => {
  const done = drive("I was charged twice and I want my money back NOW or I cancel!", "angry");
  expect(done.done).toBe(true);

  await page.goto(`./#/runs/${done.run_id}`);
  await expect(page.getByTestId("run-status")).toHaveText("done");
  await expectTrace(page, ["start", "triage", "by-tone", "escalate", "end"], ["reply"],
                    [["start", "triage"], ["triage", "by-tone"], ["by-tone", "escalate"], ["escalate", "end"]]);

  // The step cards, read-only: the start input, the manual decision with its attribution, the branch, the script's stdout.
  const cards = page.getByTestId("run-step");
  await expect(cards).toHaveCount(5);
  await expect(cards.first()).toHaveAttribute("data-kind", "start");
  await expect(cards.first().getByTestId("state-out")).toContainText("charged twice");
  await expect(page.locator('[data-testid="run-step"][data-step="triage"]').getByTestId("attribution")).toHaveAttribute("data-resolver", "manual");
  await expect(page.getByTestId("branch-taken")).toContainText("escalate");
  await expect(page.locator('[data-testid="run-step"][data-step="escalate"]').getByTestId("script-stdout")).toContainText('"ticket_id"');
  await expect(page.locator('[data-testid="run-step"][data-step="escalate"]').getByTestId("script-stdout")).toContainText('"queue": "tier2"');
  await expect(page.getByTestId("trace").getByRole("listitem")).toHaveText([/start/, /triage/, /by-tone/, /escalate/, /end/]);
  await expect(page.getByRole("button")).toHaveCount(0);           // nothing to drive from here
});

test("the calm run's trace highlights the client task, paused and then done", async ({ page }) => {
  const paused = drive("Hi, could you tell me why I was billed $12 this month?", "calm");
  expect(paused.paused).toBe("client_task");

  await page.goto(`./#/runs/${paused.run_id}`);
  await expect(page.getByTestId("run-status")).toHaveText("paused");
  await expectTrace(page, ["start", "triage", "by-tone", "reply"], ["escalate", "end"], [["start", "triage"], ["triage", "by-tone"], ["by-tone", "reply"]]);
  await expect(page.getByTestId("run-pause")).toContainText("Paused at reply");
  await expect(page.locator('[data-testid="run-step"][data-step="reply"]')).toHaveCount(0);   // recorded once answered
  await expect(page.getByTestId("run-pause").getByTestId("task")).toContainText("billed $12");

  // Finish it the way the console would, then the page replays the whole run.
  const done = aipJson(["resume", paused.run_id], { reply: "Thanks for asking: the $12 is your monthly plan charge." });
  expect(done.done).toBe(true);
  await page.reload();
  await expect(page.getByTestId("run-status")).toHaveText("done");
  await expectTrace(page, ["start", "triage", "by-tone", "reply", "end"], ["escalate"],
                    [["start", "triage"], ["triage", "by-tone"], ["by-tone", "reply"], ["reply", "end"]]);
  await expect(page.getByTestId("final-state")).toContainText("billed $12");
  await expect(page.getByTestId("run-pause")).toHaveCount(0);
  const reply = page.locator('[data-testid="run-step"][data-step="reply"]');
  await expect(reply.getByTestId("task")).toContainText("billed $12");
  expect(JSON.parse(await reply.getByTestId("state-out").innerText())).toEqual({ reply: "Thanks for asking: the $12 is your monthly plan charge." });
});

test("the runs list filters by name and status and links to the run page", async ({ page }) => {
  const done = drive("Charged twice, fix it now!", "angry");

  await page.goto("./#/runs");
  await expect(page.getByRole("table", { name: "runs" })).toBeVisible();
  await page.getByRole("combobox", { name: "name" }).selectOption("billing-support");
  await page.getByRole("combobox", { name: "status" }).selectOption("done");
  await expect(page).toHaveURL(/#\/runs\?name=billing-support&status=done$/);
  const rows = page.getByTestId("run-row");
  await expect(rows.first()).toBeVisible();
  for (const status of await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-status")))) expect(status).toBe("done");
  const mine = page.locator(`[data-testid="run-row"][data-run-id="${done.run_id}"]`);
  await expect(mine).toHaveCount(1);

  // Other specs' runs may be failed right now (run.spec retries one), so only this run's absence is certain.
  await page.getByRole("combobox", { name: "status" }).selectOption("failed");
  await expect(page).toHaveURL(/status=failed$/);
  await expect(mine).toHaveCount(0);
  for (const status of await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-status")))) expect(status).toBe("failed");
  await page.getByRole("combobox", { name: "status" }).selectOption("done");

  await mine.getByRole("link", { name: done.run_id }).click();
  await expect(page).toHaveURL(new RegExp(`#/runs/${done.run_id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText("billing-support");
  await expect(page.getByTestId("run-status")).toHaveText("done");
});
