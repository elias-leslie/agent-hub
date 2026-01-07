// Run all screenshot scripts
const { chromium } = require("@playwright/test");
const path = require("path");
const fs = require("fs");

const screenshotsDir = path.join(__dirname, "..", "screenshots");

// Ensure screenshots directory exists
if (!fs.existsSync(screenshotsDir)) {
  fs.mkdirSync(screenshotsDir, { recursive: true });
}

async function captureAll() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
  });

  const pages = [
    { url: "/dashboard", name: "dashboard", fullPage: true },
    { url: "/chat", name: "chat", fullPage: false },
    { url: "/settings", name: "settings", fullPage: true },
    { url: "/sessions", name: "sessions-list", fullPage: true },
  ];

  for (const { url, name, fullPage } of pages) {
    const page = await context.newPage();

    console.log(`Capturing ${name}...`);
    try {
      await page.goto(`http://localhost:3003${url}`, { timeout: 60000 });
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);

      await page.screenshot({
        path: path.join(screenshotsDir, `${name}.png`),
        fullPage,
      });

      console.log(`  Saved: screenshots/${name}.png`);
    } catch (err) {
      console.error(`  Failed to capture ${name}:`, err.message);
    } finally {
      await page.close();
    }
  }

  await browser.close();
  console.log("\nScreenshot capture complete!");
}

captureAll().catch((err) => {
  console.error("Screenshot capture failed:", err);
  process.exit(1);
});
