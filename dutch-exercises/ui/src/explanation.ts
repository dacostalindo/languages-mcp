// Explanation view: a grammar or vocabulary explanation written by the agent.
import { clear, h, inline, markdown } from "./lib/dom";
import { masthead, root, startView } from "./lib/host";

interface Explanation {
  view: "explanation";
  title: string;
  level?: string;
  summary?: string;
  sections?: { heading: string; body: string }[];
  examples?: { nl: string; en?: string; note?: string }[];
  table?: { caption?: string; headers: string[]; rows: string[][] } | null;
  common_mistakes?: { wrong: string; right: string; why?: string }[];
}

function tableView(t: NonNullable<Explanation["table"]>, label = ""): HTMLElement {
  // A first column with an empty header (e.g. pronouns in a conjugation table) reads as row headers.
  const rowHeaders = t.headers[0]?.trim() === "";
  const cell = (c: string, i: number) => (i === 0 && rowHeaders ? h("th", { scope: "row" }, c) : h("td", null, inline(c)));
  const table = h("table", null,
    t.caption ? h("caption", null, t.caption) : null,
    h("thead", null, h("tr", null, t.headers.map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", null, t.rows.map((row) => h("tr", null, row.map(cell)))));
  return h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": label || t.caption || "Table" }, table);
}

function render(d: Explanation): void {
  const el = root();
  clear(el);
  el.appendChild(masthead("Explanation", d.level ? `Level ${d.level}` : ""));
  const card = h("article", { "aria-labelledby": "title" },
    h("header", { class: "header" },
      h("h1", { class: "hero", id: "title", lang: "nl" }, d.title),
      d.summary ? h("div", { class: "intro summary", lang: "nl" }, markdown(d.summary)) : null));

  const section = (title: string, id: string, ...body: (Node | null)[]) =>
    h("section", { class: "section card", "aria-labelledby": id }, h("h2", { class: "section-title", id }, title), body);

  (d.sections ?? []).forEach((s, i) =>
    card.appendChild(section(s.heading, `s-${i}`, h("div", { lang: "nl" }, markdown(s.body)))));
  if (d.table) {
    card.appendChild(section(d.table.caption || "Table", "table-h", tableView({ ...d.table, caption: "" }, d.table.caption)));
  }
  if (d.examples?.length) {
    card.appendChild(section("Examples", "examples-h",
      h("ul", { class: "examples" }, d.examples.map((e) => h("li", null,
        h("div", { class: "nl", lang: "nl" }, inline(e.nl)),
        e.en ? h("div", { class: "en" }, e.en) : null,
        e.note ? h("div", { class: "note", lang: "nl" }, e.note) : null)))));
  }
  if (d.common_mistakes?.length) {
    card.appendChild(section("Common mistakes", "mistakes-h",
      h("ul", { class: "mistakes" }, d.common_mistakes.map((m) => h("li", { class: "mistake" },
        h("div", { lang: "nl" },
          h("span", { class: "visually-hidden" }, "Wrong: "), h("span", { class: "wrong" }, m.wrong)),
        h("div", { lang: "nl" },
          h("span", { class: "visually-hidden" }, "Right: "), h("span", { class: "right" }, m.right)),
        m.why ? h("div", { class: "sub", lang: "nl" }, m.why) : null)))));
  }
  el.appendChild(card);
}

void startView<Explanation>("explanation", "explanation", (d) => render(d));
