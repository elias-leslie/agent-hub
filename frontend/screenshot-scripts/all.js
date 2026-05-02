const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..", "..");
const indexPath = path.join(repoRoot, ".index.yaml");
const screenshotsDir = process.env.AGENT_HUB_SCREENSHOT_DIR
  ? path.resolve(process.env.AGENT_HUB_SCREENSHOT_DIR)
  : path.join(repoRoot, "docs", "screenshots");

const sessionName =
  process.env.AGENT_HUB_SCREENSHOT_SESSION || "agenthub-screenshots";
const theme = process.env.AGENT_HUB_SCREENSHOT_THEME || "dark";

function readHostIp() {
  if (!fs.existsSync(indexPath)) {
    return null;
  }

  const content = fs.readFileSync(indexPath, "utf8");
  const match = content.match(/^\s*host_ip:\s*([^\s]+)\s*$/m);

  return match ? match[1] : null;
}

function resolveBaseUrl() {
  const explicitBaseUrl = process.env.AGENT_HUB_SCREENSHOT_BASE_URL?.trim();
  if (explicitBaseUrl) {
    return explicitBaseUrl.replace(/\/$/, "");
  }

  const hostIp = readHostIp();
  if (hostIp) {
    return `http://${hostIp}:3003`;
  }

  return "http://localhost:3003";
}

const baseUrl = resolveBaseUrl();

function runStBrowser(args, { allowFailure = false } = {}) {
  const result = spawnSync(
    "st",
    ["browser", "--engine", "chrome", "--session", sessionName, "--color-scheme", theme, ...args],
    {
      cwd: repoRoot,
      stdio: "inherit",
      env: {
        ...process.env,
        ST_BROWSER_VIEWPORT_WIDTH:
          process.env.ST_BROWSER_VIEWPORT_WIDTH || "1440",
        ST_BROWSER_VIEWPORT_HEIGHT:
          process.env.ST_BROWSER_VIEWPORT_HEIGHT || "960",
      },
    },
  );

  if (result.status === 0 || allowFailure) {
    return;
  }

  throw new Error(`st browser ${args.join(" ")} failed with exit code ${result.status}`);
}

function closeBrowser() {
  runStBrowser(["close"], { allowFailure: true });
}

async function captureAll() {
  fs.mkdirSync(screenshotsDir, { recursive: true });

  const pages = [
    { route: "/", name: "landing" },
    { route: "/dashboard", name: "dashboard" },
    { route: "/persona", name: "persona-workspace" },
    { route: "/persona/settings", name: "persona-settings" },
    { route: "/sessions", name: "sessions-list" },
  ];

  console.log(`Using base URL: ${baseUrl}`);
  console.log(`Writing screenshots to: ${screenshotsDir}`);

  let failed = false;

  for (const page of pages) {
    const url = `${baseUrl}${page.route}`;
    const outputPath = path.join(screenshotsDir, `${page.name}.png`);

    console.log(`\nCapturing ${page.name}: ${url}`);

    try {
      closeBrowser();
      runStBrowser(["open", url]);
      runStBrowser(["wait", "--load", "networkidle"]);
      runStBrowser(["wait", "1500"]);
      runStBrowser(["screenshot", outputPath]);
      console.log(`Saved: ${path.relative(repoRoot, outputPath)}`);
    } catch (error) {
      failed = true;
      console.error(`Failed to capture ${page.name}: ${error.message}`);
    }
  }

  closeBrowser();

  if (failed) {
    process.exitCode = 1;
    return;
  }

  console.log("\nScreenshot capture complete.");
}

captureAll().catch((error) => {
  console.error("Screenshot capture failed:", error);
  process.exit(1);
});
