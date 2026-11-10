import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { BILLING, E2E, TRIAGE, resume, run } from "./aip";
import { card } from "./pages";

// The step graph: the procedure page's main view, in its modes (control flow, data flow, run traffic, and
// the card canvas as the fourth), drawn down or to the right; and a run's path drawn over it. Each mode
// is photographed into .aip-e2e/screenshots/ on the way.

const SHOTS = path.join(E2E, "screenshots");
const POLICY = "Duplicate charges are refunded within 5 business days.";
const ids: Record<string, string> = {};

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
  const who = { agent: "graph-spec", session: "graph-s1" };

  // billing_support: one run the check sends to a person, one that goes there by its value, one left waiting at the reply.
  run(BILLING, { message: "Two charges, I think? [calm] [unsure]" }, who);
  ids.angry = run(BILLING, { message: "Third double charge this year! [angry]" }, who).run_id as string;
  run(BILLING, { message: "Could you explain the $12 on my bill? [calm]" }, who);

  // ticket_triage, three tickets: the For runs three passes. The angry one is escalated by the script; the
  // two calm ones wait at `draft` together. One reply quotes the policy and passes the check; the other does
  // not, so its pass goes round the inner loop once (`fix`, then `Again check`).
  const tickets = ["Can I get a copy of my March invoice? [calm]", "Third double charge this year! [angry]", "How do I move to the annual plan? [calm]"];
  let paused = run(TRIAGE, { tickets, policy: POLICY }, who);
  ids.drafting = paused.run_id as string;
  // A second run of the same, taken further: this one is left waiting at `draft`.
  paused = run(TRIAGE, { tickets, policy: POLICY }, who);
  ids.triage = paused.run_id as string;
  paused = resume(ids.triage, { "0": { reply: `Your March invoice is attached. ${POLICY}` }, "1": { reply: "The annual plan starts at your next cycle." } }, who);
  if (paused.step !== "fix") throw new Error(`the reply that does not quote the policy should wait at fix, and the run said: ${JSON.stringify(paused)}`);
  paused = resume(ids.triage, { reply: `The annual plan starts at your next cycle. ${POLICY}` }, who);
  if (paused.step !== "summarize") throw new Error(`after the fix the run should wait at summarize, and said: ${JSON.stringify(paused)}`);
});

const steps = (page: Page) => page.getByTestId("steps");
const graph = (page: Page | Locator) => page.getByTestId("step-graph");
const node = (page: Page | Locator, step: string) => page.locator(`[data-testid="step-node"][data-step="${step}"]`);
const frame = (page: Page | Locator, loop: string) => page.locator(`[data-testid="graph-frame"][data-loop="${loop}"]`);
const edge = (page: Page | Locator, from: string, to: string) => page.locator(`[data-testid="step-edge"][data-from="${from}"][data-to="${to}"]`);
const mode = (page: Page, name: string) => steps(page).getByRole("radiogroup", { name: "graph" }).getByRole("radio", { name });
const direction = (page: Page | Locator, name: "down" | "right") => page.getByTestId("direction").getByRole("radio", { name });
const shot = (target: Locator, name: string) => target.screenshot({ path: path.join(SHOTS, `${name}.png`) });

/** Whether `inner` is drawn inside `outer`. */
async function inside(inner: Locator, outer: Locator): Promise<boolean> {
  const i = (await inner.boundingBox())!, o = (await outer.boundingBox())!;
  return i.x >= o.x && i.y >= o.y && i.x + i.width <= o.x + o.width && i.y + i.height <= o.y + o.height;
}

test("billing-support: control flow is the page's main view, with the route's branches on its arrows", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}`);
  await expect(steps(page)).toHaveAttribute("data-view", "control");
  await expect(mode(page, "control flow")).toBeChecked();
  await expect(graph(page)).toHaveAttribute("data-mode", "control");
  await expect(page.getByTestId("step-node")).toHaveCount(6);
  await expect(page.getByTestId("canvas")).toHaveCount(0);
  await expect(node(page, "triage")).toHaveAttribute("data-kind", "Decide");
  await expect(node(page, "by_tone")).toHaveAttribute("data-kind", "Route");

  // The check and the `angry` branch lead to the same step: one arrow that names both.
  await expect(edge(page, "by_tone", "escalate")).toHaveAttribute("data-kinds", "below branch");
  await expect(edge(page, "by_tone", "escalate").getByTestId("branch-label")).toHaveText("< 0.9 · angry");
  await expect(edge(page, "by_tone", "reply").getByTestId("branch-label")).toHaveText("calm");
  await expect(page.getByTestId("step-edge")).toHaveCount(6);

  // A node opens the step: what it reads and asks, and the lines of procedure.aip that wrote it.
  await node(page, "triage").click();
  const detail = page.getByTestId("step-detail");
  await expect(detail).toHaveAttribute("data-name", "triage");
  await expect(detail).toContainText("tone: choice [angry, calm]");
  await expect(detail.getByTestId("step-source")).toContainText("Decide triage");
  await detail.getByRole("button", { name: "close" }).click();
  await expect(detail).toHaveCount(0);
  await shot(steps(page), "billing-control-down");
});

test("billing-support: data flow draws who produces each key and who reads it, and says whose answer steers the route", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}`);
  await mode(page, "data flow").check();
  await expect(page).toHaveURL(/\?view=data$/);
  await expect(graph(page)).toHaveAttribute("data-mode", "data");
  const carries = (from: string, to: string) => page.locator(`[data-testid="data-edge"][data-from="${from}"][data-to="${to}"]`);
  await expect(carries("start", "triage")).toHaveAttribute("data-keys", "message");
  await expect(carries("triage", "by_tone")).toHaveAttribute("data-keys", "triage_decision");
  await expect(carries("start", "escalate")).toHaveAttribute("data-keys", "message");
  await expect(page.getByTestId("step-edge")).toHaveCount(6);         // the control edges stay, faint

  const row = (key: string) => page.locator(`[data-testid="data-flow-row"][data-key="${key}"]`);
  await expect(row("message")).toHaveAttribute("data-from", "start");
  await expect(row("triage_decision")).toHaveAttribute("data-from", "triage");
  const read = row("triage_decision").locator('[data-testid="key-read"][data-node="by_tone"]');
  await expect(read).toContainText(".tone");
  await expect(read.getByTestId("source-class")).toHaveText("measured");
  await expect(row("ticket_id")).toHaveAttribute("data-to", "end");

  // A key, or a step, picked: its arrows stand out from the rest.
  await row("triage_decision").getByRole("button", { name: "triage_decision" }).click();
  await expect(carries("triage", "by_tone")).toHaveAttribute("data-lit", "true");
  await expect(carries("start", "triage")).toHaveAttribute("data-lit", "false");
  await node(page, "start").click();
  await expect(carries("start", "triage")).toHaveAttribute("data-lit", "true");
  await expect(carries("triage", "by_tone")).toHaveAttribute("data-lit", "false");
  await node(page, "start").click();
  await expect(carries("start", "triage")).not.toHaveAttribute("data-lit");
  await shot(steps(page), "billing-data-down");
});

test("billing-support: run traffic weights the arrows by the runs that took them", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}?view=traffic`);
  await expect(mode(page, "run traffic")).toBeChecked();
  const summary = page.getByTestId("traffic-summary");
  await expect(summary).toBeVisible({ timeout: 30_000 });
  const runs = Number(await summary.getAttribute("data-runs"));
  expect(runs).toBeGreaterThanOrEqual(3);
  await expect(graph(page)).toHaveAttribute("data-mode", "traffic");

  // Every run went through triage; each took one branch of the route, so the two add up.
  await expect(node(page, "triage").getByTestId("step-runs")).toHaveAttribute("data-runs", String(runs));
  const to = async (step: string) => Number(await edge(page, "by_tone", step).getAttribute("data-runs"));
  expect(await to("escalate")).toBeGreaterThanOrEqual(2);
  expect(await to("reply")).toBeGreaterThanOrEqual(1);
  expect((await to("escalate")) + (await to("reply"))).toBe(runs);
  await expect(edge(page, "by_tone", "escalate").getByTestId("edge-runs")).toHaveText(String(await to("escalate")));

  const table = page.getByRole("table", { name: "run traffic" });
  await expect(table.locator('[data-testid="traffic-row"][data-step="start"]')).toHaveAttribute("data-runs", String(runs));
  await expect(table.locator('[data-testid="traffic-row"][data-step="reply"]')).toHaveAttribute("data-runs", String(await to("reply")));
  await shot(steps(page), "billing-traffic-down");
});

test("billing-support: the cards are the fourth mode, and every mode draws down or to the right", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}`);
  // Down, the steps share the row with what `aip info` says; to the right they take the whole row.
  await expect(steps(page)).not.toHaveClass(/wide/);
  await expect(graph(page)).toHaveAttribute("data-direction", "down");
  const below = async (a: string, b: string) => (await node(page, b).boundingBox())!.y > (await node(page, a).boundingBox())!.y;
  const rightOf = async (a: string, b: string) => (await node(page, b).boundingBox())!.x > (await node(page, a).boundingBox())!.x;
  expect(await below("start", "end")).toBe(true);
  const narrow = (await steps(page).boundingBox())!.width;

  await direction(page, "right").check();
  await expect(graph(page)).toHaveAttribute("data-direction", "right");
  await expect(steps(page)).toHaveClass(/wide/);
  expect(await rightOf("start", "triage")).toBe(true);
  expect(await rightOf("by_tone", "end")).toBe(true);
  expect((await steps(page).boundingBox())!.width).toBeGreaterThan(narrow);
  await shot(steps(page), "billing-control-right");

  for (const [name, view] of [["data flow", "data"], ["run traffic", "traffic"]] as const) {
    await mode(page, name).check();
    await expect(graph(page)).toHaveAttribute("data-direction", "right");
    if (view === "traffic") await expect(page.getByTestId("traffic-summary")).toBeVisible({ timeout: 30_000 });
    await expect(graph(page)).toHaveAttribute("data-mode", view);
    expect(await rightOf("start", "end")).toBe(true);
    await shot(steps(page), `billing-${view}-right`);
  }

  // The cards: C1's canvas, a row when drawn to the right, a column down.
  await mode(page, "cards").check();
  await expect(page).toHaveURL(/\?view=cards$/);
  await expect(graph(page)).toHaveCount(0);
  await expect(page.getByTestId("canvas")).toHaveAttribute("data-direction", "right");
  await expect(page.getByTestId("canvas-card")).toHaveCount(6);
  const cardBox = async (step: string) => (await card(page, step).boundingBox())!;
  expect((await cardBox("triage")).x).toBeGreaterThan((await cardBox("start")).x);
  expect(Math.round((await cardBox("triage")).y)).toBe(Math.round((await cardBox("start")).y));
  await shot(steps(page), "billing-cards-right");
  await direction(page, "down").check();
  await expect(page.getByTestId("canvas")).toHaveAttribute("data-direction", "down");
  expect((await cardBox("triage")).y).toBeGreaterThan((await cardBox("start")).y);
  expect(Math.round((await cardBox("triage")).x)).toBe(Math.round((await cardBox("start")).x));
  await expect(steps(page)).toHaveClass(/wide/);                       // the canvas is wide either way
  await shot(steps(page), "billing-cards-down");

  // The direction is the viewer's: it is remembered on the next page.
  await direction(page, "right").check();
  await page.goto(`./#/p/${TRIAGE}`);
  await expect(graph(page)).toHaveAttribute("data-direction", "right");
  await direction(page, "down").check();
  await expect(graph(page)).toHaveAttribute("data-direction", "down");
});

test("ticket-triage: loops are frames around their bodies, with Continue and Again as arrows of their own", async ({ page }) => {
  await page.goto(`./#/p/${TRIAGE}`);
  await expect(page.getByTestId("step-node")).toHaveCount(9);
  const outer = frame(page, "each_ticket"), inner = frame(page, "revise");
  await expect(outer).toHaveAttribute("data-kind", "For");
  await expect(inner).toHaveAttribute("data-kind", "Loop");
  await expect(outer).toContainText("Over tickets As ticket");
  expect(await inside(inner.locator("rect").first(), outer.locator("rect").first())).toBe(true);
  for (const step of ["classify", "by_tone", "draft", "escalate", "check", "fix"]) expect(await inside(node(page, step), outer.locator("rect").first())).toBe(true);
  for (const step of ["start", "summarize", "end"]) expect(await inside(node(page, step), outer.locator("rect").first())).toBe(false);
  expect(await inside(node(page, "fix"), inner.locator("rect").first())).toBe(true);
  expect(await inside(node(page, "check"), inner.locator("rect").first())).toBe(false);

  // Into the loop and out of it are arrows to and from the frame; the body's first step is entered from its head.
  await expect(edge(page, "start", "each_ticket")).toHaveCount(1);
  await expect(edge(page, "each_ticket", "classify")).toHaveAttribute("data-kinds", "enter");
  await expect(edge(page, "each_ticket", "summarize")).toHaveAttribute("data-kinds", "next");
  await expect(edge(page, "escalate", "each_ticket").getByTestId("branch-label")).toHaveText("continue");
  await expect(edge(page, "revise", "each_ticket")).toHaveAttribute("data-kinds", "continue");
  await expect(edge(page, "fix", "check").getByTestId("branch-label")).toHaveText("again");
  await expect(edge(page, "by_tone", "escalate").getByTestId("branch-label")).toHaveText("< 0.6 · angry");
  await shot(steps(page), "triage-control-down");

  // A frame's header opens the loop.
  await outer.locator(".frame-head").click();
  await expect(page.getByTestId("step-detail")).toHaveAttribute("data-name", "each_ticket");
  await expect(page.getByTestId("step-detail")).toContainText("Over tickets As ticket, At_Most 50, Collect reply Into replies");
  await expect(page.getByTestId("step-detail").getByTestId("step-source")).toContainText("For each_ticket");
});

test("ticket-triage: every mode, down and to the right", async ({ page }) => {
  await page.goto(`./#/p/${TRIAGE}?view=data`);
  const carries = (from: string, to: string) => page.locator(`[data-testid="data-edge"][data-from="${from}"][data-to="${to}"]`);
  // The For reads the list, hands each item to the steps of its body, and collects their replies.
  await expect(carries("start", "each_ticket")).toHaveAttribute("data-keys", "tickets");
  await expect(carries("each_ticket", "classify")).toHaveAttribute("data-keys", "ticket");
  await expect(carries("draft", "each_ticket")).toHaveAttribute("data-keys", "reply");
  await expect(carries("check", "revise")).toHaveAttribute("data-keys", "passed");
  await expect(carries("each_ticket", "summarize")).toHaveAttribute("data-keys", "replies");
  const row = (key: string) => page.locator(`[data-testid="data-flow-row"][data-key="${key}"]`);
  await expect(row("reply")).toHaveAttribute("data-from", "draft,escalate,fix");
  await expect(row("reply")).toContainText("on different paths");
  await expect(row("reply").locator('[data-testid="key-read"][data-node="each_ticket"]')).toHaveAttribute("data-how", "collects");
  await expect(row("classification").getByTestId("source-class")).toHaveText("measured");
  await shot(steps(page), "triage-data-down");

  await mode(page, "run traffic").check();
  const summary = page.getByTestId("traffic-summary");
  await expect(summary).toBeVisible({ timeout: 30_000 });
  const runs = Number(await summary.getAttribute("data-runs"));
  expect(runs).toBeGreaterThanOrEqual(2);
  await expect(frame(page, "each_ticket")).toHaveAttribute("data-runs", String(runs));
  // A run counts once on an arrow however many passes took it; both runs wait somewhere.
  await expect(edge(page, "classify", "by_tone")).toHaveAttribute("data-runs", String(runs));
  expect(Number(await edge(page, "fix", "check").getAttribute("data-runs"))).toBeGreaterThanOrEqual(1);
  const table = page.getByRole("table", { name: "run traffic" });
  expect(Number(await table.locator('[data-testid="traffic-row"][data-step="draft"]').getAttribute("data-waiting"))).toBeGreaterThanOrEqual(1);
  expect(Number(await table.locator('[data-testid="traffic-row"][data-step="summarize"]').getAttribute("data-waiting"))).toBeGreaterThanOrEqual(1);
  await shot(steps(page), "triage-traffic-down");

  await direction(page, "right").check();
  await expect(graph(page)).toHaveAttribute("data-direction", "right");
  await expect(steps(page)).toHaveClass(/wide/);
  const x = async (step: string) => (await node(page, step).boundingBox())!.x;
  expect(await x("classify")).toBeGreaterThan(await x("start"));
  expect(await x("summarize")).toBeGreaterThan(await x("fix"));
  expect(await inside(node(page, "fix"), frame(page, "revise").locator("rect").first())).toBe(true);
  await shot(steps(page), "triage-traffic-right");
  await mode(page, "data flow").check();
  await expect(carries("each_ticket", "classify")).toHaveCount(1);
  await shot(steps(page), "triage-data-right");
  await mode(page, "control flow").check();
  await expect(page).toHaveURL(new RegExp(`#/p/${TRIAGE}$`));
  await shot(steps(page), "triage-control-right");

  await mode(page, "cards").check();
  await expect(page.locator('[data-testid="canvas-frame"][data-loop="each_ticket"]')).toBeVisible();
  await shot(steps(page), "triage-cards-right");
  await direction(page, "down").check();
  await expect(page.getByTestId("canvas")).toHaveAttribute("data-direction", "down");
  await shot(steps(page), "triage-cards-down");
});

test("a run of ticket_triage whose For ran three passes: its path over the graph, beside its record", async ({ page }) => {
  await page.goto(`./#/runs/${ids.triage}`);
  await expect(page.getByTestId("run-status")).toHaveText("paused");
  const drawn = page.getByTestId("run-path");
  await expect(drawn).toHaveAttribute("data-waiting", "summarize", { timeout: 30_000 });
  await expect(graph(drawn)).toHaveAttribute("data-mode", "path");

  // Three passes entered the For's body and went through its first steps three times.
  await expect(edge(drawn, "each_ticket", "classify")).toHaveAttribute("data-times", "3");
  await expect(edge(drawn, "classify", "by_tone")).toHaveAttribute("data-times", "3");
  await expect(edge(drawn, "classify", "by_tone").getByTestId("edge-times")).toHaveText("×3");
  // Two calm tickets were drafted, the angry one escalated and its pass ended there.
  await expect(edge(drawn, "by_tone", "draft")).toHaveAttribute("data-times", "2");
  await expect(edge(drawn, "by_tone", "escalate")).toHaveAttribute("data-times", "1");
  await expect(edge(drawn, "escalate", "each_ticket")).toHaveAttribute("data-taken", "true");
  // One draft failed the check: its pass went round the inner loop once, so `check` ran three times in two passes.
  await expect(edge(drawn, "draft", "check")).toHaveAttribute("data-times", "2");
  await expect(edge(drawn, "revise", "fix")).toHaveAttribute("data-times", "1");
  await expect(edge(drawn, "fix", "check")).toHaveAttribute("data-times", "1");
  await expect(edge(drawn, "check", "revise")).toHaveAttribute("data-times", "3");
  await expect(edge(drawn, "revise", "each_ticket")).toHaveAttribute("data-times", "2");
  // The For is over and the run waits at the step after it; the end is not reached yet.
  await expect(edge(drawn, "each_ticket", "summarize")).toHaveAttribute("data-taken", "true");
  await expect(edge(drawn, "summarize", "end")).toHaveAttribute("data-taken", "false");
  await expect(node(drawn, "summarize")).toHaveAttribute("data-state", "waiting");
  await expect(node(drawn, "summarize").getByTestId("path-mark")).toHaveText("waiting here");
  await expect(node(drawn, "end")).toHaveAttribute("data-visited", "false");
  for (const step of ["start", "classify", "by_tone", "draft", "escalate", "check", "fix"]) await expect(node(drawn, step)).toHaveAttribute("data-visited", "true");
  await expect(frame(drawn, "each_ticket")).toHaveAttribute("data-visited", "true");
  await expect(frame(drawn, "revise")).toHaveAttribute("data-visited", "true");

  // Beside it, the record as C1 built it: the three passes under the For.
  const loop = page.locator('[data-testid="record-loop"][data-loop="each_ticket"]');
  await expect(loop.locator(':scope > [data-testid="record-pass"]')).toHaveCount(3);
  await expect(page.getByTestId("run-pause")).toHaveAttribute("data-step", "summarize");
  const beside = async () => (await page.locator(".run-record").boundingBox())!.x > (await drawn.boundingBox())!.x + 100;
  expect(await beside()).toBe(true);
  await shot(page.locator("article.history-run"), "triage-run-path-down");

  // To the right the graph takes the row and the record moves below it.
  await direction(page, "right").check();
  await expect(graph(drawn)).toHaveAttribute("data-direction", "right");
  expect(await beside()).toBe(false);
  expect((await page.locator(".run-record").boundingBox())!.y).toBeGreaterThan((await drawn.boundingBox())!.y);
  await shot(page.locator("article.history-run"), "triage-run-path-right");
  await direction(page, "down").check();
});

test("a run still inside its For waits at a step of the body; a finished one reaches the end", async ({ page }) => {
  await page.goto(`./#/runs/${ids.drafting}`);
  const drawn = page.getByTestId("run-path");
  await expect(drawn).toHaveAttribute("data-waiting", "draft", { timeout: 30_000 });
  await expect(node(drawn, "draft")).toHaveAttribute("data-state", "waiting");
  await expect(edge(drawn, "by_tone", "draft")).toHaveAttribute("data-times", "2");
  await expect(edge(drawn, "each_ticket", "summarize")).toHaveAttribute("data-taken", "false");
  await expect(node(drawn, "check")).toHaveAttribute("data-visited", "false");

  await page.goto(`./#/runs/${ids.angry}`);
  await expect(page.getByTestId("run-status")).toHaveText("done");
  await expect(node(drawn, "end")).toHaveAttribute("data-visited", "true");
  await expect(edge(drawn, "by_tone", "escalate")).toHaveAttribute("data-taken", "true");
  await expect(edge(drawn, "by_tone", "reply")).toHaveAttribute("data-taken", "false");
  await expect(node(drawn, "reply")).toHaveAttribute("data-visited", "false");
  await expect(drawn.getByTestId("path-mark")).toHaveCount(0);
});
