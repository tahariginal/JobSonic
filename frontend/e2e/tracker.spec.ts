import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("track applications by company, filter statuses, and open the saved review", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Application tracker", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Application tracker" })).toBeVisible();
  const list = page.getByRole("list", { name: "Tracked applications" });
  await expect(list.getByText("Acme Robotics", { exact: true })).toBeVisible();
  await expect(list.getByText("Hooli", { exact: true })).toBeVisible();
  await page.getByLabel("Search companies or roles").fill("hooli");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list.getByText("Hooli", { exact: true })).toBeVisible();
  await page.getByLabel("Application status").selectOption("submitted");
  await expect(page.getByText("No matching applications", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(list.getByText("Acme Robotics", { exact: true })).toBeVisible();
  await page.getByLabel("Search companies or roles").fill("Junior Automation Engineer");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await list.getByRole("link", { name: "View application for Junior Automation Engineer at Hooli" }).click();
  await expect(page).toHaveURL(/\/application\/\?id=\d+/);
  await expect(page.getByLabel("Cover letter")).toBeVisible();
});

test("tracker explains how to start when empty and recovers from API errors", async ({ page }) => {
  await login(page);
  await page.route("**/api/application-tracker?*", (route) => route.fulfill({ status: 503, json: { detail: "Tracker unavailable" } }));
  await page.goto("/application-tracker/");
  await expect(page.getByRole("alert").filter({ hasText: "Tracker unavailable" })).toBeVisible();
  await expect(page.getByText("No applications yet", { exact: true })).toBeHidden();
  await page.unroute("**/api/application-tracker?*");
  await page.route("**/api/application-tracker?*", (route) => route.fulfill({ json: {
    items: [], total: 0, statuses: {}, summary: { companies: 0, applications: 0, awaiting_approval: 0, submitted: 0 },
  } }));
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("No applications yet", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Browse jobs" })).toHaveAttribute("href", "/jobs/");
});
