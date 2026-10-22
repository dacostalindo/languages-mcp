// Connects a view to the host over the MCP Apps postMessage bridge. The views use the Concertje look (style.css),
// so only the host's light/dark preference is taken over, not its colours or fonts.
import { App, applyDocumentTheme, type McpUiHostContext } from "@modelcontextprotocol/ext-apps";
import { clear, h } from "./dom";
import "./style.css";

export const VERSION = "0.1.0";

export type CallResult = Awaited<ReturnType<App["callServerTool"]>>;

function applyContext(ctx: McpUiHostContext | undefined): void {
  if (!ctx) return;
  if (ctx.theme) applyDocumentTheme(ctx.theme);
}

/** Concertje masthead: mono label left, mono label right. */
export function masthead(left: string, right = ""): HTMLElement {
  return h("div", { class: "masthead" },
    h("span", { class: "label bright" }, left),
    right ? h("span", { class: "label" }, right) : null);
}

/** A status pill with a coloured dot (green / amber / red / grey). */
export function statusPill(text: string, dot: "green" | "amber" | "red" | "grey" | "", label?: string): HTMLElement {
  return h("span", { class: "pill", "aria-label": label ?? null },
    dot ? h("span", { class: `dot ${dot}`, "aria-hidden": "true" }, "●") : null, text);
}

export function root(): HTMLElement {
  return document.getElementById("app")!;
}

function showMessage(text: string, cls = "muted"): void {
  const el = root();
  clear(el);
  el.appendChild(h("p", { class: cls, role: cls === "error" ? "alert" : null }, text));
}

/** Text of a tool result's text blocks (for errors and fallbacks). */
export function resultText(r: { content?: unknown[] }): string {
  return (r.content ?? [])
    .map((c) => (c && typeof c === "object" && (c as { type?: string }).type === "text" ? (c as { text: string }).text : ""))
    .filter(Boolean)
    .join("\n");
}

/**
 * Start a view: `render` gets the tool result's structuredContent (checked against `view`) and the connected App.
 * Handlers are registered before connect() so the one-shot tool-input/tool-result notifications are not missed.
 */
export async function startView<T extends { view?: string }>(
  name: string,
  view: string,
  render: (data: T, app: App) => void,
): Promise<App> {
  const app = new App({ name: `dutch-exercises-${name}`, version: VERSION }, {}, { autoResize: true });
  app.ontoolinput = () => showMessage("Preparing…");
  app.ontoolcancelled = () => showMessage("Cancelled.");
  app.ontoolresult = (result) => {
    const data = result.structuredContent as T | undefined;
    if (result.isError || !data || data.view !== view) {
      showMessage(resultText(result) || "Nothing to show.", result.isError ? "error" : "muted");
      return;
    }
    try {
      render(data, app);
    } catch (err) {
      console.error(err);
      showMessage("Could not show this content.", "error");
    }
  };
  app.onhostcontextchanged = applyContext;
  await app.connect();
  applyContext(app.getHostContext());
  return app;
}
