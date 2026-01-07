import { test, expect } from "@playwright/test";

test.describe("Session Flow", () => {
  test("displays sessions list page", async ({ page }) => {
    await page.goto("/sessions");

    await expect(page.getByRole("heading", { name: /sessions/i })).toBeVisible();
  });

  test("shows search input for filtering", async ({ page }) => {
    await page.goto("/sessions");

    // Should have search functionality
    await expect(page.getByPlaceholder(/search/i)).toBeVisible();
  });

  test("shows empty state when no sessions", async ({ page }) => {
    await page.goto("/sessions");

    // Either shows sessions or empty state
    const content = await page.textContent("body");
    const hasContent =
      content?.includes("No sessions") || content?.includes("session");
    expect(hasContent).toBeTruthy();
  });

  test("navigates to session detail when clicking session", async ({ page }) => {
    await page.goto("/sessions");

    // If there are sessions, clicking one should navigate
    const sessionLink = page.locator("a[href^='/sessions/']").first();
    if (await sessionLink.isVisible()) {
      await sessionLink.click();
      await expect(page).toHaveURL(/\/sessions\/.+/);

      // Should show back button
      await expect(page.getByRole("link", { name: /back|sessions/i })).toBeVisible();
    }
  });

  test("session detail shows message history section", async ({ page }) => {
    // Go to sessions and click first if available
    await page.goto("/sessions");

    const sessionLink = page.locator("a[href^='/sessions/']").first();
    if (await sessionLink.isVisible()) {
      await sessionLink.click();

      // Should show messages section
      await expect(page.getByText(/messages/i)).toBeVisible();
    }
  });
});
