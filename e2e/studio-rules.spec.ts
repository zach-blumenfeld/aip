import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { Draft, Step } from "../src/studio/draft";
import { autofix } from "../src/studio/fixes";
import { lint, type Tier } from "../src/studio/lint";
import { skillMdToDraft } from "../src/studio/serialize";
import { DRAFT_KEY } from "../src/studio/storage";
import { EXAMPLE_DIR } from "./aip";

// S5: the Studio-only rules (docs/studio-lint.md). Each fixture is billing-support, lint-clean, with one thing
// changed, and must raise its rule exactly once at its tier. Then, in the page: an autofix clears its issue, undo and
// redo walk it back and forth, F8 walks the issues, and Delete removes the selected step.

const step = (d: Draft, name: string): Step => d.steps.find((s) => s.name === name)!;

/** billing-support with the step `reply` renamed, so it no longer shares a name with its key, and `fallback` off on
 *  its decision, so its route is measured: no issues at all. */
function base(): Draft {
  const d = skillMdToDraft(readFileSync(path.join(EXAMPLE_DIR, "SKILL.md"), "utf8"));
  step(d, "reply").name = "draft-reply";
  step(d, "triage").fallback = false;
  return d;
}

const RULES: Record<string, [Tier, (d: Draft) => void]> = {
  redundant_branches: ["warning", (d) => {
    const tone = step(d, "triage").questions![1];
    if (tone.type === "choice") tone.criteria.push({ label: "neutral", description: null });
    step(d, "by-tone").branches!.push({ value: "neutral", target: step(d, "draft-reply").id });
  }],
  branch_value_not_an_answer: ["unfinished", (d) => {
    // a router after a client task, on a boolean the task outputs: `yes` is not a boolean's value
    const reply = step(d, "draft-reply");
    reply.outputs!.push({ name: "ok", type: "boolean" });
    const again: Step = { id: "s-again", kind: "router", name: "again", description: "x", inputs: [], branchOn: "ok",
      branches: [{ value: "yes", target: step(d, "end").id }, { value: "false", target: reply.id }] };
    reply.next = again.id;
    d.steps.splice(d.steps.indexOf(reply) + 1, 0, again);
  }],
  loop_without_router: ["error", (d) => { step(d, "draft-reply").next = step(d, "draft-reply").id; }],
  numeric_choice_labels: ["warning", (d) => {
    const tone = step(d, "triage").questions![1];
    if (tone.type === "choice") { tone.criteria[0].label = "1"; tone.criteria[1].label = "2"; }
    step(d, "by-tone").branches![0].value = "1";
    step(d, "by-tone").branches![1].value = "2";
  }],
  duplicate_score_levels: ["warning", (d) => {
    step(d, "triage").questions![0] = { name: "billing", type: "score", instructions: "x", criteria: ["low", "high", "low"] };
  }],
  execution_without_outputs: ["warning", (d) => { step(d, "escalate").outputs = []; }],
  dead_key: ["warning", (d) => {
    // a lookup between triage and the router outputs `account`, which every later step could read and none does
    const triage = step(d, "triage");
    const lookup: Step = { id: "s-lookup", kind: "execution", name: "lookup", description: "x", inputs: [{ name: "message", type: "string" }],
      script: "scripts/escalate.py", outputs: [{ name: "account", type: "string" }], next: triage.next };
    triage.next = lookup.id;
    d.steps.splice(1, 0, lookup);
  }],
  name_collision: ["warning", (d) => { step(d, "draft-reply").name = "reply"; }],
};

test("billing-support with its reply step renamed has no issues", () => {
  expect(lint(base())).toEqual([]);
});

test("each Studio-only rule fires once, at its tier", () => {
  const seen: string[] = [];
  for (const [code, [tier, change]] of Object.entries(RULES)) {
    const d = base();
    change(d);
    const hits = lint(d).filter((i) => i.code === code);
    expect(hits.map((i) => i.tier), code).toEqual([tier]);
    seen.push(`${code} (${tier})`);
  }
  console.log(`studio rules: ${seen.length} fired once at their tier: ${seen.join(", ")}`);
});

test("a router whose key nothing produces is told so on its own field", () => {
  const d = base();
  step(d, "by-tone").branchOn = "ghost";
  const issue = lint(d).find((i) => i.code === "unproduced_input")!;
  expect(issue).toMatchObject({ tier: "error", stepId: step(d, "by-tone").id, field: "branchOn", key: "ghost" });
  expect(issue.message).toMatch(/^router `by-tone` branches on `ghost`/);
});

test("autofixes clear their issue", () => {
  const cases: [string, (d: Draft) => void][] = [
    ["missing_requires", (d) => { delete d.requires; }],
    ["undeclared_launcher", (d) => { step(d, "escalate").command = ["python3"]; }],
    ["schema_violation", (d) => { delete step(d, "draft-reply").next; }],
  ];
  for (const [code, change] of cases) {
    const d = base();
    change(d);
    const issue = lint(d).find((i) => i.code === code)!;
    const fix = autofix(issue, d);
    expect(fix, code).toBeDefined();
    expect(lint(fix!.apply(d)).filter((i) => i.code === code && i.tier === "error"), code).toEqual([]);
  }
});

// ------------------------------------------------------------------------------------------------ in the page

const node = (page: Page, name: string) => page.getByRole("button", { name: new RegExp(`^${name} \\(`) });

test("in the page: an autofix, undo and redo, F8 through the issues, Delete on a step", async ({ page }) => {
  const d = base();
  d.name = "studio-rules";
  delete d.requires;
  await page.goto("./#/studio");
  await page.evaluate(([key, value]) => localStorage.setItem(key, value), [DRAFT_KEY, JSON.stringify(d)]);
  await page.reload();
  await expect(node(page, "escalate")).toBeVisible();

  const lintPanel = page.getByTestId("lint-panel");
  const missing = lintPanel.locator('li[data-code="missing_requires"]');
  await expect(missing).toHaveCount(1);
  await expect(page.getByTestId("studio-undo")).toBeDisabled();
  await missing.getByTestId("lint-autofix").click();
  await expect(missing).toHaveCount(0);
  await expect(page.getByTestId("lint-error")).toHaveCount(0);   // what is left is the placeholders, unfinished

  // the fix is one step of history
  await page.getByTestId("studio-undo").click();
  await expect(missing).toHaveCount(1);
  await page.getByTestId("studio-redo").click();
  await expect(missing).toHaveCount(0);

  // F8 walks the issues: select one, and its step opens
  await page.keyboard.press("ControlOrMeta+z");
  await expect(missing).toHaveCount(1);
  await node(page, "triage").click();
  await page.keyboard.press("F8");
  await expect(lintPanel.locator('li[aria-current="true"]')).toHaveAttribute("data-code", "missing_requires");
  await expect(page.getByTestId("procedure-panel")).toBeVisible();

  // Delete removes the selected step, and undo brings it back
  await node(page, "escalate").click();
  await page.keyboard.press("Delete");
  await expect(node(page, "escalate")).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(node(page, "escalate")).toBeVisible();
});
