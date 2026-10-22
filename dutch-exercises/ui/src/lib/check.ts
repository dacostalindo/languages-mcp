// Answer checking for the exercise player. Pure functions, no DOM, so they are easy to test.

export interface BaseItem {
  id: string;
  explanation?: string;
}
export interface McItem extends BaseItem { type: "mc"; prompt: string; options: string[]; answer: number }
export interface GapItem extends BaseItem { type: "gap"; text: string; answers: string[][]; hint?: string }
export interface OrderItem extends BaseItem { type: "order"; prompt?: string; words: string[]; alternatives?: string[][] }
export interface MatchItem extends BaseItem { type: "match"; prompt?: string; pairs: { left: string; right: string }[] }
export interface TrueFalseItem extends BaseItem { type: "truefalse"; statement: string; answer: boolean }
export type Item = McItem | GapItem | OrderItem | MatchItem | TrueFalseItem;

export interface ItemResult {
  item_id: string;
  type: Item["type"];
  correct: boolean;
  given: string;
  expected: string;
}

/** Splits gap text on runs of 3+ underscores (same rule as ui_models.GAP). */
export const GAP_RE = /_{3,}/;

/** Comparison key for typed answers. Keep in sync with ui_models.normalize_answer. */
export function normalize(s: string): string {
  return s
    .trim()
    .toLocaleLowerCase("nl")
    .replace(/\s+/g, " ")
    .replace(/^[ .,!?;:"'“”‘’]+|[ .,!?;:"'“”‘’]+$/g, "");
}

export function checkMc(item: McItem, chosen: number | null): ItemResult {
  return {
    item_id: item.id, type: "mc",
    correct: chosen === item.answer,
    given: chosen === null ? "" : item.options[chosen] ?? "",
    expected: item.options[item.answer],
  };
}

export function checkGap(item: GapItem, values: string[]): ItemResult & { perGap: boolean[] } {
  const perGap = item.answers.map((alts, i) => alts.some((a) => normalize(a) === normalize(values[i] ?? "")));
  return {
    item_id: item.id, type: "gap",
    correct: perGap.every(Boolean),
    given: values.map((v) => v.trim()).join(" | "),
    expected: item.answers.map((alts) => alts[0]).join(" | "),
    perGap,
  };
}

export function checkOrder(item: OrderItem, sequence: string[]): ItemResult {
  const key = (ws: string[]) => normalize(ws.join(" "));
  const given = key(sequence);
  const correct = sequence.length === item.words.length
    && [item.words, ...(item.alternatives ?? [])].some((ws) => key(ws) === given);
  return { item_id: item.id, type: "order", correct, given: sequence.join(" "), expected: item.words.join(" ") };
}

/** `chosen[i]` is the right-hand value picked for `pairs[i].left` ("" = nothing picked). */
export function checkMatch(item: MatchItem, chosen: string[]): ItemResult & { perPair: boolean[] } {
  const perPair = item.pairs.map((p, i) => normalize(chosen[i] ?? "") === normalize(p.right));
  return {
    item_id: item.id, type: "match",
    correct: perPair.every(Boolean),
    given: item.pairs.map((p, i) => `${p.left} = ${chosen[i] || "?"}`).join("; "),
    expected: item.pairs.map((p) => `${p.left} = ${p.right}`).join("; "),
    perPair,
  };
}

export function checkTrueFalse(item: TrueFalseItem, chosen: boolean | null): ItemResult {
  const word = (b: boolean) => (b ? "true" : "false");
  return {
    item_id: item.id, type: "truefalse",
    correct: chosen === item.answer,
    given: chosen === null ? "" : word(chosen),
    expected: word(item.answer),
  };
}

/** Fallback summary for the model when record_attempt is unavailable (the server builds a richer one). */
export function summarize(title: string, results: ItemResult[]): string {
  const right = results.filter((r) => r.correct).length;
  const wrong = results.filter((r) => !r.correct);
  const head = `${right}/${results.length} correct on '${title}'`;
  if (!wrong.length) return `${head}. No errors.`;
  return `${head}. Errors: ` + wrong
    .map((r) => `${r.item_id} (${r.type}) answered ${JSON.stringify(r.given || "(blank)")}, expected ${JSON.stringify(r.expected)}`)
    .join("; ");
}
