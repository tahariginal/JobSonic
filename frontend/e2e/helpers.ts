import { expect, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const AUTH = path.join(__dirname, ".auth.json");

/** Sign in through the real form. */
export async function loginFresh(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

/** Reuse one signed-in session across tests: the login rate limit (6 per 5 minutes) stays as in production. */
export async function login(page: Page) {
  if (fs.existsSync(AUTH)) {
    await page.context().addCookies(JSON.parse(fs.readFileSync(AUTH, "utf8")));
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    return;
  }
  await loginFresh(page);
  fs.writeFileSync(AUTH, JSON.stringify(await page.context().cookies()));
}
