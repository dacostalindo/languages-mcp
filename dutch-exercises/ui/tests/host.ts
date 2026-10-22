// A minimal MCP Apps host for tests: renders a built view in a sandboxed srcdoc iframe (like real hosts), answers
// the ui/* JSON-RPC requests, forwards tools/call to the real Python server and logs everything the view sends.
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const DIST = join(here, "..", "..", "dutch_exercises", "ui_dist");
const PORT = Number(process.env.UI_TEST_PORT ?? 8766);

export interface ToolResult {
  content?: { type: string; text?: string }[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
}

let rpcId = 0;

/** Call a tool on the Python server over stateless streamable HTTP. */
export async function callTool(name: string, args: Record<string, unknown>): Promise<ToolResult> {
  const res = await fetch(`http://127.0.0.1:${PORT}/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method: "tools/call", params: { name, arguments: args } }),
  });
  const msg = await res.json();
  if (msg.error) throw new Error(`${name}: ${JSON.stringify(msg.error)}`);
  return msg.result;
}

export async function readResource(uri: string): Promise<{ uri: string; mimeType: string; text: string }> {
  const res = await fetch(`http://127.0.0.1:${PORT}/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method: "resources/read", params: { uri } }),
  });
  const msg = await res.json();
  if (msg.error) throw new Error(JSON.stringify(msg.error));
  return msg.result.contents[0];
}

export interface HostOptions {
  theme?: "light" | "dark";
  variables?: Record<string, string>;
}

export interface LoggedMessage {
  method: string;
  params?: any;
}

const HOST_PAGE = `<!doctype html><html><head><meta charset="utf-8"><style>
  body { margin: 0; padding: 16px; font-family: system-ui; background: #1f1f1f; }
  body.light { background: #f0f0f0; }
  iframe { width: 100%; border: 0; display: block; height: 200px; }
</style></head><body><iframe id="view" sandbox="allow-scripts allow-forms" title="MCP App view"></iframe></body></html>`;

/**
 * Mount `view` (results | explanation | player) in the mock host, with `toolArgs` and `toolResult` delivered as
 * the ui/notifications/tool-input and tool-result notifications after the handshake.
 */
export async function mountView(
  page: Page,
  view: string,
  toolArgs: Record<string, unknown>,
  toolResult: ToolResult,
  opts: HostOptions = {},
): Promise<void> {
  const html = readFileSync(join(DIST, `${view}.html`), "utf8");
  await page.exposeFunction("__callServer", (name: string, args: Record<string, unknown>) => callTool(name, args));
  await page.setContent(HOST_PAGE);
  await page.evaluate(
    ({ html, toolArgs, toolResult, opts }) => {
      const w = window as any;
      w.__log = [] as { method: string; params?: unknown }[];
      if (opts.theme === "light") document.body.classList.add("light");
      const frame = document.getElementById("view") as HTMLIFrameElement;
      const send = (msg: object) => frame.contentWindow!.postMessage({ jsonrpc: "2.0", ...msg }, "*");
      const hostContext = {
        theme: opts.theme ?? "dark",
        styles: opts.variables ? { variables: opts.variables } : undefined,
        displayMode: "inline",
        availableDisplayModes: ["inline"],
        platform: "web",
        locale: "en-US",
      };
      window.addEventListener("message", async (ev) => {
        if (ev.source !== frame.contentWindow) return;
        const msg = ev.data;
        if (!msg || msg.jsonrpc !== "2.0" || !msg.method) return;
        w.__log.push({ method: msg.method, params: msg.params });
        const reply = (result: unknown) => send({ id: msg.id, result });
        switch (msg.method) {
          case "ui/initialize":
            return reply({
              protocolVersion: msg.params.protocolVersion,
              hostInfo: { name: "mock-host", version: "0.0.1" },
              hostCapabilities: { openLinks: {}, serverTools: {}, logging: {}, updateModelContext: { text: {} }, message: { text: {} } },
              hostContext,
            });
          case "ui/notifications/initialized":
            send({ method: "ui/notifications/tool-input", params: { arguments: toolArgs } });
            send({ method: "ui/notifications/tool-result", params: toolResult });
            return;
          case "ui/notifications/size-changed":
            if (msg.params?.height) frame.style.height = `${Math.ceil(msg.params.height)}px`;
            return;
          case "tools/call":
            try {
              return reply(await w.__callServer(msg.params.name, msg.params.arguments ?? {}));
            } catch (err) {
              return send({ id: msg.id, error: { code: -32603, message: String(err) } });
            }
          case "ui/update-model-context":
          case "ui/open-link":
          case "ui/message":
            return reply({});
          default:
            if (msg.id !== undefined) send({ id: msg.id, error: { code: -32601, message: `unsupported: ${msg.method}` } });
        }
      });
      frame.srcdoc = html;
    },
    { html, toolArgs, toolResult, opts },
  );
}

export async function hostLog(page: Page): Promise<LoggedMessage[]> {
  return page.evaluate(() => (window as any).__log);
}

export function view(page: Page) {
  return page.frameLocator("#view");
}
