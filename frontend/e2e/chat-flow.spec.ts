import { test, expect } from "@playwright/test";

test.describe("Chat Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/chat");
  });

  test("displays chat page with mode toggle", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Chat" })).toBeVisible();
    await expect(page.getByRole("button", { name: /single/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /roundtable/i })).toBeVisible();
  });

  test("can switch between single and roundtable modes", async ({ page }) => {
    // Start in single mode
    const singleBtn = page.getByRole("button", { name: /single/i });
    const roundtableBtn = page.getByRole("button", { name: /roundtable/i });

    // Click roundtable
    await roundtableBtn.click();
    await expect(roundtableBtn).toHaveClass(/bg-white/);

    // Click back to single
    await singleBtn.click();
    await expect(singleBtn).toHaveClass(/bg-white/);
  });

  test("shows model selector in single mode", async ({ page }) => {
    // In single mode, model selector should be visible
    await expect(page.getByText(/Claude Sonnet/i)).toBeVisible();
  });

  test("can open model selector dropdown", async ({ page }) => {
    // Click model selector
    await page.getByText(/Claude Sonnet/i).click();

    // Should show dropdown with models
    await expect(page.getByText(/Claude Opus/i)).toBeVisible();
    await expect(page.getByText(/Claude Haiku/i)).toBeVisible();
    await expect(page.getByText(/Gemini/i).first()).toBeVisible();
  });

  test("has chat input area", async ({ page }) => {
    // Chat panel should have input
    await expect(page.getByPlaceholder(/message/i)).toBeVisible();
  });
});
