import { expect, test } from "@playwright/test";
import { AGENT, BILLING, DRAFT_DIR, FIXED, resume, run } from "./aip";
import { entry } from "./pages";

// History: the runs the server holds, whoever made them. These are made through the CLI as two agents in
// two sessions, one of them from a folder that was never published, so its run is a draft's.

const ids: Record<string, string> = {};

test.beforeAll(() => {
  const claude = { agent: "claude", session: "history-s1" };
  const codex = { agent: "codex", session: "history-s2" };

  // claude, by name: the model is unsure, the route's check fires, the script opens a ticket.
  ids.fired = run(BILLING, { message: "Two charges, I think? [calm] [unsure]" }, claude).run_id as string;

  // claude again, the agent classifies and drafts: a run with two answered tasks.
  let paused = run(AGENT, { message: "When is my invoice due?" }, claude);
  paused = resume(paused.run_id as string, { billing: true, tone: "calm" }, claude);
  ids.calm = resume(paused.run_id as string, { reply: "On the 1st." }, claude).run_id as string;

  // codex, from a folder nobody published: a draft, left waiting at its first task.
  ids.draft = run(DRAFT_DIR, { message: "A draft's run." }, codex).run_id as string;

  // codex, a loop that takes two passes.
  paused = run(FIXED, { request: "A note." }, codex);
  paused = resume(paused.run_id as string, { work: "Hey you. [break:courteous]" }, codex);
  ids.loop = resume(paused.run_id as string, { work: "Dear customer, thank you." }, codex).run_id as string;
});

const row = (id: string) => `[data-testid="run-row"][data-run-id="${id}"]`;

test("history lists the runs with who made them, and filters by agent, session and draft", async ({ page }) => {
  await page.goto("./#/runs");
  await expect(page.locator(row(ids.fired))).toHaveAttribute("data-agent", "claude");
  await expect(page.locator(row(ids.loop))).toHaveAttribute("data-session", "history-s2");
  await expect(page.locator(row(ids.draft)).getByTestId("draft-badge")).toBeVisible();
  await expect(page.locator(row(ids.calm)).getByTestId("draft-badge")).toHaveCount(0);

  // By agent, typed in.
  const filters = page.getByTestId("run-filters");
  await filters.getByLabel("agent", { exact: true }).fill("claude");
  await filters.getByLabel("agent", { exact: true }).press("Enter");
  await expect(page).toHaveURL(/#\/runs\?agent=claude$/);
  await expect(page.locator(row(ids.fired))).toBeVisible();
  await expect(page.locator(row(ids.calm))).toBeVisible();
  await expect(page.locator(row(ids.loop))).toHaveCount(0);
  await expect(page.locator('[data-testid="run-row"]:not([data-agent="claude"])')).toHaveCount(0);

  // By session, from a row: the address carries the filter, so it can be shared.
  await page.goto("./#/runs");
  await page.locator(row(ids.loop)).getByRole("button", { name: "history-s2" }).click();
  await expect(page).toHaveURL(/session=history-s2/);
  await expect(page.locator(row(ids.draft))).toBeVisible();
  await expect(page.locator(row(ids.fired))).toHaveCount(0);

  // Drafts only, then published only.
  await page.goto("./#/runs");
  await page.getByTestId("run-filters").getByLabel("draft").selectOption("true");
  await expect(page).toHaveURL(/draft=true/);
  await expect(page.locator(row(ids.draft))).toBeVisible();
  await expect(page.locator('[data-testid="run-row"][data-draft="false"]')).toHaveCount(0);
  await page.getByTestId("run-filters").getByLabel("draft").selectOption("false");
  await expect(page.locator(row(ids.fired))).toBeVisible();
  await expect(page.locator(row(ids.draft))).toHaveCount(0);

  // By procedure and status.
  await page.goto(`./#/runs?name=${FIXED}&status=done`);
  await expect(page.locator(row(ids.loop))).toBeVisible();
  await expect(page.locator(row(ids.fired))).toHaveCount(0);
  await page.goto("./#/runs?agent=nobody");
  await expect(page.getByTestId("no-runs")).toBeVisible();
});

test("a run's page answers what the raw record leaves a reader to work out", async ({ page }) => {
  await page.goto(`./#/runs/${ids.fired}`);
  await expect(page.getByTestId("run-status")).toHaveText("done");
  await expect(page.getByTestId("run-agent")).toHaveText("claude");
  await expect(page.getByTestId("run-session")).toHaveText("history-s1");
  await expect(page.getByTestId("run-timing")).toContainText("the model");

  // Each step says how long it took; the decision says which model answered and how sure it was.
  await expect(page.locator('[data-testid="record-entry"]')).toHaveCount(5);
  await expect(entry(page, "triage").getByTestId("entry-time")).toHaveText(/^\+\d/);
  await expect(entry(page, "triage").getByTestId("answered-by")).toContainText("e2e-1");
  await expect(entry(page, "triage").locator('[data-testid="answer"][data-name="tone"]')).toContainText("0.55");

  // The route went to escalate although the value was calm, and says why.
  const route = entry(page, "by_tone");
  await expect(route.getByTestId("route-to")).toHaveText("escalate");
  await expect(route.getByTestId("check")).toHaveAttribute("data-fired", "true");
  await expect(route.getByTestId("check")).toContainText("0.55 is below 0.9");
  await expect(route).toContainText("because its check fired");

  // What a step read and produced is one click away.
  await entry(page, "escalate").getByText("read and produced").click();
  await expect(entry(page, "escalate").getByTestId("entry-result")).toContainText("ticket_id");
  await expect(page.getByTestId("run-result")).toContainText("tier2");
});

test("who answered each task, and the passes of a loop under the loop", async ({ page }) => {
  await page.goto(`./#/runs/${ids.calm}`);
  const triage = entry(page, "triage").getByTestId("answered-by");
  await expect(triage).toHaveAttribute("data-agent", "claude");
  await expect(triage).toHaveAttribute("data-session", "history-s1");
  await expect(triage).toContainText("after");

  await page.goto(`./#/runs/${ids.loop}`);
  const loop = page.locator('[data-testid="record-loop"][data-loop="revise"]');
  await expect(loop).toHaveAttribute("data-exit", "until");
  await expect(loop.getByTestId("record-pass")).toHaveCount(2);
  await expect(loop.getByTestId("record-pass").nth(0).getByTestId("until")).toHaveAttribute("data-holds", "false");
  await expect(loop.getByTestId("record-pass").nth(0).locator('[data-testid="record-entry"][data-step="fix"]')).toHaveCount(1);
  await expect(loop.getByTestId("loop-exit")).toContainText("after 2 passes");
  // Outside the loop: start, draft, end.
  await expect(page.locator('[data-testid="record"] > [data-testid="record-entry"]')).toHaveCount(3);

  // The procedure, with what the run went through marked.
  await page.getByTestId("show-run-canvas").click();
  await expect(page.locator('[data-testid="canvas-card"].visited')).toHaveCount(6);
  await expect(page.locator('[data-testid="canvas-frame"][data-loop="revise"]')).toHaveClass(/visited/);
});

test("a draft's run wears the badge, shows where it waits, and opens the bundle it ran", async ({ page }) => {
  await page.goto(`./#/runs/${ids.draft}`);
  await expect(page.getByRole("heading", { level: 1 }).getByTestId("draft-badge")).toBeVisible();
  await expect(page.getByTestId("run-status")).toHaveText("paused");
  const pause = page.getByTestId("run-pause");
  await expect(pause).toHaveAttribute("data-step", "triage");
  await expect(pause.getByTestId("waiting-task")).toContainText("billing");

  await page.getByRole("link", { name: "procedure", exact: true }).click();
  await expect(page).toHaveURL(/#\/p\/bundle%3A[0-9a-f]{64}$/);
  await expect(page.getByTestId("draft-note")).toContainText("no revision");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(AGENT);
  await expect(page.getByTestId("step-node")).toHaveCount(6);
});
