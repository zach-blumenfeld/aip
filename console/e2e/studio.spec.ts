import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { AGENT_MODEL_NAME, AGENT_MODEL_REPORTED, BILLING, E2E, SERVER, TRIAGE } from "./aip";

// The Studio (plan C4, A2), for people who do not code: a chat that runs build_procedure and edit_procedure
// with `aip runah` (its model here the stand-in, e2e/agent.mjs), the step graph beside it, forms for field
// edits, Undo per run, save and publish. A field edit is a text edit of procedure.aip that the console's
// process formats and compiles; only what compiles is saved. The scripts the model wrote are shown, and
// saving or publishing a draft that has them asks once.

const status = (page: Page) => page.getByTestId("studio-status");
const node = (page: Page, step: string) => page.locator(`[data-testid="studio-graph"] [data-testid="step-node"][data-step="${step}"]`);
const loopNode = (page: Page, loop: string) => page.locator(`[data-testid="studio-graph"] [data-testid="loop-node"][data-loop="${loop}"]`);
/** A picture of the page, into .aip-e2e/screenshots/ as graph.spec.ts does. */
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(E2E, "screenshots", `${name}.png`), fullPage: true });

const BRIEF = "A support inbox procedure: refund requests checked against a 100 limit by a script, bug reports tagged by area, the rest ends.";
const NAME = "support_inbox";              // the stand-in names it after the brief's subject when no name is given
const POLICY = "# Refunds\n\nA refund of 100 or less is approved by a script. Above it, a manager decides.\n";

async function openStudio(page: Page, ref?: string) {
  await page.goto(ref ? `./#/studio/${encodeURIComponent(ref)}` : "./#/studio");
  await expect(status(page)).toHaveText("compiles", { timeout: 30_000 });
}

/** Drop files on the chat as a person drags them from their desktop. */
async function dropOn(page: Page, files: { name: string; text: string }[]) {
  const data = await page.evaluateHandle((given) => {
    const dt = new DataTransfer();
    for (const f of given) dt.items.add(new File([f.text], f.name, { type: "text/markdown" }));
    return dt;
  }, files);
  await page.getByTestId("studio-chat").dispatchEvent("drop", { dataTransfer: data });
}

test.beforeEach(async ({ page }) => {
  // Unsaved edits are kept per browser; each test starts from what the server holds.
  await page.goto("./");
  await page.evaluate(() => localStorage.clear());
});

test("a brief and a document build a procedure; a label changed on its form; a step added by the chat, undone; saved and published", async ({ page, request }) => {
  await openStudio(page);
  await expect(page.getByTestId("studio-source")).toHaveCount(0);        // the source is closed until asked for
  await expect(page.getByTestId("studio-send")).toHaveText("Build it");

  // The brief, and a document dropped on the chat.
  await dropOn(page, [{ name: "refund-policy.md", text: POLICY }]);
  await expect(page.getByTestId("studio-documents")).toContainText("refund-policy.md");
  await page.getByTestId("studio-message").fill(BRIEF);
  await page.getByTestId("studio-send").click();

  // build_procedure reads the document, works out the rules, and asks what they leave open: a form in the chat.
  const turn = page.getByTestId("studio-turn").first();
  const human = turn.getByTestId("studio-human");
  await expect(human).toBeVisible({ timeout: 60_000 });
  await expect(turn).toHaveAttribute("data-kind", "build");
  await expect(turn).toHaveAttribute("data-status", "paused");
  await expect(human).toHaveAttribute("data-step", "ask_user");
  await expect(turn.getByTestId("studio-lines")).toContainText("reading refund-policy.md");
  await expect(turn.getByTestId("studio-lines")).toContainText("worked out the rules");
  await expect(human.getByTestId("studio-questions")).toContainText("What is the refund limit, and who approves above it?");
  await expect(page.getByTestId("studio-waiting")).toBeVisible();            // no new message until it is answered
  await expect(page.getByTestId("studio-message")).toBeDisabled();
  await shot(page, "studio-ask-user");

  // The answers: the run goes on, writes the folder, compiles it, tries it, reviews it.
  await human.getByLabel("answers", { exact: true }).fill("1. The limit is 100; above it a manager approves.");
  await human.getByTestId("studio-answer").click();
  await expect(turn).toHaveAttribute("data-status", "done", { timeout: 90_000 });
  await expect(turn.getByTestId("studio-lines")).toContainText("writing procedure.aip");
  await expect(turn.getByTestId("studio-lines")).toContainText("compiled it");
  await expect(turn.getByTestId("studio-review")).toContainText("stub");
  await expect(turn.getByTestId("studio-diff")).toContainText("Task_Agent classify");
  await expect(turn.getByTestId("studio-files")).toContainText("scripts/check_refund.py");
  await expect(status(page)).toHaveText("compiles");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(NAME);
  for (const step of ["start", "classify", "by_kind", "check_refund", "tag_bug", "end"]) await expect(node(page, step)).toBeVisible();
  const buildRun = (await turn.getAttribute("data-run"))!;
  await shot(page, "studio-built");

  // A field edit: classify's labels, `bug` renamed `defect`, which the route's branch follows.
  await node(page, "classify").click();
  const form = page.getByTestId("studio-form");
  await expect(form).toHaveAttribute("data-name", "classify");
  const labels = form.locator('[data-testid="form-answer"][data-key="kind"]');
  await expect(labels.getByTestId("form-labels-input")).toHaveValue("refund, bug, other");
  await labels.getByTestId("form-labels-input").fill("refund, defect, other");
  await labels.getByTestId("form-labels-save").click();
  await expect(status(page)).toHaveText("compiles");
  await page.getByTestId("studio-view-source").check();
  const source = page.getByTestId("studio-source");
  await expect(source).toContainText("Produce kind: choice [refund, defect, other]");
  await expect(source).toContainText(/defect\s*-> tag_bug/);
  await expect(page.locator('[data-testid="studio-graph"] [data-testid="step-edge"][data-from="by_kind"][data-to="tag_bug"]')).toHaveAttribute("data-label", "defect");

  // An edit message: edit_procedure adds a step for the other messages.
  await expect(page.getByTestId("studio-send")).toHaveText("Change it");
  await page.getByTestId("studio-message").fill("Answer the other messages instead of just ending.");
  await page.getByTestId("studio-send").click();
  const edit = page.getByTestId("studio-turn").nth(1);
  await expect(edit).toHaveAttribute("data-status", "done", { timeout: 90_000 });
  await expect(edit).toHaveAttribute("data-kind", "edit");
  await expect(edit.getByTestId("studio-review")).toContainText("answer_other");
  await expect(edit.getByTestId("studio-diff")).toContainText("Task_Agent answer_other");
  await expect(node(page, "answer_other")).toBeVisible();
  await expect(source).toContainText(/other\s*-> answer_other/);
  await expect(source).toContainText("choice [refund, defect, other]");       // the field edit made before it stays
  await shot(page, "studio-edited");

  // Undo takes the whole run back, and only it.
  await page.getByTestId("studio-undo").click();
  await expect(node(page, "answer_other")).toHaveCount(0);
  await expect(source).toContainText("choice [refund, defect, other]");
  await expect(status(page)).toHaveText("compiles");
  // And again: the change it was asked for.
  await page.getByTestId("studio-message").fill("Answer the other messages instead of just ending.");
  await page.getByTestId("studio-send").click();
  await expect(page.getByTestId("studio-turn").nth(2)).toHaveAttribute("data-status", "done", { timeout: 90_000 });
  await expect(node(page, "answer_other")).toBeVisible();

  // Saved as a draft, then published as the first revision of its name. The draft has a script the model wrote: saving
  // asks once whether it was read, and publishing does not ask again.
  await expect(page.getByTestId("studio-publish")).toBeDisabled();
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-scripts-ask")).toContainText("scripts/check_refund.py");
  await page.getByTestId("studio-scripts-ok").click();
  const saved = page.getByTestId("studio-saved");
  await expect(saved).toContainText(`Saved as a draft of ${NAME}`);
  await page.getByTestId("studio-publish").click();
  await expect(page.getByTestId("studio-scripts-ask")).toHaveCount(0);
  await expect(saved).toHaveAttribute("data-revision", "1");
  await expect(saved).toContainText(`Published ${NAME}@1`);
  const published = await (await request.get(`${SERVER}/catalog/${NAME}/graph`)).json();
  const text = published.graph.nodes.find((n: { labels: string[] }) => n.labels.includes("Procedure")).properties.source as string;
  expect(text).toContain("choice [refund, defect, other]");
  expect(text).toContain("Task_Agent answer_other");
  const files = published.graph.nodes.filter((n: { labels: string[] }) => n.labels.includes("File")).map((n: { properties: { path: string } }) => n.properties.path);
  expect(files).toEqual(expect.arrayContaining(["assets/docs/refund-policy.md", "scripts/check_refund.py"]));

  // The chat's runs are recorded as the studio's, with what runah's model did: the model as the endpoint reported it.
  const record = await (await request.get(`${SERVER}/runs/${buildRun}`)).json();
  expect(record.name).toBe("build_procedure");
  expect(record.identity.agent).toBe("studio");
  const draft = record.history.find((e: { step: string }) => e.step === "draft");
  expect(draft.answered_by).toEqual({ agent: "runah", model: AGENT_MODEL_REPORTED });
  expect(draft.work).toBe("observed");
  expect(draft.tool_calls.map((c: { name: string }) => c.name)).toEqual(["write_file", "write_file", "compile"]);
  expect(draft.result.procedure).toBe(NAME);
  const asked = record.history.find((e: { step: string }) => e.step === "ask_user");
  expect(asked.answered_by.agent).toBe("studio");
  // History's page of the run says so too.
  await page.goto(`./#/runs/${buildRun}`);
  const drafted = page.locator('[data-testid="record-entry"][data-step="draft"] [data-testid="answered-by"]');
  await expect(drafted).toHaveAttribute("data-agent", "runah");
  await expect(drafted).toHaveAttribute("data-work", "observed");
  await expect(drafted).toContainText(`answered by runah (${AGENT_MODEL_REPORTED}), observed: 3 tool calls (write_file 2, compile 1)`);
  await expect(page.locator('[data-testid="record-entry"][data-step="ask_user"] [data-testid="answered-by"]')).toHaveAttribute("data-agent", "studio");
});

test("a name given in the brief box names the procedure; the script the model wrote is shown, and saving asks once", async ({ page, request }) => {
  await openStudio(page);
  await page.getByTestId("studio-title").fill("Refund Desk");
  await page.getByTestId("studio-message").fill(BRIEF);
  await page.getByTestId("studio-send").click();
  const turn = page.getByTestId("studio-turn").first();
  const human = turn.getByTestId("studio-human");
  await expect(human).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("studio-scripts")).toHaveCount(0);           // nothing written yet
  await human.getByLabel("answers", { exact: true }).fill("1. The limit is 100.");
  await human.getByTestId("studio-answer").click();
  await expect(turn).toHaveAttribute("data-status", "done", { timeout: 90_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("refund_desk");
  await expect(turn.getByTestId("studio-review")).toContainText("Scripts:");

  // The script, with its text, under the heading that says to read it.
  const scripts = page.getByTestId("studio-scripts");
  await expect(scripts.getByRole("heading")).toHaveText("scripts the model wrote, read before you run or publish");
  const script = scripts.locator('[data-testid="studio-script"][data-path="scripts/check_refund.py"]');
  await expect(script).toContainText("Approve a refund of 100 or less");
  await expect(script).toContainText("json.dump({\"approved\": True}, sys.stdout)");
  await expect(scripts).toHaveAttribute("data-read", "false");
  await shot(page, "studio-scripts");

  // Saving asks; "not yet" saves nothing, and the next try asks again.
  await page.getByTestId("studio-save").click();
  const ask = page.getByTestId("studio-scripts-ask");
  await expect(ask).toHaveAttribute("data-action", "save");
  await expect(ask).toContainText("scripts/check_refund.py");
  await page.getByTestId("studio-scripts-cancel").click();
  await expect(ask).toHaveCount(0);
  await expect(page.getByTestId("studio-saved")).toHaveCount(0);
  await page.getByTestId("studio-save").click();
  await page.getByTestId("studio-scripts-ok").click();
  await expect(page.getByTestId("studio-saved")).toContainText("Saved as a draft of refund_desk");
  await expect(scripts).toHaveAttribute("data-read", "true");
  // Asked once: publishing, and saving again, go straight through.
  await page.getByTestId("studio-publish").click();
  await expect(page.getByTestId("studio-saved")).toContainText("Published refund_desk@1");
  await expect(ask).toHaveCount(0);
  const published = await (await request.get(`${SERVER}/catalog/refund_desk/graph`)).json();
  const files = published.graph.nodes.filter((n: { labels: string[] }) => n.labels.includes("File")).map((n: { properties: { path: string } }) => n.properties.path);
  expect(files).toContain("scripts/check_refund.py");
});

test("billing-support: forms change a description, a bar and a way out; a broken edit is drawn and undone", async ({ page, request }) => {
  await openStudio(page, `${BILLING}@1`);
  await expect(page.getByTestId("studio-send")).toHaveText("Change it");     // a revision is changed, not built

  await node(page, "by_tone").click();
  const form = page.getByTestId("studio-form");
  await form.getByTestId("form-bar-input").fill("0.75");
  await form.getByTestId("form-bar-save").click();
  await expect(status(page)).toHaveText("compiles");
  await form.locator('[data-testid="form-exit"][data-way="calm"]').getByTestId("form-exit-target").selectOption("escalate");
  // Nothing goes to reply now: the compiler says so, and the graph marks it.
  await expect(status(page)).toHaveText(/^\d+ errors?$/);
  await expect(page.getByTestId("studio-diagnostics").locator('[data-code="unreachable_step"]')).toBeVisible();
  await expect(node(page, "reply").getByTestId("node-note")).toHaveAttribute("data-note", /^\d+ errors?$/);
  await expect(page.getByTestId("studio-save")).toBeDisabled();
  await page.getByTestId("studio-undo").click();
  await expect(status(page)).toHaveText("compiles");

  await node(page, "reply").click();
  await page.getByTestId("studio-form").getByTestId("form-description").locator("textarea").fill("Draft a short, calm reply grounded in the refund policy.");
  await page.getByTestId("studio-form").getByTestId("form-description-save").click();
  await expect(status(page)).toHaveText("compiles");
  await page.getByTestId("studio-view-source").check();
  await expect(page.getByTestId("studio-source")).toContainText("Confidence_Below 0.75 -> escalate");
  await expect(page.getByTestId("studio-source")).toContainText('Task_Agent With reply "Draft a short, calm reply grounded in the refund policy." {');

  await page.getByTestId("studio-save").click();
  const saved = page.getByTestId("studio-saved");
  await expect(saved).toContainText(`Saved as a draft of ${BILLING}`);
  // A draft: the name still resolves to revision 1.
  const catalog = await (await request.get(`${SERVER}/catalog`)).json();
  expect(catalog.find((c: { name: string }) => c.name === BILLING).resolves).toBe("1");
});

test("ticket-triage: a loop's cap, Until and what it does at the cap, on its form", async ({ page }) => {
  await openStudio(page, `${TRIAGE}@1`);
  await loopNode(page, "revise").click();
  const form = page.getByTestId("studio-form");
  await expect(form).toHaveAttribute("data-kind", "Loop");
  await form.getByTestId("form-cap-input").fill("5");
  await form.getByTestId("form-cap-save").click();
  await expect(status(page)).toHaveText("compiles");
  await form.getByTestId("form-at-cap").selectOption("Else_Exit");
  await expect(status(page)).toHaveText("compiles");
  await page.getByTestId("studio-view-source").check();
  await expect(page.getByTestId("studio-source")).toContainText("Loop revise Until passed, At_Most 5, Else_Exit {");
  // An Until on something that is not an answer is the compiler's to refuse.
  await form.getByTestId("form-until").locator("textarea").fill("reply");
  await form.getByTestId("form-until-save").click();
  await expect(status(page)).not.toHaveText("compiles");
  await expect(page.getByTestId("studio-diagnostics")).toContainText("condition_on_plain_value");
  await page.getByTestId("studio-undo").click();
  await expect(status(page)).toHaveText("compiles");
});

test("a step whose script the draft lacks is marked: it needs a developer", async ({ page }) => {
  // An unsaved edit kept in this browser, naming a script the bundle does not have.
  const original = await (await (await page.request.get(`${SERVER}/catalog/${BILLING}/graph`)).json());
  const source = (original.graph.nodes.find((n: { labels: string[] }) => n.labels.includes("Procedure")).properties.source as string)
    .replace("Run_Script scripts/escalate.py", "Run_Script scripts/open_ticket.py");
  await page.evaluate(([key, value]) => localStorage.setItem(key, value), [`aip.studio:${BILLING}@1`, JSON.stringify({ source, files: {} })]);
  await page.goto(`./#/studio/${encodeURIComponent(`${BILLING}@1`)}`);
  await expect(page.getByTestId("studio-restored")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("studio-needs-scripts")).toContainText("escalate needs scripts/open_ticket.py");
  await expect(node(page, "escalate").getByTestId("node-note")).toHaveAttribute("data-note", "needs a script");
  await node(page, "escalate").click();
  await expect(page.getByTestId("needs-script")).toContainText("Ask a developer");
  await expect(page.getByTestId("studio-save")).toBeDisabled();
});

test("settings: the model `aip runah` runs the chat with, never its key", async ({ page }) => {
  await openStudio(page);
  await page.getByTestId("studio-view-settings").check();
  const runah = page.getByTestId("settings-runah");
  await expect(runah).toContainText(AGENT_MODEL_NAME);
  await expect(runah).toContainText("key set");
  await expect(runah).toContainText("set by the environment");
  await expect(runah).toContainText("AIP_RUNAH_MODEL_KEY");
  await expect(page.getByTestId("studio-settings")).not.toContainText("e2e");     // the stand-in's key
});
