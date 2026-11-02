import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { DRAFT_KEY } from "../src/studio/storage";
import { skillMdToDraft } from "../src/studio/serialize";
import { unpackSkill } from "../src/zip";
import { FIRST_REVISION_DIR } from "./aip";
import { aipSpec, specErrors } from "./aip-spec";

// The Studio tab (S1): build the billing-support graph by hand through the page, reload, and find the draft kept
// and the wired part of the graph lint-clean. Inputs and outputs have no editor until S2, so the draft still has
// the issues that need them (a client task with no outputs, an unfinished script); only the wiring rules are
// asserted clean here.

const WIRING = ["duplicate_step_name", "invalid_start_step", "missing_end_step", "multiple_end_steps", "unknown_step_reference",
  "unreachable_step", "no_path_to_end", "unknown_branch_value"];

const node = (page: Page, name: string) => page.getByRole("button", { name: new RegExp(`^${name} \\(`) });
const panel = (page: Page) => page.getByTestId("step-panel");
const field = (page: Page, name: string): Locator => panel(page).locator(`[data-field="${name}"]`).first();
const idOf = async (page: Page, name: string) => (await page.locator(`[data-testid="step-node"][data-name="${name}"]`).getAttribute("data-step"))!;
const edge = async (page: Page, from: string, to: string) =>
  page.locator(`[data-testid="step-edge"][data-from="${await idOf(page, from)}"][data-to="${await idOf(page, to)}"]`);
const rename = async (page: Page, name: string) => { await field(page, "name").fill(name); await expect(node(page, name)).toBeVisible(); };
const onBranch = (page: Page, n: number, kind: string) =>
  panel(page).getByRole("group", { name: `New step on branch ${n}` }).getByRole("button", { name: `+ ${kind}` }).click();
const addAfter = (page: Page, after: string, kind: string) =>
  page.getByRole("group", { name: `Add step after ${after}` }).getByRole("button", { name: `+ ${kind}` }).click();

test("build billing-support by hand, reload, and the draft and its wiring are kept", async ({ page }) => {
  await page.goto("./#/studio");
  await expect(page.getByTestId("studio-empty")).toBeVisible();

  // triage: a decision with one choice question, whose labels become the router's branches
  await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: "+ decision" }).click();
  await rename(page, "triage");
  await page.getByRole("group", { name: "Add question" }).getByRole("button", { name: "+ choice" }).click();
  const q = panel(page).getByTestId("question");
  await q.locator("input").first().fill("tone");
  await q.getByLabel("label 1", { exact: true }).fill("angry");
  await q.getByLabel("label 2", { exact: true }).fill("calm");

  // by-tone: spliced after triage, its rows filled from the question's labels
  await addAfter(page, "triage", "router");
  await rename(page, "by-tone");
  await expect(field(page, "branchOn")).toHaveValue("tone");
  await expect(panel(page).getByLabel("branch 1 value")).toHaveValue("angry");
  await expect(panel(page).getByLabel("branch 2 value")).toHaveValue("calm");
  // the key is chosen from what reaches the router, and the question's answers are shown
  await expect(field(page, "branchOn").locator("option")).toHaveText(["(choose a key)", "tone (string)"]);
  await expect(panel(page).getByTestId("possible-values")).toHaveText("possible values: angry, calm");

  // a step is made from the branch row it belongs to
  await onBranch(page, 1, "execution");
  await rename(page, "escalate");
  await node(page, "by-tone").click();
  await onBranch(page, 2, "client_task");
  await expect(panel(page).getByRole("heading", { name: /^client-task-1/ })).toBeVisible();
  await rename(page, "reply");
  await node(page, "escalate").click();
  await addAfter(page, "escalate", "end");
  await rename(page, "end");

  // reply leads to the end through the next-step picker; a second outbound edge cannot be added
  await node(page, "reply").click();
  await panel(page).getByLabel("next step").selectOption({ label: "end" });

  await expect(page.getByTestId("step-node")).toHaveCount(5);
  await expect(page.getByTestId("step-edge")).toHaveCount(5);
  for (const [from, to] of [["triage", "by-tone"], ["by-tone", "escalate"], ["by-tone", "reply"], ["escalate", "end"], ["reply", "end"]]) {
    await expect(await edge(page, from, to)).toHaveCount(1);
  }
  await expect(page.getByTestId("branch-label")).toHaveText(["angry", "calm"]);

  // the lint panel shows no wiring errors, and a click on an issue selects its step
  const lintPanel = page.getByTestId("lint-panel");
  for (const code of WIRING) await expect(lintPanel.locator(`li[data-code="${code}"]`)).toHaveCount(0);
  await lintPanel.locator('li[data-code="missing_outputs"]').getByRole("button").click();
  await expect(panel(page).getByRole("heading", { name: /^reply/ })).toBeVisible();
  await expect(page.getByTestId("step-mark").first()).toBeVisible();

  // procedure settings are kept too
  await page.getByRole("button", { name: "procedure settings" }).click();
  await page.locator('[data-field="name"]').fill("billing-support");
  await page.locator('[data-field="purpose"]').fill("Answer a billing question.");

  await expect(page.getByTestId("studio-saved")).toHaveAttribute("data-state", "saved");
  await page.reload();

  await expect(page.getByTestId("step-node")).toHaveCount(5);
  await expect(page.getByTestId("step-edge")).toHaveCount(5);
  for (const name of ["triage", "by-tone", "escalate", "reply", "end"]) await expect(node(page, name)).toBeVisible();
  for (const [from, to] of [["by-tone", "escalate"], ["by-tone", "reply"], ["reply", "end"]]) {
    await expect(await edge(page, from, to)).toHaveCount(1);
  }
  await page.getByRole("button", { name: "procedure settings" }).click();
  await expect(page.locator('[data-field="purpose"]')).toHaveValue("Answer a billing question.");
  for (const code of WIRING) await expect(page.getByTestId("lint-panel").locator(`li[data-code="${code}"]`)).toHaveCount(0);
});

test("deleting a middle step re-links its neighbours; a step with no name still draws", async ({ page }) => {
  await page.goto("./#/studio");
  await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: "+ execution" }).click();
  await rename(page, "first");
  await addAfter(page, "first", "execution");
  await rename(page, "middle");
  await addAfter(page, "middle", "end");
  await expect(page.getByTestId("step-edge")).toHaveCount(2);

  await node(page, "middle").click();
  await panel(page).getByRole("button", { name: "delete step" }).click();
  await expect(page.getByTestId("step-node")).toHaveCount(2);
  await expect(await edge(page, "first", "end")).toHaveCount(1);

  // an empty name is an error in the lint panel, not a crash
  await node(page, "first").click();
  await field(page, "name").fill("");
  await expect(page.getByTestId("lint-panel").locator('li[data-code="schema_violation"]').first()).toBeVisible();
  await expect(page.getByTestId("step-node")).toHaveCount(2);
});

// ------------------------------------------------------------------------------------------------ S2: inputs and outputs

/** fetch (execution, one integer output `ticket`) -> end, with `ticket` taken as an input of the end step. */
async function chain(page: Page) {
  await page.goto("./#/studio");
  await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: "+ execution" }).click();
  await rename(page, "fetch");
  await expect(panel(page).getByTestId("io-inputs").getByText("inputs: what the client supplies")).toBeVisible();
  await panel(page).getByRole("button", { name: "add new output" }).click();
  await panel(page).getByLabel("outputs 1 name").fill("ticket");
  await panel(page).getByLabel("outputs 1 type").selectOption("integer");
  await addAfter(page, "fetch", "end");
  // the end step offers the key, with its type, and the pick fills both
  await expect(panel(page).getByLabel("add inputs from the state").locator("option")).toHaveText(["add a key from the state…", "ticket (integer)"]);
  await panel(page).getByLabel("add inputs from the state").selectOption({ label: "ticket (integer)" });
  await expect(panel(page).getByLabel("inputs 1 name")).toHaveValue("ticket");
  await expect(panel(page).getByLabel("inputs 1 type")).toHaveValue("integer");
}

const unproduced = (page: Page) => page.getByTestId("lint-panel").locator('li[data-code="unproduced_input"]');

test("a key picked from the state is never unproduced; renaming its producer's output is, and a quick fix clears it", async ({ page }) => {
  await chain(page);
  const lintPanel = page.getByTestId("lint-panel");
  await expect(unproduced(page)).toHaveCount(0);
  await expect(lintPanel.locator('li[data-code="type_mismatch"]')).toHaveCount(0);

  await node(page, "fetch").click();
  await panel(page).getByLabel("outputs 1 name").fill("ticket_id");
  await expect(unproduced(page)).toHaveCount(1);
  await expect(unproduced(page)).toHaveAttribute("data-step", await idOf(page, "end"));
  await expect(unproduced(page)).toContainText("`ticket`");

  // the fix: the client supplies it, as an input of the start step
  await unproduced(page).getByRole("button", { name: "declare ticket as a start input" }).click();
  await expect(unproduced(page)).toHaveCount(0);
  await node(page, "fetch").click();
  await expect(panel(page).getByLabel("inputs 1 name")).toHaveValue("ticket");
  await expect(panel(page).getByLabel("inputs 1 type")).toHaveValue("integer");
});

test("the other quick fix makes the key an output of a step", async ({ page }) => {
  await chain(page);
  await node(page, "fetch").click();
  await panel(page).getByLabel("outputs 1 name").fill("ticket_id");
  await expect(unproduced(page)).toHaveCount(1);
  await unproduced(page).getByLabel("make ticket an output of").selectOption({ label: "fetch" });
  await expect(unproduced(page)).toHaveCount(0);
  await node(page, "fetch").click();
  await expect(panel(page).getByLabel("outputs 2 name")).toHaveValue("ticket");
  // the declared type came from the consumer, so nothing disagrees
  await expect(page.getByTestId("lint-panel").locator('li[data-code="type_mismatch"]')).toHaveCount(0);
});

test("a decision's outputs are read-only, one key per question, and the data view draws the flow", async ({ page }) => {
  await page.goto("./#/studio");
  await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: "+ decision" }).click();
  await rename(page, "triage");
  await page.getByRole("group", { name: "Add question" }).getByRole("button", { name: "+ score" }).click();
  await panel(page).getByTestId("question").locator("input").first().fill("urgency");
  await expect(panel(page).getByTestId("decision-outputs")).toContainText("urgency: integer");
  await expect(panel(page).getByTestId("decision-outputs").locator("input")).toHaveCount(0);

  await addAfter(page, "triage", "execution");
  await rename(page, "act");
  await panel(page).getByLabel("add inputs from the state").selectOption({ label: "urgency (integer)" });

  await expect(page.getByTestId("data-edge")).toHaveCount(0);
  await page.getByLabel("data flow").check();
  const arrow = page.getByTestId("data-edge");
  await expect(arrow).toHaveCount(1);
  await expect(arrow).toHaveAttribute("data-keys", "urgency");
  await expect(arrow).toHaveAttribute("data-from", await idOf(page, "triage"));
  await expect(arrow).toHaveAttribute("data-to", await idOf(page, "act"));
  await expect(page.getByTestId("input-node")).toBeVisible();
});

test("a decision's review threshold takes decimals, is checked against 0 to 1, and is explained per question type", async ({ page }) => {
  await page.goto("./#/studio");
  await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: "+ decision" }).click();
  await rename(page, "triage");
  await page.getByRole("group", { name: "Add question" }).getByRole("button", { name: "+ noul" }).click();
  const q = panel(page).getByTestId("question");
  const threshold = q.getByLabel("question_1 threshold");
  const help = q.getByTestId("threshold-help");

  await expect(help).toContainText("within this margin of 0.5");
  await threshold.pressSequentially("0.35");
  await expect(threshold).toHaveValue("0.35");
  await expect(threshold).not.toHaveAttribute("aria-invalid", "true");

  // out of range is marked, and the linter says so
  await threshold.fill("1.5");
  await expect(threshold).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByTestId("lint-panel").locator('li[data-code="schema_violation"]', { hasText: "between 0 and 1" })).toHaveCount(1);
  await threshold.fill("0.35");

  // the meaning changes with the type: choice and score are about the model's confidence
  await q.getByLabel("question_1 type").selectOption("choice");
  await expect(help).toContainText("confidence");
  await expect(threshold).toHaveValue("0.35");

  await expect(page.getByTestId("studio-saved")).toHaveAttribute("data-state", "saved");
  await page.reload();
  await expect(panel(page)).toBeHidden();
  await node(page, "triage").click();
  await expect(panel(page).getByTestId("question").getByLabel("question_1 threshold")).toHaveValue("0.35");
});

// ------------------------------------------------------------------------------------------------ S3: the scaffold zip

test("export a scaffold: placeholders follow their paths, the zip validates with aip-spec, and it publishes", async ({ page }) => {
  // billing-support as the stored draft, under a name of its own so the catalog's billing-support is left alone
  const draft = skillMdToDraft(readFileSync(path.join(FIRST_REVISION_DIR, "SKILL.md"), "utf8"));
  draft.name = "studio-scaffold";
  await page.goto("./#/studio");
  await page.evaluate(([key, value]) => localStorage.setItem(key, value), [DRAFT_KEY, JSON.stringify(draft)]);
  await page.reload();
  await expect(node(page, "escalate")).toBeVisible();

  // every referenced file is a placeholder, and the linter says so on its step
  const lintPanel = page.getByTestId("lint-panel");
  await expect(lintPanel.locator('li[data-code="placeholder_file"]')).toHaveCount(5);

  // a renamed step takes its default template path along; an edited script path moves the stub
  await node(page, "reply").click();
  await rename(page, "answer");
  await expect(field(page, "template")).toHaveValue("assets/answer.md");
  await node(page, "escalate").click();
  await field(page, "script").fill("scripts/open-ticket.py");

  // with an error, the summary says so and publishing is held back with the reason
  await node(page, "end").click();
  await field(page, "name").fill("End");
  await page.getByTestId("studio-export").click();
  const summary = page.getByTestId("export-summary");
  await expect(summary).not.toHaveAttribute("data-errors", "0");
  await expect(page.getByTestId("export-publish")).toBeDisabled();
  await expect(page.getByTestId("export-publish-reason")).toBeVisible();
  await rename(page, "end");
  await expect(summary).toHaveAttribute("data-errors", "0");
  await expect(summary).toHaveAttribute("data-unfinished", "5");

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-download").click()]);
  expect(download.suggestedFilename()).toBe("studio-scaffold.zip");
  const { files, folder } = unpackSkill(new Uint8Array(readFileSync(await download.path())));
  expect(folder).toBe("studio-scaffold");
  // SKILL.md, one script per execution step, one template per client task, the declared assets and references
  const tree = files.map((f) => f.path);
  console.log(`scaffold tree: ${tree.join(", ")}`);
  expect(tree).toEqual(["SKILL.md", "assets/answer.md", "assets/config.json", "assets/policy.md", "references/help.md", "scripts/open-ticket.py", "source/README.md"]);

  const root = mkdtempSync(path.join(tmpdir(), "studio-export-"));
  try {
    const dir = path.join(root, folder!);
    for (const f of files) {
      mkdirSync(path.dirname(path.join(dir, f.path)), { recursive: true });
      writeFileSync(path.join(dir, f.path), f.bytes);
    }
    const { status } = aipSpec(["validate", dir]);
    const errors = specErrors(dir);
    console.log(`scaffold: aip-spec validate exited ${status} with ${errors.length} errors`);
    expect(errors).toEqual([]);
    expect(status).toBe(0);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }

  // the same files publish through the catalog flow, and the page lands on the new revision
  await page.getByTestId("export-publish").click();
  await expect(page).toHaveURL(/#\/p\/studio-scaffold(%40|@)[0-9a-f]{16}$/);
  await expect(page.getByTestId("published-note")).toHaveAttribute("data-existed", "false");
});
