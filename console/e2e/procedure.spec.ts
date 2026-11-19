import { expect, test } from "@playwright/test";
import { AGENT, BILLING } from "./aip";

// The procedure page (the step graph, its main view, is graph.spec.ts): what `aip info` says, a step
// opened with the lines of procedure.aip that wrote it, and the revisions. The card canvas that was a
// fourth mode here went at C4.

const node = (page: import("@playwright/test").Page, step: string) => page.locator(`[data-testid="step-node"][data-step="${step}"]`);

test("what aip info says beside the steps, and a step opened with the lines that wrote it", async ({ page }) => {
  await page.goto(`./#/p/${BILLING}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`${BILLING} @1`);
  await expect(page.getByRole("radio", { name: "cards" })).toHaveCount(0);
  await expect(page.getByTestId("inputs")).toContainText("message");
  await expect(page.getByTestId("result")).toContainText("reply");
  await expect(page.getByTestId("requires")).toContainText("python");
  await expect(page.getByRole("heading", { name: "Use when", exact: true })).toBeVisible();

  await node(page, "by_tone").click();
  const detail = page.getByTestId("step-detail");
  await expect(detail).toHaveAttribute("data-name", "by_tone");
  await expect(detail).toContainText("routes on");
  const source = detail.getByTestId("step-source");
  await expect(source).toContainText("Route On by_tone");
  await expect(source).toContainText("Confidence_Below 0.9 -> escalate");
  await expect(source).not.toContainText("Execute escalate");
  // The slice is coloured by the shipped grammar, and numbered from its own first line.
  await expect(source.locator('[data-scope="keyword.control.step.aip"]')).toHaveText("Route");
  expect(Number(await source.getAttribute("data-first-line"))).toBeGreaterThan(20);
  await detail.getByRole("button", { name: "close" }).click();
  await expect(detail).toHaveCount(0);
});

test("the agent's version of the same procedure says an agent steers the route", async ({ page }) => {
  await page.goto(`./#/p/${AGENT}`);
  await expect(node(page, "triage")).toHaveAttribute("data-kind", "Task_Agent");
  await page.getByRole("radio", { name: "data flow" }).check();
  await expect(page.locator('[data-testid="data-flow-row"][data-key="tone"]').getByTestId("source-class")).toHaveText("agent");
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
