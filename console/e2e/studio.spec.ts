import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { BILLING, E2E, SERVER, TRIAGE, folderOf } from "./aip";
import { card } from "./pages";

// The Studio (plan C2): the card canvas as an editor. Every change is a text edit of procedure.aip that the
// console's process formats and compiles; the compiler's diagnostics are drawn on the cards while a change is
// half done, and only what compiles is saved, as a draft the server holds with no revision.

const status = (page: Page) => page.getByTestId("studio-status");
/** A picture of the page, into .aip-e2e/screenshots/ as graph.spec.ts does. */
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(E2E, "screenshots", `${name}.png`), fullPage: true });

async function openStudio(page: Page, ref?: string) {
  await page.goto(ref ? `./#/studio/${encodeURIComponent(ref)}` : "./#/studio");
  await expect(status(page)).toHaveText("compiles", { timeout: 30_000 });
  await page.getByTestId("studio-view-source").check();
}

test.beforeEach(async ({ page }) => {
  // Unsaved edits are kept per browser; each test starts from what the server holds.
  await page.goto("./");
  await page.evaluate(() => localStorage.clear());
});

test("billing-support: add a Task_Agent card, connect the calm branch to it, save a draft", async ({ page, request }) => {
  const original = readFileSync(path.join(folderOf("billing-support"), "procedure.aip"), "utf8");
  await page.goto(`./#/p/${BILLING}@1`);
  await page.getByTestId("open-studio").click();
  await expect(status(page)).toHaveText("compiles", { timeout: 30_000 });
  await expect(page.getByTestId("studio-source")).toHaveCount(0);
  await page.getByTestId("studio-view-source").check();

  await page.getByTestId("canvas-add").click();
  const add = page.getByTestId("card-add");
  await add.getByTestId("add-kind").selectOption("Task_Agent");
  await add.getByTestId("add-description").fill("Review the drafted reply before it is sent.");
  await add.getByTestId("add-after").selectOption("step:by_tone");
  await add.getByTestId("add-next").selectOption("reply");
  await add.getByTestId("add-submit").click();

  // Half done: the card is there and nothing reaches it, which the compiler says on the card.
  const added = card(page, "review_drafted_reply");
  await expect(status(page)).toHaveText("1 error");
  await expect(added).toHaveAttribute("data-problems", "1");
  await expect(added.locator('[data-section="problems"]')).toContainText("unreachable_step");
  await expect(page.getByTestId("studio-diagnostics").locator('[data-code="unreachable_step"]')).toBeVisible();
  await expect(page.getByTestId("studio-save")).toBeDisabled();
  await page.getByTestId("studio-view-source").uncheck();
  await shot(page, "studio-half-done");
  await page.getByTestId("studio-view-source").check();

  // The route's calm branch to the new card: the diagnostics clear.
  await card(page, "by_tone").click();
  const calm = page.getByTestId("card-form").locator('[data-testid="form-port"][data-port="calm"]');
  await calm.getByTestId("port-target").selectOption("review_drafted_reply");
  await expect(status(page)).toHaveText("compiles");
  await expect(page.getByTestId("studio-diagnostics")).toHaveCount(0);
  await expect(card(page, "review_drafted_reply")).not.toHaveAttribute("data-problems");
  await expect(page.getByTestId("studio-source")).toContainText("calm  -> review_drafted_reply");
  await shot(page, "studio-connected");

  await page.getByTestId("studio-save").click();
  const saved = page.getByTestId("studio-saved");
  await expect(saved).toContainText("Saved as a draft of billing_support");
  const bundleId = (await saved.getAttribute("data-bundle"))!;

  // The draft's procedure.aip is the original, the formatted new block, and the rewritten branch line.
  const draft = await (await request.get(`${SERVER}/bundles/${bundleId}/graph`)).json();
  expect([draft.name, draft.revision, draft.draft]).toEqual(["billing_support", null, true]);
  const source = draft.graph.nodes.find((n: { labels: string[] }) => n.labels.includes("Procedure")).properties.source as string;
  const block = 'Task_Agent review_drafted_reply "Review the drafted reply before it is sent." {\n  Next_Step reply\n}\n\n';
  const expected = original.replace("  calm  -> reply\n", "  calm  -> review_drafted_reply\n").replace("\nExecute escalate", `\n${block}Execute escalate`);
  expect(source).not.toBe(original);
  expect(source).toBe(expected);
  // It is a draft: not in the catalog, and the name still resolves to revision 1.
  const catalog = await (await request.get(`${SERVER}/catalog`)).json();
  expect(catalog.find((c: { name: string }) => c.name === BILLING).resolves).toBe("1");
  await saved.getByRole("link").click();
  await expect(page.getByTestId("draft-note")).toBeVisible();
});

test("a new procedure: renamed, an input added and read, saved, then published", async ({ page, request }) => {
  await openStudio(page);
  await page.getByTestId("studio-name").fill("studio_made");
  await page.getByRole("button", { name: "Rename" }).click();
  await expect(page.getByTestId("studio-source")).toContainText('Procedure studio_made "What this procedure does."');

  await card(page, "start").click();
  const form = page.getByTestId("card-form");
  await form.getByTestId("form-output-name").fill("topic");
  await form.getByTestId("form-output-add").click();
  await expect(card(page, "start").locator('[data-section="inputs"]')).toContainText("topic: string");

  await card(page, "end").click();
  await page.getByTestId("card-form").getByTestId("form-read-pick").selectOption("topic");
  await page.getByTestId("card-form").getByTestId("form-read-add").click();
  await expect(status(page)).toHaveText("compiles");
  await expect(page.getByTestId("studio-source")).toContainText("Read request, topic");

  await expect(page.getByTestId("studio-publish")).toBeDisabled();
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-saved")).toContainText("Saved as a draft of studio_made");
  await page.getByTestId("studio-publish").click();
  await expect(page.getByTestId("studio-saved")).toHaveAttribute("data-revision", "1");
  await expect(page.getByTestId("studio-saved")).toContainText("Published studio_made@1");
  const catalog = await (await request.get(`${SERVER}/catalog`)).json();
  expect(catalog.map((c: { name: string }) => c.name)).toContain("studio_made");
});

test("ticket-triage: a move that breaks the flow is drawn on the cards, and undone", async ({ page }) => {
  await openStudio(page, `${TRIAGE}@1`);
  await card(page, "summarize").click();
  await page.getByTestId("card-form").getByTestId("form-move-into").selectOption({ label: "Loop revise" });
  await expect(status(page)).not.toHaveText("compiles");
  await expect(page.locator('[data-testid="canvas-card"][data-problems]').first()).toBeVisible();
  await expect(page.getByTestId("studio-save")).toBeDisabled();
  await page.getByTestId("studio-undo").click();
  await expect(status(page)).toHaveText("compiles");
  await expect(page.locator('[data-testid="canvas-card"][data-problems]')).toHaveCount(0);

  // The loop's cap, changed on its frame's form.
  await page.locator('[data-testid="canvas-frame"][data-loop="revise"] .aipc-frame-head').click();
  await page.getByTestId("form-cap").fill("5");
  await page.getByTestId("form-cap-save").click();
  await expect(page.getByTestId("studio-source")).toContainText("Loop revise Until passed, At_Most 5, Else_Fail {");
  await expect(status(page)).toHaveText("compiles");
});
