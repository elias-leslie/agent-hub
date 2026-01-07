// Screenshot script for /settings page
const { chromium } = require("@playwright/test");

async function captureSettings() {
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
  });

  await page.goto("http://localhost:3003/settings");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);

  await page.screenshot({
    path: "screenshots/settings.png",
    fullPage: true,
  });

  await browser.close();
  console.log("Settings screenshot saved to screenshots/settings.png");
}

captureSettings().catch(console.error);
