import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { AGENT_MODEL_REPORTED, E2E, SERVER, WORKDIR } from "./aip";
import { answer, done, entry, fill, pausedAt, pick, runIdOf } from "./pages";

// Run it from the Studio (plans C5, C6): a drafted procedure with one Execute and two Task_Agent steps is saved, and
// its Run button opens the run console on the saved draft, driven: the model (`aip agent --answer`, the stand-in
// e2e/agent.mjs) answers every task but the step the user ticks for a person, which stops for the form (nothing is
// ticked to begin with), and the record says who answered what. The scripts the model wrote are asked about once
// more before they first execute.

const BRIEF = "A refund approval procedure: a script checks the refund against the limit, the model summarizes it, and a person approves it.";
const NAME = "refund_approval";            // what the stand-in names a procedure drafted from an approval brief
const MARKER = path.join(WORKDIR, "limit-checked.txt");    // what the drafted script leaves when it runs

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(E2E, "screenshots", `${name}.png`), fullPage: true });

test.beforeEach(async ({ page }) => {
  await page.goto("./");
  await page.evaluate(() => localStorage.clear());
  rmSync(MARKER, { force: true });
});

test("a saved draft runs from the Studio: the person's step through the form, the other answered by the model", async ({ page, request }) => {
  // Drafted by the chat: a brief, the question it asks, the procedure it writes.
  await page.goto("./#/studio");
  await expect(page.getByTestId("studio-status")).toHaveText("compiles", { timeout: 30_000 });
  await expect(page.getByTestId("studio-run")).toBeDisabled();               // nothing saved, nothing to run
  await page.getByTestId("studio-message").fill(BRIEF);
  await page.getByTestId("studio-send").click();
  const turn = page.getByTestId("studio-turn").first();
  const asked = turn.getByTestId("studio-human");
  await expect(asked).toBeVisible({ timeout: 60_000 });
  await asked.getByLabel("answers", { exact: true }).fill("1. A manager approves every refund.");
  await asked.getByTestId("studio-answer").click();
  await expect(turn).toHaveAttribute("data-status", "done", { timeout: 90_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText(NAME);
  for (const step of ["check_limit", "summarize", "approve"]) {
    await expect(page.locator(`[data-testid="studio-graph"] [data-testid="step-node"][data-step="${step}"]`)).toBeVisible();
  }

  // Saved: the save asks about the script once, and Run comes on.
  await page.getByTestId("studio-save").click();
  await page.getByTestId("studio-scripts-ok").click();
  const saved = page.getByTestId("studio-saved");
  await expect(saved).toContainText(`Saved as a draft of ${NAME}`);
  const bundle = (await saved.getAttribute("data-bundle"))!;
  await expect(page.getByTestId("studio-run")).toBeEnabled();

  // The first real run asks again, naming the script and what the review said it touches: this is when it executes.
  await page.getByTestId("studio-run").click();
  const ask = page.getByTestId("studio-run-ask");
  await expect(ask.locator('[data-testid="studio-run-script"][data-path="scripts/check_limit.py"]'))
    .toContainText("the review says it writes limit-checked.txt in the working directory");
  expect(existsSync(MARKER)).toBe(false);
  const [run] = await Promise.all([page.waitForEvent("popup"), page.getByTestId("studio-run-ok").click()]);
  await expect(ask).toHaveCount(0);

  // The run console on the draft: driven, nothing ticked; the user ticks approve as the person's step.
  await expect(run.getByRole("heading", { level: 1 })).toContainText(NAME, { timeout: 30_000 });
  await expect(run.getByRole("heading", { level: 1 }).getByText("draft")).toBeVisible();
  const how = run.getByTestId("run-how");
  await expect(how).toHaveAttribute("data-mode", "agent");
  const approveStep = how.locator('[data-testid="person-step"][data-step="approve"] input');
  await expect(approveStep).not.toBeChecked();
  await expect(how.locator('[data-testid="person-step"][data-step="summarize"] input')).not.toBeChecked();
  await approveStep.check();
  await expect(run.getByTestId("run-agent")).toHaveText("studio");
  await fill(run.getByTestId("pause-start"), "request", "Please refund the 40 I paid twice for March.");
  await shot(run, "studio-run-start");
  await run.getByTestId("pause-start-submit").click();

  // The script ran, the model summarized, and the run stops at the person's step: a true_or_false is two buttons.
  const approve = await pausedAt(run, "approve");
  await expect(approve.getByTestId("pause-why")).toContainText("A step for a person");
  await expect(approve.locator('[data-testid="field"][data-key="approved"]').getByRole("radio")).toHaveCount(2);
  await expect(approve.getByTestId("answer-json")).toBeVisible();              // hand-typed JSON stays behind the form
  await expect(run.locator('[data-testid="trace"] li[data-step="summarize"]').first()).toBeVisible();
  await expect(run.locator('[data-testid="trace"] li[data-kind="model"][data-step="summarize"]')).toContainText("answered summarize");
  expect(existsSync(MARKER)).toBe(true);
  await shot(run, "studio-run-approve");
  await pick(approve, "approved", "true");
  await answer(approve);
  await done(run);
  // The person's answer, as an answer object: an agent's answer is `{value}` (spec 2.4).
  expect(JSON.parse((await run.getByTestId("run-result").textContent())!).approved).toEqual({ value: true });
  await expect(run.getByTestId("run-workdir")).toHaveText(WORKDIR);

  // Who answered what: both as the studio's; the model's answer names its model and what it spent, the person's none.
  const summarized = entry(run, "summarize").getByTestId("answered-by");
  await expect(summarized).toHaveAttribute("data-agent", "studio");
  await expect(summarized).toHaveAttribute("data-model", AGENT_MODEL_REPORTED);
  await expect(summarized).toHaveAttribute("data-work", "reported");
  await expect(entry(run, "approve").getByTestId("answered-by")).toHaveAttribute("data-agent", "studio");
  await expect(entry(run, "approve").getByTestId("answered-by")).not.toContainText(AGENT_MODEL_REPORTED);
  await shot(run, "studio-run-done");

  // Recorded as the studio's, against the draft the Studio saved, in History like any other run.
  const id = await runIdOf(run);
  const record = await (await request.get(`${SERVER}/runs/${id}`)).json();
  expect(record.identity.agent).toBe("studio");
  expect(record.draft).toBe(true);
  expect(record.bundle_id).toBe(bundle);
  const byStep = Object.fromEntries(record.history.map((e: { step: string }) => [e.step, e]));
  expect(byStep.summarize.answered_by).toMatchObject({ agent: "studio", model: AGENT_MODEL_REPORTED });
  expect(byStep.summarize.work).toBe("reported");
  expect(byStep.approve.answered_by.agent).toBe("studio");
  expect(byStep.approve.answered_by.model ?? null).toBeNull();
  expect(byStep.check_limit.kind).toBe("Execute");
  await run.close();

  // A later run of the same scripts does not ask again.
  const [again] = await Promise.all([page.waitForEvent("popup"), page.getByTestId("studio-run").click()]);
  await expect(page.getByTestId("studio-run-ask")).toHaveCount(0);
  await expect(again.getByTestId("run-how")).toBeVisible({ timeout: 30_000 });
  await again.close();
});
