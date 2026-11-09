import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { packSkill, type ZipFile } from "../src/zip";
import { FIRST_REVISION_DIR, WORKDIR } from "./aip";
import { aipSpec } from "./aip-spec";

// "Complete with an agent" (S6): the gate keeps the agent away from an unfinished design; Start writes the scaffold to
// a folder and shows one prompt naming it; the Studio watches the folder and checks what the agent writes there
// (aip-spec validate, adherence to the design, the script contract, completeness). Accept needs every check to pass.

function folderFiles(dir: string): ZipFile[] {
  const out: ZipFile[] = [];
  const walk = (rel: string) => {
    for (const item of readdirSync(path.join(dir, rel)).sort()) {
      const sub = rel ? `${rel}/${item}` : item;
      const st = statSync(path.join(dir, sub));
      if (st.isDirectory()) walk(sub);
      else out.push({ path: sub, bytes: new Uint8Array(readFileSync(path.join(dir, sub))), mode: st.mode & 0o777 });
    }
  };
  walk("");
  return out;
}

const SKILL_MD = readFileSync(path.join(FIRST_REVISION_DIR, "SKILL.md"), "utf8");
const ESCALATE_DESCRIPTION = "    description: Open a tier-2 ticket for the message.\n";
/** The design: billing-support's SKILL.md alone, with the escalate step's description left for the agent. */
const DESIGN = SKILL_MD.replace(ESCALATE_DESCRIPTION, '    description: ""\n');

const zip = (name: string, files: ZipFile[]) => ({ name, mimeType: "application/zip", buffer: Buffer.from(packSkill("billing-support", files)) });
const md = (text: string): ZipFile => ({ path: "SKILL.md", bytes: new TextEncoder().encode(text), mode: 0o644 });

/** The real billing-support folder (a correct fill-in of the design), with `change` applied to one file. */
function result(change?: { path: string; edit: (text: string) => string }): ZipFile[] {
  return folderFiles(FIRST_REVISION_DIR).map((f) => {
    if (!change || f.path !== change.path) return f;
    return { ...f, bytes: new TextEncoder().encode(change.edit(new TextDecoder().decode(f.bytes))) };
  });
}

async function openDesign(page: Page, skillMd: string, name: string) {
  await page.goto("#/studio");
  await page.getByTestId("studio-drafts").getByLabel("import skill zip").setInputFiles(zip(name, [md(skillMd)]));
  await expect(page.getByTestId("studio-notice")).toContainText(`Imported ${name}`);
  await page.getByTestId("studio-agent").click();
  return page.getByTestId("agent-panel");
}

/** Play the agent: write `files` into the handoff folder, then wait for the Studio's next check of it. */
async function agentWrites(page: Page, dir: string, label: string, files: ZipFile[]) {
  const out = page.getByTestId("agent-result");
  const before = (await out.count()) ? Number(await out.getAttribute("data-run")) : 0;
  for (const f of files) {
    mkdirSync(path.dirname(path.join(dir, f.path)), { recursive: true });
    writeFileSync(path.join(dir, f.path), f.bytes, { mode: f.mode });
  }
  await expect.poll(async () => ((await out.count()) ? Number(await out.getAttribute("data-run")) : 0), { timeout: 60_000 }).toBeGreaterThan(before);
  const failed = await out.locator('[data-check][data-ok="false"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-check")));
  verdicts.push(`${label}: ${failed.length ? `not ready (failed: ${failed.join(", ")})` : "every check passed"}`);
  return out;
}

const verdicts: string[] = [];
const check = (out: ReturnType<Page["getByTestId"]>, name: string) => out.locator(`[data-check="${name}"]`);

test.beforeEach(() => {
  test.skip(aipSpec(["--version"]).status !== 0, "aip-spec is not available (needs uv and the aip repo's environment)");
});

test("a design with a bash execution step keeps the agent away, and says why", async ({ page }) => {
  const bash = SKILL_MD
    .replace("    script: scripts/escalate.py\n", "    script: scripts/escalate.py\n    command: [bash]\n")
    .replace('    version: "3.10"\n', '    version: "3.10"\n  tools:\n    - bash\n');
  const panel = await openDesign(page, bash, "bash-design.zip");
  const reasons = panel.getByTestId("agent-reason");
  await expect(reasons.filter({ hasText: "launched with `bash`" })).toHaveCount(1);
  await expect(panel.getByTestId("agent-start")).toBeDisabled();
  console.log(`agent gate: ${await reasons.count()} reason(s): ${(await reasons.allTextContents()).join(" | ")}`);

  // the reason links to the field
  await reasons.filter({ hasText: "launched with `bash`" }).getByRole("button").click();
  await expect(page.locator('.studio-panel [data-field="command"]')).toBeFocused();
});

test("start writes the folder and one prompt; the Studio checks the agent's edits as they land, and accepts a correct one", async ({ page }) => {
  const panel = await openDesign(page, DESIGN, "design.zip");

  // the instructions can be edited, and the edit is saved with the draft
  await panel.locator("summary", { hasText: "Edit the instructions" }).click();
  await panel.getByTestId("agent-prompt").fill("Fill the placeholders. Be brief.");

  await panel.getByTestId("agent-start").click();
  const dir = (await panel.getByTestId("agent-dir").textContent())!;
  expect(dir).toBe(path.join(WORKDIR, "studio", "billing-support"));
  expect(readFileSync(path.join(dir, "scripts", "escalate.py"), "utf8")).toContain("AIP-STUDIO-PLACEHOLDER");
  const prompt = await panel.getByTestId("agent-prompt-text").inputValue();
  for (const s of ["Fill the placeholders. Be brief.", `\`${dir}\``, "`start` (start)", "inputs (what the client supplies): message: string", "`escalate` (execution)",
                   "outputs: ticket_id: integer, queue: string", "fallback: true", "step 4 (`escalate`): the description"]) {
    expect(prompt, s).toContain(s);
  }
  await expect(panel.getByTestId("agent-waiting")).toContainText("0 of 5 placeholder files written");

  // a reload keeps the handoff, and the watch goes on
  await page.reload();
  await page.getByTestId("studio-agent").click();
  await expect(page.getByTestId("agent-dir")).toHaveText(dir);

  // a step renamed: the adherence check names it
  const renamed = await agentWrites(page, dir, "renamed step", result({
    path: "SKILL.md", edit: (t) => t.replace("  - name: escalate\n", "  - name: open-ticket\n").replace("angry: escalate", "angry: open-ticket"),
  }));
  await expect(check(renamed, "adherence")).toContainText("the name changed: the draft has `escalate`, the result has `open-ticket`");
  await expect(renamed.getByTestId("agent-accept")).toBeDisabled();

  // a script that prints a wrong key: the contract check names it
  const wrongKey = await agentWrites(page, dir, "wrong key", result({ path: "scripts/escalate.py", edit: (t) => t.replace('json.dump({"ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)', 'json.dump({"ticket": ticket_id, "queue": config["queue"]}, sys.stdout)') }));
  await expect(check(wrongKey, "validate")).toHaveAttribute("data-ok", "true");
  await expect(check(wrongKey, "adherence")).toHaveAttribute("data-ok", "true");
  await expect(check(wrongKey, "contract")).toContainText("does not print the declared output `ticket_id`");
  await expect(check(wrongKey, "contract")).toContainText("prints `ticket`, which is not a declared output");
  await expect(wrongKey.getByTestId("agent-accept")).toBeDisabled();

  // a placeholder marker left in one file, then one empty script: completeness fails
  const marker = await agentWrites(page, dir, "marker left", result({ path: "assets/policy.md", edit: (t) => `<!-- AIP-STUDIO-PLACEHOLDER: Studio wrote this asset. -->\n${t}` }));
  await expect(check(marker, "completeness")).toContainText("`assets/policy.md` still holds the placeholder marker");
  await expect(marker.getByTestId("agent-accept")).toBeDisabled();
  const empty = await agentWrites(page, dir, "empty script", result({ path: "scripts/escalate.py", edit: () => "# TODO\n" }));
  await expect(check(empty, "completeness")).toContainText("`scripts/escalate.py` is empty apart from comments");
  await expect(empty.getByTestId("agent-accept")).toBeDisabled();

  // the correct result: every check passes, the filled description is listed, the diff shows the script replaced
  const good = await agentWrites(page, dir, "correct", result());
  for (const c of ["validate", "adherence", "contract", "completeness"]) await expect(check(good, c), c).toHaveAttribute("data-ok", "true");
  await expect(good.getByTestId("agent-filled")).toContainText("Open a tier-2 ticket for the message.");
  await good.getByTestId("agent-diff").locator("summary").click();
  await expect(good.locator('[data-path="scripts/escalate.py"][data-status="changed"]')).toHaveCount(1);
  await good.getByTestId("agent-accept").click();
  await expect(page.getByTestId("agent-accepted")).toBeVisible();

  // the draft now carries the files and the prose: nothing is unfinished
  const lint = page.getByTestId("lint-panel");
  await expect(lint.locator('[data-code="placeholder_file"]')).toHaveCount(0);
  await expect(lint.locator('[data-code="empty_description"]')).toHaveCount(0);
  await expect(page.getByTestId("lint-unfinished")).toHaveCount(0);

  // starting again writes a fresh scaffold and moves the agent's folder aside rather than deleting it
  await page.getByTestId("agent-start").click();
  await expect(page.getByTestId("agent-dir")).toHaveText(dir);
  const previous = readdirSync(path.join(WORKDIR, "studio", ".previous"));
  expect(previous.some((p) => p.startsWith("billing-support-"))).toBe(true);
  console.log(`agent checks:\n  ${verdicts.join("\n  ")}`);
});
