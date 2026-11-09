import { expect, test } from "@playwright/test";
import { AGENT, BILLING, FIXED, TRIAGE } from "./aip";
import { card } from "./pages";

// The procedure page: the card canvas drawn from the revision's own graph, and what `aip info` says.

const port = (scope: ReturnType<typeof card>, label: string) => scope.locator(`[data-testid="canvas-port"][data-port="${label}"]`);

test("one card per step: its kind, its description as the title, what it reads and produces, where it leads", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`${BILLING} @1`);
  await expect(page.locator('[data-testid="canvas-card"]')).toHaveCount(6);

  const triage = card(page, "triage");
  await expect(triage).toHaveAttribute("data-kind", "Decide");
  await expect(triage.locator(".aipc-title")).toHaveText("Classify whether the message is about billing and how upset the customer is.");
  await expect(triage.locator('[data-section="reads"]')).toContainText("message");
  await expect(triage.locator('[data-section="asks"]')).toContainText("tone: choice [angry, calm]");
  await expect(triage.locator('[data-section="produces"]')).toContainText("triage_decision");
  // Its way out quotes the next step's description, not its name.
  await expect(port(triage, "next")).toHaveAttribute("data-target", "by_tone");
  await expect(port(triage, "next")).toContainText("Angry customers, and those the model is unsure of");

  // A route: one port per label, and one for its confidence check.
  const route = card(page, "by_tone");
  await expect(route.locator('[data-section="reads"]')).toContainText("triage_decision.tone");
  await expect(route.locator('[data-section="routes on"]')).toContainText("measured answer");
  await expect(route.locator('[data-testid="canvas-port"]')).toHaveCount(3);
  await expect(port(route, "confidence below 0.9")).toHaveAttribute("data-target", "escalate");
  await expect(port(route, "angry")).toHaveAttribute("data-target", "escalate");
  await expect(port(route, "calm")).toHaveAttribute("data-target", "reply");

  await expect(card(page, "escalate").locator('[data-section="runs"]')).toContainText("scripts/escalate.py");
  await expect(card(page, "start").locator('[data-section="inputs"]')).toContainText("message: string");
  await expect(card(page, "end").locator('[data-testid="canvas-port"]')).toHaveCount(0);

  // What `aip info` says, below the canvas.
  await expect(page.getByTestId("inputs")).toContainText("message");
  await expect(page.getByTestId("result")).toContainText("reply");
  await expect(page.getByTestId("requires")).toContainText("python");
  await expect(page.getByRole("heading", { name: "Use when" })).toBeVisible();
});

test("the agent's version of the same procedure shows who steers the route", async ({ page }) => {
  await page.goto(`./#/p/${AGENT}`);
  await expect(card(page, "triage")).toHaveAttribute("data-kind", "Task_Agent");
  await expect(card(page, "triage").locator('[data-section="produces"]')).toContainText("tone: choice [angry, calm]");
  const route = card(page, "by_tone");
  await expect(route.locator('[data-section="routes on"]')).toContainText("agent answer");
  await expect(route.locator('[data-testid="canvas-port"]')).toHaveCount(2);       // no confidence check on an agent's answer
});

test("clicking a card opens it with the lines of procedure.aip that wrote it; a port leads to its target", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}`);
  await card(page, "by_tone").locator(".aipc-title").click();
  const detail = page.getByTestId("canvas-detail");
  await expect(detail).toHaveAttribute("data-name", "by_tone");
  const source = detail.getByTestId("canvas-source");
  await expect(source).toContainText("Route On by_tone");
  await expect(source).toContainText("Confidence_Below 0.9 -> escalate");
  await expect(source).not.toContainText("Execute escalate");
  // The slice is coloured by the shipped grammar, and numbered from its own first line.
  await expect(source.locator('[data-scope="keyword.control.step.aip"]')).toHaveText("Route");
  expect(Number(await source.getAttribute("data-first-line"))).toBeGreaterThan(20);

  await card(page, "by_tone").locator('[data-testid="canvas-port"][data-port="calm"]').click();
  await expect(detail).toHaveAttribute("data-name", "reply");
  await expect(card(page, "reply")).toHaveClass(/open/);
  await detail.getByRole("button", { name: "close" }).click();
  await expect(detail).toHaveCount(0);
});

test("loops are frames around their cards, and the canvas pans, zooms and fits", async ({ page }) => {
  await page.goto(`./#/p/${FIXED}`);
  const frame = page.locator('[data-testid="canvas-frame"][data-loop="revise"]');
  await expect(frame).toContainText("Until check_summary.all_hold, At_Most 3, Else_Fail");
  await expect(frame.locator('[data-testid="canvas-port"][data-port="next"]')).toHaveAttribute("data-target", "end");
  await expect(card(page, "fix").locator('[data-testid="canvas-port"][data-port="continue"]')).toContainText("the next pass of revise");
  await expect(card(page, "summarize_check").locator('[data-section="aggregates"]')).toContainText("all_hold: All policy_check With Confidence_Above 0.7");

  // The frame holds its three cards and not the ones outside it.
  const inside = async (step: string) => {
    const f = (await frame.boundingBox())!, c = (await card(page, step).boundingBox())!;
    return c.x >= f.x && c.y >= f.y && c.x + c.width <= f.x + f.width && c.y + c.height <= f.y + f.height;
  };
  for (const step of ["check", "summarize_check", "fix"]) expect(await inside(step)).toBe(true);
  for (const step of ["draft", "end"]) expect(await inside(step)).toBe(false);

  const zoom = page.getByTestId("canvas-zoom");
  const before = await zoom.textContent();
  await page.getByRole("button", { name: "zoom in" }).click();
  await expect(zoom).not.toHaveText(before!);
  const world = page.getByTestId("canvas-world");
  const moved = (await world.boundingBox())!;
  await page.mouse.move(moved.x + 5, moved.y + 5);
  // Dragging the background pans; the click that ends the drag opens nothing.
  const view = (await page.locator(".aipc-view").boundingBox())!;
  await page.mouse.move(view.x + view.width - 30, view.y + view.height - 30);
  await page.mouse.down();
  await page.mouse.move(view.x + view.width - 130, view.y + view.height - 90, { steps: 5 });
  await page.mouse.up();
  const after = (await world.boundingBox())!;
  expect(Math.round(after.x - moved.x)).toBe(-100);
  await expect(page.getByTestId("canvas-detail")).toHaveCount(0);
  await page.getByTestId("canvas-fit").click();
  await expect(zoom).toHaveText(before!);
});

test("nested loops nest: a Loop inside a For, with the For's header and an Again port", async ({ page }) => {
  await page.goto(`./#/p/${TRIAGE}`);
  const outer = page.locator('[data-testid="canvas-frame"][data-loop="each_ticket"]');
  const inner = page.locator('[data-testid="canvas-frame"][data-loop="revise"]');
  await expect(outer).toHaveAttribute("data-kind", "For");
  await expect(outer).toContainText("Over tickets As ticket, At_Most 50, Collect reply Into replies");
  const o = (await outer.boundingBox())!, i = (await inner.boundingBox())!;
  expect(i.x > o.x && i.y > o.y && i.x + i.width < o.x + o.width && i.y + i.height < o.y + o.height).toBe(true);
  await expect(card(page, "fix").locator('[data-testid="canvas-port"][data-port="again"]')).toHaveAttribute("data-target", "check");
  await expect(card(page, "by_tone").locator('[data-testid="canvas-port"]')).toHaveCount(3);
});

test("revisions: what the name runs, pin and retire", async ({ page }) => {
  await page.goto(`./#/p/${AGENT}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`${AGENT} @2`);
  const revisions = page.getByTestId("revisions");
  await expect(revisions.getByTestId("resolves")).toHaveText("2");
  await expect(revisions.getByTestId("revision-row")).toHaveCount(2);

  await revisions.locator('[data-revision="1"]').getByTestId("pin").click();
  await expect(revisions.getByTestId("resolves")).toHaveText("1");
  await expect(revisions.locator('[data-revision="1"]').getByTestId("pinned-tag")).toBeVisible();
  await page.goto("./#/");
  await expect(page.locator(`[data-testid="catalog-row"][data-name="${AGENT}"]`)).toContainText("@1 (pinned)");

  await page.goto(`./#/p/${AGENT}`);
  await page.getByTestId("revisions").locator('[data-revision="1"]').getByTestId("unpin").click();
  await expect(page.getByTestId("revisions").getByTestId("resolves")).toHaveText("2");
});
