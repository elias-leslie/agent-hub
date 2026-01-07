// Screenshot script for /chat page
const { chromium } = require("@playwright/test");

async function captureChat() {
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
  });

  await page.goto("http://localhost:3003/chat");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);

  await page.screenshot({
    path: "screenshots/chat.png",
    fullPage: false,
  });

  await browser.close();
  console.log("Chat screenshot saved to screenshots/chat.png");
}

captureChat().catch(console.error);
