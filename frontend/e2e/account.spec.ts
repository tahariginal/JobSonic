import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("account settings update sign-in details and validate confirmation", async ({ page }) => {
  await login(page);
  await page.goto("/settings/?tab=account");
  await expect(page.getByLabel("Username", { exact: true })).toHaveValue("admin");
  await page.getByLabel("Username", { exact: true }).fill("updated-admin");
  await page.getByLabel("Current password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("New password", { exact: true }).fill("updated-password-123");
  await page.getByLabel("Confirm new password", { exact: true }).fill("mismatched-password");
  await page.getByRole("button", { name: "Save account" }).click();
  await expect(page.getByText("New passwords do not match.", { exact: true })).toBeVisible();
  await page.getByLabel("Confirm new password", { exact: true }).fill("updated-password-123");
  await page.getByRole("button", { name: "Save account" }).click();
  await expect(page.getByLabel("Current password", { exact: true })).toHaveValue("");
  await expect(page.locator("aside")).toContainText("updated-admin");
  await page.reload();
  await expect(page.getByLabel("Username", { exact: true })).toHaveValue("updated-admin");

  // Restore fixture credentials using the new password, keeping the shared session valid.
  await page.getByLabel("Username", { exact: true }).fill("admin");
  await page.getByLabel("Current password", { exact: true }).fill("updated-password-123");
  await page.getByLabel("New password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Confirm new password", { exact: true }).fill("e2e-password-123");
  await page.getByRole("button", { name: "Save account" }).click();
  await expect(page.getByLabel("Current password", { exact: true })).toHaveValue("");
  await expect(page.locator("aside")).not.toContainText("updated-admin");
});
