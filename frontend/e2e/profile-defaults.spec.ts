import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("saved motivation and start-date defaults can be edited and survive reload", async ({ page }) => {
  await login(page);
  await page.goto("/profile/");
  await page.getByRole("tab", { name: "Standard answers", exact: true }).click();
  const motivation = page.getByLabel("Why this company?", { exact: true });
  await expect(motivation).toHaveValue(/contribute to useful work/);
  await motivation.fill("I want to contribute practical work, learn from feedback, and grow with the team.");
  await page.getByRole("tab", { name: "Work authorization & preferences", exact: true }).click();
  await page.getByLabel("Earliest start date").fill("2027-01-07");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(page.getByText("You have unsaved changes.")).toBeHidden();
  await page.reload();
  await page.getByRole("tab", { name: "Work authorization & preferences", exact: true }).click();
  await expect(page.getByLabel("Earliest start date")).toHaveValue("2027-01-07");
  await page.getByRole("tab", { name: "Standard answers", exact: true }).click();
  await expect(motivation).toHaveValue("I want to contribute practical work, learn from feedback, and grow with the team.");
});
