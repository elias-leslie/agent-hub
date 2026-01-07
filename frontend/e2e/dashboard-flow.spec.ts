import { test, expect } from "@playwright/test";

test.describe("Dashboard Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard");
  });

  test("displays dashboard with Agent Hub branding", async ({ page }) => {
    await expect(page.getByText("Agent Hub")).toBeVisible();
    await expect(page.getByText(/monitoring dashboard/i)).toBeVisible();
  });

  test("shows KPI cards section", async ({ page }) => {
    // Should show key metrics
    await expect(page.getByText(/active sessions/i)).toBeVisible();
    await expect(page.getByText(/total cost/i)).toBeVisible();
    await expect(page.getByText(/requests/i)).toBeVisible();
    await expect(page.getByText(/error rate/i)).toBeVisible();
  });

  test("shows provider status section", async ({ page }) => {
    await expect(page.getByText(/provider status/i)).toBeVisible();
  });

  test("shows requests over time chart", async ({ page }) => {
    await expect(page.getByText(/requests over time/i)).toBeVisible();
  });

  test("shows cost by model chart", async ({ page }) => {
    await expect(page.getByText(/cost by model/i)).toBeVisible();
  });

  test("shows token usage section", async ({ page }) => {
    await expect(page.getByText(/token usage/i)).toBeVisible();
    await expect(page.getByText(/total tokens/i)).toBeVisible();
  });

  test("displays system status indicator", async ({ page }) => {
    // Should show status badge (healthy/degraded)
    const statusIndicator = page.locator(".rounded-full").first();
    await expect(statusIndicator).toBeVisible();
  });

  test("shows uptime information", async ({ page }) => {
    await expect(page.getByText(/uptime/i)).toBeVisible();
  });
});
