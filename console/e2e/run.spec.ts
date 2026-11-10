import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { AGENT, BILLING, DYNAMIC, FIXED, SERVER, TRIAGE, WORKDIR } from "./aip";
import { answer, done, entry, fill, pausedAt, pick, runIdOf, start, task } from "./pages";

// The run console: every run goes through the `aip` CLI the console spawns, on this machine, and is
// recorded on the server as agent `console` in the tab's session.

test("a task that decides, then a task that does the work: the agent's answers steer the run", async ({ page }) => {
  await start(page, AGENT, { message: "Could you explain the $12 on my bill?" });
  const triage = await pausedAt(page, "triage");
  await expect(triage.getByTestId("task-prompt")).toContainText("explain the $12");
  await pick(triage, "billing", "true");
  await pick(triage, "tone", "calm");
  await answer(triage);

  const reply = await pausedAt(page, "reply");
  await expect(reply.getByTestId("references")).toContainText("references/help.md");
  await fill(reply, "reply", "The $12 is your monthly plan.");
  await answer(reply);
  await done(page);
  await expect(page.getByTestId("run-result")).toContainText("The $12 is your monthly plan.");

  // The record on the page: who answered each task, and where the route went on the agent's answer.
  await expect(entry(page, "triage").getByTestId("answered-by")).toContainText("console");
  await expect(entry(page, "by_tone").getByTestId("route-to")).toHaveText("reply");
  await expect(entry(page, "by_tone")).toContainText("no confidence check");
  await expect(entry(page, "triage").getByTestId("entry-time")).toHaveText(/^\+\d/);

  // It was recorded on the server, under this tab's session.
  await expect(page.getByTestId("run-recorded")).toHaveAttribute("data-recorded", "true");
  const session = (await page.getByTestId("session-id").textContent())!.trim();
  const recorded = await (await fetch(`${SERVER}/runs/${await runIdOf(page)}`)).json() as { identity: { agent: string; session: string }; draft: boolean; revision: string };
  expect(recorded.identity).toMatchObject({ agent: "console", session });
  expect(recorded).toMatchObject({ draft: false, revision: "2" });
});

test("the script runs on this machine: its ticket lands in the console's working directory", async ({ page }) => {
  const message = "Charged twice for March and nobody answers. Fix it today or I cancel.";
  await start(page, AGENT, { message });
  const triage = await pausedAt(page, "triage");
  await pick(triage, "billing", "true");
  await pick(triage, "tone", "angry");
  await answer(triage);
  await done(page);
  await expect(page.getByTestId("trace").getByRole("listitem")).toContainText(["start", "triage", "by_tone", "escalate", "end"]);
  await expect(entry(page, "escalate").getByTestId("script")).toHaveText("scripts/escalate.py");

  const result = JSON.parse((await page.getByTestId("run-result").textContent())!) as { ticket_id: number; queue: string };
  const file = path.join(WORKDIR, "tickets", `${result.ticket_id}.json`);
  expect(existsSync(file)).toBe(true);
  expect(JSON.parse(readFileSync(file, "utf8")).message).toBe(message);
});

test("a failing script stops the run where it was, and Retry runs the step again", async ({ page }) => {
  const down = path.join(WORKDIR, "ticket-service-down");
  writeFileSync(down, "");
  try {
    await start(page, AGENT, { message: "Nothing works and I want out. [outage]" });
    const triage = await pausedAt(page, "triage");
    await pick(triage, "billing", "true");
    await pick(triage, "tone", "angry");
    await answer(triage);
    const error = page.getByTestId("run-error");
    await expect(error).toHaveAttribute("data-kind", "script_failed", { timeout: 30_000 });
    await expect(error.getByTestId("error-stderr")).toContainText("ticket service unreachable");
    await expect(page.getByTestId("run-status")).toHaveText("failed");
  } finally {
    rmSync(down, { force: true });
  }
  await page.getByTestId("retry").click();
  await done(page);
  await expect(entry(page, "escalate")).toBeVisible();
});

test("a decision is the model's: a sure answer routes by its value, an unsure one fires the route's check", async ({ page }) => {
  await start(page, BILLING, { message: "This is the third double charge. Fix it today. [angry]" });
  await done(page);
  const decided = entry(page, "triage");
  await expect(decided.getByTestId("answered-by")).toHaveAttribute("data-model", "e2e-1");
  await expect(decided.locator('[data-testid="answer"][data-name="tone"]')).toHaveAttribute("data-value", "angry");
  await expect(decided.locator('[data-testid="answer"][data-name="tone"]').getByTestId("answer-confidence")).toContainText("0.97");
  const sure = entry(page, "by_tone").getByTestId("check");
  await expect(sure).toHaveAttribute("data-fired", "false");
  await expect(sure).toContainText("0.97 is not below 0.9");

  // Calm, but the model is not sure: the check sends it to a person all the same.
  await page.getByRole("button", { name: "new run" }).click();
  const form = page.getByTestId("pause-start");
  await fill(form, "message", "Hm. Saw two March charges, maybe I misread. [calm] [unsure]");
  await page.getByTestId("pause-start-submit").click();
  await done(page);
  const fired = entry(page, "by_tone").getByTestId("check");
  await expect(fired).toHaveAttribute("data-fired", "true");
  await expect(fired).toHaveAttribute("data-reason", "below");
  await expect(fired).toContainText("0.55 is below 0.9");
  await expect(entry(page, "by_tone").getByTestId("route-to")).toHaveText("escalate");
});

test("a loop: the passes nest under it, each says why it ran, and the loop says why it ended", async ({ page }) => {
  await start(page, FIXED, { request: "A thank-you note to a customer who renewed." });
  const draft = await pausedAt(page, "draft");
  await fill(draft, "work", "Thanks, you absolute legend! [break:courteous]");
  await answer(draft);

  // The model found the tone policy broken: the loop's first pass asks for a fix, and says it is not the last.
  const fix = await pausedAt(page, "fix");
  await expect(task(fix, 0).getByTestId("last-pass")).toHaveCount(0);
  const loop = page.locator('[data-testid="record-loop"][data-loop="revise"]');
  await expect(loop).toHaveAttribute("data-exit", "open");
  await expect(loop.getByTestId("loop-exit")).toContainText("inside it");
  const failed = loop.locator('[data-testid="aggregation"][data-name="all_hold"]').first();
  await expect(failed).toHaveAttribute("data-value", "false");
  await expect(failed).toContainText("no confidence");
  await fill(fix, "work", "Thank you for renewing your subscription.");
  await answer(fix);
  await done(page);

  await expect(loop).toHaveAttribute("data-exit", "until");
  await expect(loop).toHaveAttribute("data-passes", "2");
  await expect(loop.getByTestId("loop-exit")).toContainText("its Until condition held at summarize_check, after 2 passes");
  const passes = loop.getByTestId("record-pass");
  await expect(passes.nth(0).getByTestId("until")).toContainText("not in the state yet");
  await expect(passes.nth(1).getByTestId("until")).toContainText("check_summary.all_hold was false");
  await expect(passes.nth(0).locator('[data-testid="record-entry"]')).toHaveCount(3);     // check, summarize_check, fix
  await expect(passes.nth(1).locator('[data-testid="record-entry"]')).toHaveCount(2);     // check, summarize_check: it held
  await expect(page.getByTestId("run-timing")).toContainText("waiting on agents");
});

test("a loop at its cap: the last fix is announced, and the failure is not retried", async ({ page }) => {
  await start(page, FIXED, { request: "A note." });
  const draft = await pausedAt(page, "draft");
  await fill(draft, "work", "You fools. [break:courteous]");
  await answer(draft);
  for (const pass of [0, 1, 2]) {
    const fix = page.locator('[data-testid="pause-task"][data-step="fix"]');
    await expect(task(fix, 0)).toHaveAttribute("data-pass", String(pass), { timeout: 30_000 });
    await expect(task(fix, 0).getByTestId("last-pass")).toHaveCount(pass === 2 ? 1 : 0);
    await fill(fix, "work", `Still rude, take ${pass}. [break:courteous]`);
    await answer(fix);
  }
  const error = page.getByTestId("run-error");
  await expect(error).toHaveAttribute("data-kind", "loop_cap", { timeout: 30_000 });
  await expect(page.getByTestId("retry")).toHaveCount(0);
  const loop = page.locator('[data-testid="record-loop"][data-loop="revise"]');
  await expect(loop).toHaveAttribute("data-exit", "cap");
  await expect(loop.getByTestId("loop-exit")).toContainText("reached its cap after 3 passes");
});

test("a batch: the passes waiting at one step are one pause, answered together", async ({ page }) => {
  const tickets = ["Can I get a copy of my March invoice? [calm]", "Third double charge this year! [angry]", "How do I move to the annual plan? [calm]"];
  await start(page, TRIAGE, { tickets: JSON.stringify(tickets), policy: "Duplicate charges are refunded within 5 business days." });
  const drafts = await pausedAt(page, "draft");
  await expect(drafts).toHaveAttribute("data-tasks", "2");
  await expect(drafts.getByTestId("batched-note")).toContainText("answered together");
  // The angry ticket was escalated by the script and finished its pass; the two calm ones wait, as passes 0 and 2.
  await expect(task(drafts, 0)).toHaveAttribute("data-pass", "0");
  await expect(task(drafts, 1)).toHaveAttribute("data-pass", "2");
  await expect(task(drafts, 1).getByTestId("pause-state")).toContainText("annual plan");

  // The check script passes a reply that quotes the policy's first sentence, so neither pass needs a fix.
  await fill(task(drafts, 0), "reply", "Your March invoice is attached. Duplicate charges are refunded within 5 business days.");
  await fill(task(drafts, 1), "reply", "The annual plan starts at your next cycle. Duplicate charges are refunded within 5 business days.");
  await drafts.getByRole("button", { name: "Answer all 2" }).click();

  await pausedAt(page, "summarize");
  const loop = page.locator('[data-testid="record-loop"][data-loop="each_ticket"]');
  await expect(loop).toHaveAttribute("data-exit", "items");
  await expect(loop.getByTestId("record-pass")).toHaveCount(3);
  await expect(loop.locator('[data-testid="record-entry"][data-step="draft"]')).toHaveCount(2);
  await expect(loop.locator('[data-testid="record-entry"][data-step="escalate"]')).toHaveCount(1);
});

test("a For of decisions goes to the model in one call, and the record says so", async ({ page }) => {
  await start(page, DYNAMIC, { task: "Write a note.", policies: JSON.stringify(["be polite", "be short", "use no names"]) });
  const draft = await pausedAt(page, "draft");
  await fill(draft, "work", "A very long draft. [break:short]");
  await answer(draft);
  const fix = await pausedAt(page, "fix");
  const review = page.locator('[data-testid="record-loop"][data-loop="review"]').first();
  await expect(review.getByTestId("record-pass")).toHaveCount(3);
  await expect(review.locator('[data-testid="record-entry"][data-step="check"]').first().getByTestId("batched")).toContainText("one call for 3 passes");
  await expect(review.locator('[data-testid="answer"][data-name="follows"]')).toHaveCount(3);
  await expect(review.locator('[data-testid="answer"][data-name="follows"][data-value="false"]')).toHaveCount(1);
  await fill(fix, "work", "A short draft.");
  await answer(fix);
  await done(page);
});

test("inputs the Start step refuses open no run", async ({ page }) => {
  await page.goto(`./#/run/${TRIAGE}`);
  const form = page.getByTestId("pause-start");
  await expect(form).toBeVisible({ timeout: 30_000 });
  await fill(form, "tickets", "not json");
  await fill(form, "policy", "p");
  await page.getByTestId("pause-start-submit").click();
  await expect(form.getByRole("alert")).toContainText("tickets: not JSON");
  await expect(page.getByTestId("run-status")).toHaveText("not started");

  // A list of the wrong things gets as far as the CLI, which names the key.
  await fill(form, "tickets", '"one ticket, not a list"');
  await page.getByTestId("pause-start-submit").click();
  await expect(page.getByTestId("run-error")).toHaveAttribute("data-kind", "invalid_input", { timeout: 30_000 });
  await expect(page.getByTestId("run-id")).toHaveCount(0);
  await expect(form).toBeVisible();
});
