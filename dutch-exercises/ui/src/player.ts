// Exercise player: renders an agent-written exercise set, checks answers in the view, shows per-item feedback,
// stores the attempt through the app-only record_attempt tool and tells the model the score.
import type { App } from "@modelcontextprotocol/ext-apps";
import {
  checkGap, checkMatch, checkMc, checkOrder, checkTrueFalse, GAP_RE, summarize,
  type GapItem, type Item, type ItemResult, type MatchItem, type McItem, type OrderItem, type TrueFalseItem,
} from "./lib/check";
import { clear, h, markdown, shuffle } from "./lib/dom";
import { masthead, resultText, root, startView, statusPill } from "./lib/host";

interface ExerciseSet {
  view: "exercise_set";
  set_id: string;
  title: string;
  level?: string;
  theme?: string;
  instructions?: string;
  items: Item[];
}

interface Rendered {
  el: HTMLElement;
  check(): ItemResult;
  /** Lock the inputs and mark right/wrong parts. */
  reveal(result: ItemResult): void;
}

const TYPE_LABEL: Record<Item["type"], string> = {
  mc: "Multiple choice", gap: "Fill in the gap", order: "Word order", match: "Matching", truefalse: "True or false",
};

function feedback(item: Item, result: ItemResult): HTMLElement {
  return h("div", { class: "feedback", role: "status" },
    h("div", { class: "verdict" },
      statusPill(result.correct ? "Correct" : "Not quite", result.correct ? "green" : "red"),
      result.correct ? null : h("span", { class: "answer" }, "Answer: ", h("strong", { lang: "nl" }, result.expected))),
    item.explanation ? h("div", { class: "explain", lang: "nl" }, markdown(item.explanation)) : null);
}

function shell(item: Item, index: number, body: HTMLElement | null, prompt: string | HTMLElement): HTMLElement {
  return h("li", { class: "card item", "data-item-id": item.id, "aria-label": `Question ${index + 1}` },
    h("p", { class: "kicker" }, h("span", { class: "num" }, String(index + 1).padStart(2, "0")), "  ", TYPE_LABEL[item.type]),
    typeof prompt === "string" ? h("div", { class: "prompt", lang: "nl" }, prompt) : prompt,
    body);
}

let uid = 0;

function renderMc(item: McItem, index: number): Rendered {
  const name = `mc-${++uid}`;
  const inputs = item.options.map((_, i) => h("input", { type: "radio", name, value: String(i) }));
  const labels = item.options.map((o, i) => h("label", { class: "option", lang: "nl" }, inputs[i], o));
  const legend = h("legend", { class: "visually-hidden" }, item.prompt);
  const el = shell(item, index, h("fieldset", null, legend, h("div", { class: "options" }, labels)), item.prompt);
  return {
    el,
    check: () => checkMc(item, inputs.findIndex((r) => r.checked) >= 0 ? inputs.findIndex((r) => r.checked) : null),
    reveal: (res) => {
      inputs.forEach((r, i) => {
        r.disabled = true;
        if (i === item.answer) labels[i].classList.add("is-answer");
        else if (r.checked) labels[i].classList.add("is-wrong");
      });
      el.appendChild(feedback(item, res));
    },
  };
}

function renderGap(item: GapItem, index: number): Rendered {
  const parts = item.text.split(GAP_RE);
  const inputs: HTMLInputElement[] = [];
  const line = h("div", { class: "prompt gap-text", lang: "nl" });
  parts.forEach((part, i) => {
    line.appendChild(document.createTextNode(part));
    if (i < parts.length - 1) {
      const input = h("input", {
        type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
        "aria-label": parts.length > 2 ? `Gap ${i + 1} of ${parts.length - 1}` : "Your answer",
      });
      inputs.push(input);
      line.appendChild(input);
    }
  });
  const hint = item.hint ? h("div", { class: "small muted", lang: "nl" }, "Hint: ", item.hint) : null;
  const el = shell(item, index, hint, line);
  return {
    el,
    check: () => checkGap(item, inputs.map((i) => i.value)),
    reveal: (res) => {
      const per = (res as ReturnType<typeof checkGap>).perGap;
      inputs.forEach((input, i) => {
        input.readOnly = true;
        input.classList.add(per[i] ? "ok" : "bad");
        input.setAttribute("aria-invalid", String(!per[i]));
      });
      el.appendChild(feedback(item, res));
    },
  };
}

function renderOrder(item: OrderItem, index: number): Rendered {
  // Shuffle the chips; avoid handing out the answer as the starting order.
  let bank = item.words.map((w, i) => ({ w, i }));
  for (let tries = 0; tries < 5; tries++) {
    bank = shuffle(bank);
    if (bank.some((b, i) => b.i !== i)) break;
  }
  const chosen: { w: string; i: number }[] = [];
  const answerLine = h("div", { class: "chips answer-line", role: "group", "aria-label": "Your sentence" });
  const bankEl = h("div", { class: "chips", role: "group", "aria-label": "Words to use" });
  const live = h("span", { class: "visually-hidden", "aria-live": "polite" });
  let locked = false;

  const draw = () => {
    clear(answerLine);
    clear(bankEl);
    if (!chosen.length) answerLine.appendChild(h("span", { class: "small muted" }, "Click the words in the right order."));
    chosen.forEach((c, pos) => answerLine.appendChild(h("button", {
      type: "button", class: "chip", lang: "nl", disabled: locked, "data-word": c.w,
      "aria-label": `Remove “${c.w}” (position ${pos + 1})`,
      onclick: () => { chosen.splice(pos, 1); bank.push(c); live.textContent = `Removed ${c.w}`; draw(); focusFirst(bankEl); },
    }, c.w)));
    bank.forEach((b, pos) => bankEl.appendChild(h("button", {
      type: "button", class: "chip", lang: "nl", disabled: locked, "data-word": b.w,
      "aria-label": `Add “${b.w}”`,
      onclick: () => {
        bank.splice(pos, 1);
        chosen.push(b);
        live.textContent = `${b.w} added: ${chosen.map((c) => c.w).join(" ")}`;
        draw();
        focusFirst(bankEl.children.length ? bankEl : answerLine);
      },
    }, b.w)));
  };
  const focusFirst = (container: HTMLElement) => (container.querySelector("button") as HTMLButtonElement | null)?.focus();
  draw();

  const body = h("div", { class: "order" }, answerLine, bankEl, live);
  const el = shell(item, index, body, item.prompt || h("div", { class: "prompt" }, "Put the words in the right order."));
  return {
    el,
    check: () => checkOrder(item, chosen.map((c) => c.w)),
    reveal: (res) => {
      locked = true;
      draw();
      bankEl.hidden = !bank.length;
      answerLine.classList.add(res.correct ? "ok" : "bad");
      el.appendChild(feedback(item, res));
    },
  };
}

function renderMatch(item: MatchItem, index: number): Rendered {
  const rights = shuffle(item.pairs.map((p) => p.right));
  const selects = item.pairs.map((p) => h("select", { "aria-label": `Match for “${p.left}”`, lang: "nl" },
    h("option", { value: "" }, "Choose…"),
    rights.map((r) => h("option", { value: r }, r))));
  const grid = h("div", { class: "match-grid" },
    item.pairs.flatMap((p, i) => [h("span", { lang: "nl" }, p.left), selects[i]]));
  const el = shell(item, index, grid, item.prompt || h("div", { class: "prompt" }, "Match the pairs."));
  return {
    el,
    check: () => checkMatch(item, selects.map((s) => s.value)),
    reveal: (res) => {
      const per = (res as ReturnType<typeof checkMatch>).perPair;
      selects.forEach((s, i) => {
        s.disabled = true;
        s.classList.add(per[i] ? "ok" : "bad");
      });
      el.appendChild(feedback(item, res));
    },
  };
}

function renderTrueFalse(item: TrueFalseItem, index: number): Rendered {
  const name = `tf-${++uid}`;
  const yes = h("input", { type: "radio", name, value: "true" });
  const no = h("input", { type: "radio", name, value: "false" });
  const yesL = h("label", { class: "option" }, yes, "True");
  const noL = h("label", { class: "option" }, no, "False");
  const fs = h("fieldset", null, h("legend", { class: "visually-hidden" }, item.statement),
    h("div", { class: "row" }, yesL, noL));
  const el = shell(item, index, fs, item.statement);
  return {
    el,
    check: () => checkTrueFalse(item, yes.checked ? true : no.checked ? false : null),
    reveal: (res) => {
      [yes, no].forEach((r) => (r.disabled = true));
      (item.answer ? yesL : noL).classList.add("is-answer");
      if (!res.correct && (yes.checked || no.checked)) (item.answer ? noL : yesL).classList.add("is-wrong");
      el.appendChild(feedback(item, res));
    },
  };
}

function renderItem(item: Item, index: number): Rendered {
  switch (item.type) {
    case "mc": return renderMc(item, index);
    case "gap": return renderGap(item, index);
    case "order": return renderOrder(item, index);
    case "match": return renderMatch(item, index);
    case "truefalse": return renderTrueFalse(item, index);
  }
}

async function report(app: App, data: ExerciseSet, results: ItemResult[], status: HTMLElement): Promise<string> {
  let summary = summarize(data.title, results);
  try {
    const payload = results.map(({ item_id, type, correct, given, expected }) => ({ item_id, type, correct, given, expected }));
    const res = await app.callServerTool({ name: "record_attempt", arguments: { set_id: data.set_id, results: payload } });
    if (res.isError) throw new Error(resultText(res));
    summary = (res.structuredContent as { summary?: string } | undefined)?.summary ?? summary;
    status.textContent = "Your score is saved.";
  } catch (err) {
    console.error("record_attempt failed", err);
    status.textContent = "Couldn't save your score.";
  }
  const right = results.filter((r) => r.correct).length;
  try {
    await app.updateModelContext({
      content: [{ type: "text", text: `Exercise player result (set ${data.set_id}): ${summary}` }],
      structuredContent: {
        set_id: data.set_id, title: data.title, correct: right, total: results.length,
        wrong: results.filter((r) => !r.correct).map(({ item_id, given, expected }) => ({ item_id, given, expected })),
      },
    });
  } catch (err) {
    console.error("updateModelContext failed", err);
  }
  return summary;
}

function render(data: ExerciseSet, app: App): void {
  const el = root();
  clear(el);
  const rendered = data.items.map(renderItem);
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  const score = h("div", { class: "scorebar", "aria-live": "polite" });
  const discuss = h("button", { type: "button", hidden: true }, "Discuss my mistakes");
  const again = h("button", { type: "button", hidden: true, onclick: () => render(data, app) }, "Try again");
  const checkBtn = h("button", { type: "button", class: "primary" }, "Check answers");

  checkBtn.addEventListener("click", async () => {
    checkBtn.disabled = true;
    const results = rendered.map((r) => r.check());
    rendered.forEach((r, i) => {
      r.reveal(results[i]);
      r.el.classList.add(results[i].correct ? "correct" : "incorrect");
    });
    const right = results.filter((r) => r.correct).length;
    score.replaceChildren(`${right}`, h("span", { class: "of" }, ` / ${results.length}`));
    score.setAttribute("aria-label", `Score: ${right} out of ${results.length}`);
    checkBtn.hidden = true;
    again.hidden = false;
    status.textContent = "Saving…";
    const summary = await report(app, data, results, status);
    if (right < results.length) {
      discuss.hidden = false;
      discuss.onclick = async () => {
        discuss.disabled = true;
        const res = await app.sendMessage({
          role: "user",
          content: [{ type: "text", text: `I finished "${data.title}": ${summary} Can you explain my mistakes?` }],
        }).catch(() => ({ isError: true }));
        if (res.isError) {
          discuss.disabled = false;
          status.textContent = "Couldn't send the message. Ask in the chat instead.";
        }
      };
    }
  });

  el.appendChild(masthead("Exercises", [data.level, data.theme].filter(Boolean).join(" · ")));
  el.appendChild(h("header", { class: "header" },
    h("h1", { class: "hero", lang: "nl" }, data.title),
    data.instructions ? h("div", { class: "intro", lang: "nl" }, markdown(data.instructions)) : null));
  el.appendChild(h("ol", { class: "items" }, rendered.map((r) => r.el)));
  el.appendChild(h("div", { class: "actions" }, h("div", { class: "row" }, checkBtn, again, discuss), score));
  el.appendChild(status);
}

void startView<ExerciseSet>("player", "exercise_set", render);
