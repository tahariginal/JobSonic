import { expect, test } from "@playwright/test";
import { login, loginFresh } from "./helpers";

test.describe.configure({ mode: "serial" });

test("unauthenticated visitors are sent to sign-in and bad passwords are refused", async ({ page }) => {
  await page.goto("/jobs/");
  await expect(page).toHaveURL(/\/login\/$/);
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid username or password")).toBeVisible();
  expect((await page.request.get("/api/overview")).status()).toBe(401);
});

test("overview shows real numbers and marks unavailable metrics", async ({ page }) => {
  await login(page);
  const stat = (label: string) => page.locator("section[aria-label='Key numbers'] > *").filter({ hasText: label });
  await expect(stat("Jobs discovered")).toContainText("10");
  await expect(stat("Awaiting approval")).toContainText("2");
  await expect(stat("Submitted")).toContainText("0");
  await expect(stat("Response rate")).toContainText("Not available yet");
  await expect(page.getByText("2 applications waiting for your approval")).toBeVisible();
  await expect(page.getByText("Search finished: 10 new")).toBeVisible();
  // charts have a table alternative
  const visa = page.getByRole("region", { name: "Visa sponsorship" });
  await visa.getByRole("button", { name: "Show as table" }).click();
  await expect(visa.getByRole("table")).toContainText("Confirmed");
});

test("jobs table: search, filters, sorting, rejection reasons and evidence panel", async ({ page }) => {
  await login(page);
  await page.goto("/jobs/");
  const rows = page.locator("tbody tr");
  await expect(page.getByRole("columnheader")).toHaveText(["Company", "Role", "What you'll do", "Fit", "Salary", "Location / Mode", "Visa", "Apply"]);
  await expect(rows.filter({ hasText: "Engineer" }).first()).toBeVisible(); // real rows, not loading placeholders
  const matches = await rows.count();
  expect(matches).toBeGreaterThan(3);

  await page.getByLabel("Search jobs").fill("automation");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Junior Automation Engineer");
  await page.getByLabel("Search jobs").fill("");

  await page.getByRole("button", { name: /Filters/ }).click();
  await page.locator("label").filter({ hasText: "Visa sponsorship" }).locator("select").selectOption("confirmed");
  await expect(rows).toHaveCount(2);
  for (const r of await rows.all()) await expect(r).toContainText("Confirmed");
  await page.locator("label").filter({ hasText: "Country" }).locator("select").selectOption("Germany");
  await expect(rows).toHaveCount(1);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(rows).toHaveCount(matches);

  await page.getByLabel("Sort").selectOption("company");
  await expect(rows.first()).toContainText("Acme Robotics");

  await page.getByRole("tab", { name: "Filtered out" }).click();
  await expect(rows.filter({ hasText: "Senior Platform Engineer" })).toContainText("senior-level role");
  await expect(rows.filter({ hasText: "Hooli" })).toContainText("existing local work authorization");

  // detail panel with evidence, by keyboard
  await page.getByRole("tab", { name: "Matches" }).click();
  const row = rows.filter({ hasText: "Junior Backend Engineer" });
  await row.focus();
  await page.keyboard.press("Enter");
  const panel = page.getByRole("dialog");
  await expect(panel.getByRole("heading", { name: "Junior Backend Engineer", exact: true })).toBeVisible();
  await expect(panel).toContainText("We offer visa sponsorship and relocation support for this role.");
  await expect(panel).toContainText("Source: official posting");
  await expect(panel).toContainText("computed by rules, no AI");
  await expect(panel.getByText("Verified").first()).toBeVisible();
  await panel.getByRole("button", { name: "Save" }).click();
  await expect(panel.getByRole("button", { name: "Saved" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await page.getByRole("tab", { name: "Saved" }).click();
  await expect(rows).toHaveCount(1);
});

test("pipeline board reflects real states and enforces the workflow", async ({ page }) => {
  await login(page);
  await page.goto("/pipeline/");
  const col = (name: string) => page.getByRole("region", { name, exact: true });
  await expect(col("Awaiting approval").locator("li")).toHaveCount(2);
  const card = col("Verified").locator("li").filter({ hasText: "AI Agent Engineer" });
  // the move menu only offers transitions the backend allows: no jumping straight to Submitted
  await expect(card.getByRole("combobox").locator("option")).toHaveText(["Move to…", "Hide", "Shortlisted"]);
  await card.getByRole("combobox").selectOption("shortlisted");
  await expect(col("Shortlisted").locator("li").filter({ hasText: "AI Agent Engineer" })).toBeVisible();
  // the API itself refuses a forced jump
  const csrf = (await (await page.request.get("/api/auth/me")).json()).csrf_token;
  const id = (await (await page.request.get("/api/jobs?q=AI Agent")).json()).items[0].id;
  const forced = await page.request.post(`/api/jobs/${id}/stage`, { data: { to: "submitted" }, headers: { "X-CSRF-Token": csrf } });
  expect(forced.status()).toBe(409);
  // leaving the approval queue needs confirmation
  const waiting = col("Awaiting approval").locator("li").filter({ hasText: "Junior Automation Engineer" });
  await waiting.getByRole("combobox").selectOption("shortlisted");
  const modal = page.getByRole("dialog", { name: "Confirm this change" });
  await expect(modal).toContainText("Any approval for the current version will be cancelled");
  await modal.getByRole("button", { name: "Cancel" }).click();
  await expect(col("Awaiting approval").locator("li")).toHaveCount(2);
});

test("approval inbox: review, edit invalidates, approve the exact version", async ({ page }) => {
  await login(page);
  await page.goto("/approvals/");
  await expect(page.getByText("Ready to review")).toHaveCount(2);
  await page.getByRole("link", { name: /Junior Automation Engineer/ }).click();
  await expect(page.getByRole("heading", { name: "Junior Automation Engineer" })).toBeVisible();
  await expect(page.getByText("Awaiting your approval")).toBeVisible();
  await expect(page.getByLabel("Cover letter")).toHaveValue(/1337 School/);
  await expect(page.getByText("From your profile").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & submit" })).toBeVisible();

  // editing an answer creates a new version and removes the ability to approve until the form is filled again
  await page.getByLabel("Phone").fill("+212611111111");
  await expect(page.getByText("Unsaved changes")).toBeVisible();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("version 2")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & submit" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Fill form for review" })).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByText("v2 · edited by you")).toBeVisible();

  // second application: approve
  await page.goto("/approvals/");
  await page.getByRole("link", { name: /Junior Backend Engineer/ }).click();
  await page.getByRole("tab", { name: /Form screenshots/ }).click();
  await expect(page.getByRole("img", { name: /Form screenshot/ })).toBeVisible();
  await page.getByRole("tab", { name: "What will be sent" }).click();
  await page.getByRole("button", { name: "Approve & submit" }).click();
  const modal = page.getByRole("dialog", { name: "Approve and submit this application?" });
  await expect(modal).toContainText("press submit once");
  await expect(modal).toContainText("cv.pdf");
  await modal.getByRole("button", { name: "Approve & submit" }).click();
  await expect(page.getByText("Approved — queued to send")).toBeVisible();
  await expect(page.getByLabel("Cover letter")).toBeDisabled();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  await page.goto("/approvals/");
  await expect(page.getByText("Ready to review")).toHaveCount(0);
});

test("profile editor saves and reloads verified data", async ({ page }) => {
  await login(page);
  await page.goto("/profile/");
  await expect(page.getByLabel("Citizenship")).toHaveValue("Moroccan");
  await page.getByLabel("City").fill("Khouribga");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("Profile saved")).toBeVisible();
  await page.getByRole("tab", { name: "Education & experience" }).click();
  await expect(page.getByLabel("Credential (exact wording)")).toHaveValue("42 Common Core (completed)");
  await page.getByRole("tab", { name: "CVs & documents" }).click();
  await expect(page.getByText("Main CV")).toBeVisible();
  await page.locator("#doc-upload").setInputFiles({ name: "evil.pdf", mimeType: "application/pdf", buffer: Buffer.from("<script>alert(1)</script>") });
  await expect(page.getByText("File content does not match its extension")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("City")).toHaveValue("Khouribga");
});

test("settings: schedule persists, sources listed, AI is off by default", async ({ page }) => {
  await login(page);
  await page.goto("/settings/");
  const interval = page.getByLabel("Search interval in hours");
  await interval.fill("6");
  await interval.blur();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Search interval in hours")).toHaveValue("6");
  await page.getByRole("tab", { name: "Job sources" }).click();
  await expect(page.getByText("5 active of 5")).toBeVisible();
  await page.getByRole("tab", { name: "AI", exact: true }).click();
  await expect(page.getByText("AI is off — the system runs on rules only")).toBeVisible();
  await page.getByRole("tab", { name: "Email" }).click();
  await expect(page.getByText("Needs configuration")).toBeVisible();
  await page.getByRole("tab", { name: "System" }).click();
  await expect(page.getByText("auth.login").first()).toBeVisible();
});

test("activity feed and notifications show backend events", async ({ page }) => {
  await login(page);
  await page.goto("/activity/");
  await expect(page.getByText("Approved revision 1: Acme Robotics — Junior Backend Engineer.")).toBeVisible();
  await expect(page.getByText("Worker idle").or(page.getByText("Submit Application")).first()).toBeVisible();
  await page.getByRole("button", { name: /Notifications/ }).click();
  await expect(page.getByText("Review & approve: Junior Backend Engineer")).toBeVisible();
  await page.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeVisible();
});

test("sign out ends the session", async ({ page }) => {
  await loginFresh(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login\/$/);
  expect((await page.request.get("/api/profile")).status()).toBe(401);
});
