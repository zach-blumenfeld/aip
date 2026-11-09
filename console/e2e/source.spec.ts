import { expect, test } from "@playwright/test";
import { CHANGED_FILE, NEW_LINE, OLD_LINE } from "./global-setup";

const FILES = ["SKILL.md", "assets/config.json", "assets/policy.md", "assets/reply.md",
               "references/help.md", "scripts/escalate.py", "source/README.md"];

test("the source page lists the manifest and shows a text file", async ({ page }) => {
  await page.goto("./#/p/billing-support/files");
  const manifest = page.getByRole("table", { name: "file manifest" });
  await expect(manifest).toBeVisible();
  for (const f of FILES) await expect(manifest.getByRole("link", { name: f, exact: true })).toHaveCount(1);
  await expect(manifest.getByRole("row")).toHaveCount(FILES.length + 1);

  await manifest.getByRole("link", { name: "scripts/escalate.py", exact: true }).click();
  await expect(page).toHaveURL(/\/files\/scripts\/escalate\.py$/);
  const text = page.getByTestId("file-text");
  await expect(text).toBeVisible();
  await expect(text.getByRole("listitem").first()).toContainText(/python|import|json/i);
  await expect(page.getByTestId("binary-file")).toHaveCount(0);
});

test("the diff shows the one changed line and nothing else", async ({ page }) => {
  // The procedure page resolves to the newest revision and links to the diff with the previous one.
  await page.goto("./#/p/billing-support");
  await page.getByRole("link", { name: "diff with previous" }).click();
  await expect(page).toHaveURL(/\/diff\/[0-9a-f]{16}\.\.[0-9a-f]{16}$/);

  await expect(page.getByTestId("diff-summary")).toHaveText(`0 added, 0 removed, 1 changed, ${FILES.length - 1} unchanged`);
  const rows = page.getByRole("table", { name: "manifest diff" }).locator("tbody tr");
  await expect(rows).toHaveCount(FILES.length);
  const changedRows = page.locator('[aria-label="manifest diff"] tr[data-status="changed"]');
  await expect(changedRows).toHaveCount(1);
  await expect(changedRows).toContainText(CHANGED_FILE);

  const fileDiff = page.getByTestId("file-diff");
  await expect(fileDiff).toHaveCount(1);
  await expect(fileDiff).toHaveAttribute("data-path", CHANGED_FILE);
  await expect(fileDiff.getByTestId("line-remove")).toHaveCount(1);
  await expect(fileDiff.getByTestId("line-add")).toHaveCount(1);
  await expect(fileDiff.getByTestId("line-remove")).toContainText(OLD_LINE);
  await expect(fileDiff.getByTestId("line-add")).toContainText(NEW_LINE);
  await expect(fileDiff.getByTestId("line-remove")).not.toContainText("45 days");

  // Swapping sides flips the direction of the change.
  await page.getByRole("button", { name: "swap" }).click();
  await expect(fileDiff.getByTestId("line-remove")).toContainText(NEW_LINE);
  await expect(fileDiff.getByTestId("line-add")).toContainText(OLD_LINE);
});

test("the same revision on both sides shows no changes", async ({ page }) => {
  await page.goto("./#/p/billing-support/diff");
  const to = page.getByRole("combobox", { name: "to revision" });
  const revision = await to.inputValue();
  await page.getByRole("combobox", { name: "from revision" }).selectOption(revision);
  await expect(page.getByTestId("diff-summary")).toHaveText("Same revision on both sides.");
  await expect(page.getByTestId("file-diff")).toHaveCount(0);
});
