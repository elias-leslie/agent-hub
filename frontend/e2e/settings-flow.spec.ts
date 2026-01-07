import { test, expect } from "@playwright/test";

test.describe("Settings Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/settings");
  });

  test("displays settings page with credentials section", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(page.getByText(/provider credentials/i)).toBeVisible();
  });

  test("has add credential button", async ({ page }) => {
    await expect(page.getByRole("button", { name: /add credential/i })).toBeVisible();
  });

  test("can open add credential form", async ({ page }) => {
    await page.getByRole("button", { name: /add credential/i }).click();

    // Form should appear
    await expect(page.getByText(/add new credential/i)).toBeVisible();
    await expect(page.getByText(/provider/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /save credential/i })).toBeVisible();
  });

  test("can cancel add credential form", async ({ page }) => {
    // Open form
    await page.getByRole("button", { name: /add credential/i }).click();
    await expect(page.getByText(/add new credential/i)).toBeVisible();

    // Cancel
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByText(/add new credential/i)).not.toBeVisible();
  });

  test("shows provider selector with Claude and Gemini", async ({ page }) => {
    await page.getByRole("button", { name: /add credential/i }).click();

    // Should have provider dropdown
    const providerSelect = page.locator("select").first();
    await expect(providerSelect).toBeVisible();

    // Check options
    const options = await providerSelect.locator("option").allTextContents();
    expect(options.some((opt) => opt.includes("Claude"))).toBeTruthy();
    expect(options.some((opt) => opt.includes("Gemini"))).toBeTruthy();
  });

  test("shows model preferences section", async ({ page }) => {
    await expect(page.getByText(/model preferences/i)).toBeVisible();
  });
});
