import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { AGENT, CHANGED_FILE, FIRST_REVISION_DIR, NEW_LINE, OLD_LINE } from "./aip";

// The source view: the stored procedure.aip, in the shipped grammar's colours, and the bundle's files;
// and the diff between two revisions.

test("the source is procedure.aip as it was stored, coloured by the grammar the extension ships", async ({ page }) => {
  await page.goto(`./#/p/${AGENT}@1/files`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`${AGENT} source @1`);
  const rows = page.getByTestId("file-row");
  await expect(rows).toHaveText([/procedure\.aip/, /assets\/config\.json/, /assets\/policy\.md/, /assets\/reply\.md/, /references\/help\.md/, /scripts\/escalate\.py/]);

  // Byte for byte: every line of the folder's file, in order.
  const stored = readFileSync(path.join(FIRST_REVISION_DIR, "procedure.aip"), "utf8");
  const code = page.getByTestId("file-text");
  await expect(code).toHaveAttribute("data-language", "aip");
  const lines = stored.replace(/\n$/, "").split("\n");
  await expect(code.getByRole("listitem")).toHaveCount(lines.length);
  const shown = await code.getByRole("listitem").allTextContents();
  expect(shown.map((l) => l.replace("​", ""))).toEqual(lines);

  // The grammar's scopes: step verbs, step names, clauses, types, labels, comments, strings.
  const scoped = (scope: string) => code.locator(`[data-scope="${scope}"]`);
  await expect(scoped("keyword.control.step.aip").first()).toHaveText("Procedure");
  await expect(scoped("entity.name.function.step.aip").filter({ hasText: "triage" }).first()).toBeVisible();
  await expect(scoped("keyword.other.clause.aip").filter({ hasText: "Produce" }).first()).toBeVisible();
  await expect(scoped("support.type.answer.aip").filter({ hasText: "choice" }).first()).toBeVisible();
  await expect(scoped("constant.other.label.aip").filter({ hasText: "angry" }).first()).toBeVisible();
  await expect(scoped("comment.line.number-sign.aip").first()).toContainText("#");
  // A verb is coloured as the extension colours it (one of its two palettes), and bold.
  const verb = scoped("keyword.control.step.aip").first();
  const colour = await verb.evaluate((el) => getComputedStyle(el).color);
  expect(["rgb(255, 122, 178)", "rgb(194, 24, 91)"]).toContain(colour);
  expect(Number(await verb.evaluate((el) => getComputedStyle(el).fontWeight))).toBeGreaterThanOrEqual(600);
});

test("a file beside the procedure opens as plain text", async ({ page }) => {
  await page.goto(`./#/p/${AGENT}@1/files/${CHANGED_FILE}`);
  await expect(page.locator('[data-testid="file-row"][aria-current="true"]')).toContainText(CHANGED_FILE);
  const code = page.getByTestId("file-text");
  await expect(code).not.toHaveAttribute("data-language", "aip");
  await expect(code).toContainText(OLD_LINE);
  await expect(code.locator("[data-scope]")).toHaveCount(0);
});

test("the diff between two revisions names the file that changed and shows the line", async ({ page }) => {
  await page.goto(`./#/p/${AGENT}/diff`);
  // With no pair in the address, the latest is compared with the one before it.
  await expect(page).toHaveURL(new RegExp(`#/p/${AGENT}/diff/1\\.\\.2$`));
  await expect(page.getByTestId("diff-summary")).toHaveText("0 added, 0 removed, 1 changed, 5 unchanged");
  await expect(page.locator('tr[data-status="changed"]')).toHaveAttribute("data-path", CHANGED_FILE);
  await expect(page.locator('tr[data-path="procedure.aip"]')).toHaveAttribute("data-status", "unchanged");
  const diff = page.locator(`[data-testid="file-diff"][data-path="${CHANGED_FILE}"]`);
  await expect(diff.getByTestId("line-remove")).toContainText(OLD_LINE);
  await expect(diff.getByTestId("line-add")).toContainText(NEW_LINE);

  await page.getByRole("button", { name: "swap" }).click();
  await expect(page).toHaveURL(/diff\/2\.\.1$/);
  await expect(diff.getByTestId("line-add")).toContainText(OLD_LINE);
});
