import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("configure a four-hour automatic cycle and see it in the tracker", async ({ page }) => {
  await login(page);
  await page.goto("/settings/?tab=schedule");
  await expect(page.getByRole("switch", { name: "Automatically fill applications", exact: true })).not.toBeChecked();
  await page.getByRole("switch", { name: "Automatically fill applications", exact: true }).click();
  await expect(page.getByRole("switch", { name: "Automatically fill applications", exact: true })).toBeChecked();
  await page.getByLabel("Search interval in hours").fill("4");
  await page.getByLabel("Search interval in hours").blur();
  await expect.poll(async () => (await (await page.request.get("/api/settings")).json()).schedule.discovery_interval_hours).toBe(4);
  await page.getByLabel("Applications per cycle").fill("10");
  await page.getByLabel("Applications per cycle").blur();
  await expect.poll(async () => (await (await page.request.get("/api/settings")).json()).automation.max_applications_per_cycle).toBe(10);
  await page.reload();
  await expect(page.getByRole("switch", { name: "Include other suitable jobs", exact: true })).toBeChecked();
  await expect(page.getByLabel("Applications per cycle")).toHaveValue("10");
  await page.goto("/application-tracker/");
  await expect(page.getByRole("heading", { name: "Automatic application cycle", exact: true })).toBeVisible();
  await expect(page.getByText("Every 4 hours", { exact: true })).toBeVisible();
  await expect(page.getByText(/Up to 10 new applications per cycle/)).toBeVisible();
  await page.getByRole("link", { name: "Manage automation" }).click();
  await page.getByRole("switch", { name: "Automatically fill applications", exact: true }).click();
  await expect(page.getByRole("switch", { name: "Automatically fill applications", exact: true })).not.toBeChecked();
  await page.goto("/application-tracker/");
  await expect(page.getByText("Schedule paused", { exact: true })).toBeVisible();
});
