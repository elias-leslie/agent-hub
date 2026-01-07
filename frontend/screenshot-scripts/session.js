// Screenshot script for /sessions/[id] page
const { chromium } = require("@playwright/test");

async function captureSession() {
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
  });

  // First go to sessions list
  await page.goto("http://localhost:3003/sessions");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);

  await page.screenshot({
    path: "screenshots/sessions-list.png",
    fullPage: true,
  });

  // Try to click first session if available
  const firstSession = page.locator("a[href^='/sessions/']").first();
  if (await firstSession.isVisible()) {
    await firstSession.click();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);

    await page.screenshot({
      path: "screenshots/session-detail.png",
      fullPage: true,
    });
  }

  await browser.close();
  console.log("Session screenshots saved to screenshots/");
}

captureSession().catch(console.error);
