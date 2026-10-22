import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The views run inside a mocked MCP Apps host (tests/host.ts). Tool calls go to the real Python server, started
// here over streamable HTTP with a throwaway DATA_DIR. Run `npm run build` first: the tests load ui_dist/*.html.
export const PORT = Number(process.env.UI_TEST_PORT ?? 8766);
const dataDir = mkdtempSync(join(tmpdir(), "dutch-ui-test-"));

export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    viewport: { width: 760, height: 900 },
    // Use a preinstalled Chromium when given (e.g. CHROMIUM_PATH=/opt/pw-browsers/chromium).
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `../.venv/bin/dutch-exercises-mcp --transport http --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/healthz`,
    env: { DATA_DIR: dataDir, MCP_APPS: "1" },
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
