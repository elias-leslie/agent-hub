// Screenshot script for /dashboard page
const { chromium } = require("@playwright/test");

async function captureDashboard() {
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
  });

  await page.goto("http://localhost:3003/dashboard");
  await page.waitForLoadState("networkidle");

  // Wait for data to load
  await page.waitForTimeout(1000);

  await page.screenshot({
    path: "screenshots/dashboard.png",
    fullPage: true,
  });

  await browser.close();
  console.log("Dashboard screenshot saved to screenshots/dashboard.png");
}

captureDashboard().catch(console.error);
