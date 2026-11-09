import { expect, test } from "@playwright/test";

test("the catalog lists the published procedure", async ({ page }) => {
  await page.goto("./");
  const table = page.getByRole("table", { name: "catalog" });
  await expect(table).toBeVisible();
  const row = table.getByRole("row").filter({ hasText: "billing-support" });
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("cell").nth(3)).toHaveText("2"); // the example and its one-line variant
});
