import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const PAGES = ["/", "/jobs/", "/pipeline/", "/approvals/", "/activity/", "/analytics/", "/profile/", "/settings/"];

test("no page scrolls sideways and navigation is reachable", async ({ page }) => {
  await login(page);
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  const mobileNav = page.getByRole("navigation", { name: "Main" }).filter({ has: page.getByRole("button", { name: "More" }) });
  const sidebar = page.locator("aside");
  expect((await mobileNav.isVisible()) || (await sidebar.isVisible())).toBe(true);
});

test("an application can be reviewed on a small screen", async ({ page }) => {
  await login(page);
  await page.goto("/approvals/");
  await page.getByRole("link").filter({ hasText: /Engineer/ }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByLabel("Cover letter")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const box = await page.getByRole("tab", { name: "What will be sent" }).boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(32);
});

test("job details open as a sheet on small screens", async ({ page }) => {
  await login(page);
  await page.goto("/jobs/");
  await page.getByRole("button").filter({ hasText: "AI Agent Engineer" }).first().click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByRole("heading", { name: "AI Agent Engineer", exact: true })).toBeVisible();
  await expect(panel).toContainText("Remote from Morocco");
  await panel.getByRole("button", { name: "Close" }).click();
  await expect(panel).toBeHidden();
});
