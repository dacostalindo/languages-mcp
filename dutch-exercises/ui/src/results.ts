// Exercise results view: renders find_exercises results as cards with an Open link and 1-5 rating buttons.
import type { App } from "@modelcontextprotocol/ext-apps";
import { clear, h, safeUrl } from "./lib/dom";
import { masthead, resultText, root, startView, statusPill } from "./lib/host";

interface Card {
  title: string;
  url: string;
  score?: number;
  source?: string;
  curated?: boolean;
  level?: { stated?: string[]; estimated?: string | null; fit?: string };
  skills?: string[];
  formats?: string[];
  has_answer_key?: boolean | null;
  free?: boolean | null;
  verified?: boolean;
  why?: string[];
  warnings?: string[];
  preview?: string;
  found_via?: string;
}

interface Results {
  view: "exercise_results";
  request?: { theme?: string; level?: string };
  results: Card[];
  tip?: string;
  errors?: string[];
}

// Level fit as a show-status pill: green = right level, amber = near, red = off.
const FIT: Record<string, [string, "green" | "amber" | "red" | "grey"]> = {
  exact: ["Level match", "green"],
  close: ["Level close", "amber"],
  off: ["Level off", "red"],
  estimated: ["Level match (est.)", "green"],
  estimated_close: ["Level close (est.)", "amber"],
  estimated_off: ["Level off (est.)", "red"],
  unknown: ["Level unknown", "grey"],
};

const RATING_LABELS = ["unusable", "poor", "okay", "good", "excellent"];

function levelText(level: Card["level"]): string {
  if (!level) return "";
  const stated = (level.stated ?? []).join("/");
  if (stated) return stated;
  return level.estimated ? `≈${level.estimated}` : "";
}

function ratingControl(app: App, card: Card, request: Results["request"]): HTMLElement {
  const status = h("span", { class: "status", role: "status" });
  const buttons: HTMLButtonElement[] = [];
  const rate = async (rating: number) => {
    buttons.forEach((b) => (b.disabled = true));
    status.textContent = "Saving…";
    try {
      const res = await app.callServerTool({
        name: "rate_exercise",
        arguments: { url: card.url, rating, level: request?.level ?? "", theme: request?.theme ?? "" },
      });
      if (res.isError) throw new Error(resultText(res) || "rating failed");
      buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(i + 1 === rating)));
      status.textContent = `Rated ${rating}/5. Thanks!`;
      void app.updateModelContext({
        content: [{ type: "text", text: `The learner rated "${card.title}" (${card.url}) ${rating}/5.` }],
      }).catch(() => undefined);
    } catch (err) {
      console.error(err);
      status.textContent = "Couldn't save the rating.";
    } finally {
      buttons.forEach((b) => (b.disabled = false));
    }
  };
  for (let i = 1; i <= 5; i++) {
    buttons.push(
      h("button", {
        type: "button",
        "aria-pressed": "false",
        "aria-label": `Rate ${i} of 5 (${RATING_LABELS[i - 1]})`,
        title: RATING_LABELS[i - 1],
        onclick: () => void rate(i),
      }, String(i)),
    );
  }
  return h("div", { class: "row" },
    h("div", { class: "rating", role: "group", "aria-label": `Rate “${card.title}”` },
      h("span", { class: "label", "aria-hidden": "true" }, "Rate"), buttons),
    status);
}

function cardView(app: App, card: Card, request: Results["request"], index: number): HTMLElement {
  const url = safeUrl(card.url);
  const score = Math.round(Number(card.score ?? 0));
  const [fitLabel, fitDot] = FIT[card.level?.fit ?? "unknown"] ?? [`Level ${card.level?.fit}`, "grey"];
  const lvl = levelText(card.level);
  const titleId = `card-title-${index}`;

  const open = h("button", {
    type: "button",
    class: "primary",
    disabled: !url,
    "aria-label": `Open “${card.title}” in a new window`,
    onclick: async () => {
      if (!url) return;
      const res = await app.openLink({ url }).catch(() => ({ isError: true }));
      if (res.isError) linkFallback.hidden = false;
    },
  }, "Open exercise");
  // When the host refuses openLink, show the URL so the learner can copy it.
  const linkFallback = h("p", { class: "small muted", hidden: true }, "Couldn't open the link. Copy it: ",
    h("code", null, card.url));

  const kicker = [card.source, card.curated ? "curated" : ""].filter(Boolean).join(" · ");
  const pills = [
    statusPill(lvl ? `${fitLabel} · ${lvl}` : fitLabel, fitDot),
    card.has_answer_key ? statusPill("Answer key", "green") : null,
    card.free === false ? statusPill("Paid / login", "red") : null,
    card.verified === false ? statusPill("Not fetched", "amber") : null,
  ];
  const chips = [...(card.skills ?? []), ...(card.formats ?? [])].map((t) => h("span", { class: "chip" }, t));

  return h("article", { class: "card", "aria-labelledby": titleId },
    h("div", { class: "spread" },
      h("div", null,
        kicker ? h("p", { class: "kicker" }, kicker) : null,
        h("h2", { class: "name", id: titleId }, card.title || card.url)),
      h("span", { class: `score${score < 45 ? " low" : ""}`, "aria-label": `Score ${score} out of 100`, title: "Score (0-100)" },
        String(score))),
    h("div", { class: "row" }, pills),
    chips.length ? h("div", { class: "row" }, chips) : null,
    card.preview ? h("p", { class: "sub" }, card.preview) : null,
    card.found_via ? h("p", { class: "sub" }, "Found via ", card.found_via) : null,
    card.why?.length ? h("ul", { class: "why", "aria-label": "Why it ranks here" },
      card.why.map((w) => h("li", null, w))) : null,
    card.warnings?.length ? h("ul", { class: "warnings", "aria-label": "Warnings" },
      card.warnings.map((w) => h("li", null, "▲ ", w))) : null,
    h("div", { class: "actions" }, open, ratingControl(app, card, request)),
    linkFallback);
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function render(data: Results, app: App): void {
  const el = root();
  clear(el);
  const req = data.request ?? {};
  const n = data.results.length;
  el.appendChild(masthead("Dutch exercises", [req.level, req.theme].filter(Boolean).join(" · ")));
  el.appendChild(h("header", { class: "header" },
    h("h1", { class: "hero", lang: req.theme ? "nl" : null }, req.theme ? capitalize(req.theme) : "Exercises"),
    h("p", { class: "intro" }, `${n} exercise${n === 1 ? "" : "s"}, best match first. Open one, then rate it so the next search gets better.`)));
  if (!data.results.length) {
    el.appendChild(h("p", { class: "muted" }, "No exercises found."));
  }
  el.appendChild(h("div", { class: "items", role: "list" },
    data.results.map((c, i) => {
      const card = cardView(app, c, req, i);
      card.setAttribute("role", "listitem");
      return card;
    })));
  if (data.tip) el.appendChild(h("p", { class: "small muted" }, "Tip: ", data.tip));
  if (data.errors?.length) {
    el.appendChild(h("details", { class: "small muted" }, h("summary", null, "Search notes"),
      h("ul", null, data.errors.map((e) => h("li", null, e)))));
  }
}

void startView<Results>("results", "exercise_results", render);
