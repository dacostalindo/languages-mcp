import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { callTool, hostLog, mountView, readResource, view } from "./host";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) => JSON.parse(readFileSync(join(here, "fixtures", name), "utf8"));
const SHOTS = join(here, "..", "screenshots");

async function shot(page: Page, name: string) {
  await page.waitForTimeout(150); // let size-changed settle
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}

async function waitFor(page: Page, method: string, pred: (p: any) => boolean = () => true) {
  await expect.poll(async () => (await hostLog(page)).some((m) => m.method === method && pred(m.params))).toBe(true);
  return (await hostLog(page)).filter((m) => m.method === method && pred(m.params)).at(-1)!;
}

test("ui resources are served as mcp-app html", async () => {
  for (const name of ["results", "explanation", "player"]) {
    const res = await readResource(`ui://dutch-exercises/${name}.html`);
    expect(res.mimeType).toBe("text/html;profile=mcp-app");
    expect(res.text).toContain("<!doctype html>");
  }
});

test("results view: cards, open link, rating", async ({ page }) => {
  const args = { results: fixture("results.json"), theme: "perfectum", level: "A2" };
  const result = await callTool("show_exercises", args);
  expect(result.structuredContent?.view).toBe("exercise_results");
  await mountView(page, "results", args, result);
  const v = view(page);

  await expect(v.getByRole("heading", { level: 2 })).toHaveCount(3);
  await expect(v.getByText("NT2 - A2 - Grammatica - Voltooide tijd - Oefening 1")).toBeVisible();
  await expect(v.getByLabel("Score 86 out of 100")).toBeVisible();
  await expect(v.getByText("not fetched: scored from search snippet only")).toBeVisible();
  await expect(v.getByText("Found via dutchgrammar.com/en/?n=Verbs.00")).toBeVisible();

  await v.getByRole("button", { name: /Open “NT2 - A2/ }).click();
  const open = await waitFor(page, "ui/open-link");
  expect(open.params.url).toBe("https://proefa.nt2taalmenu.nl/a2-grammatica-voltooide-tijd-1/");

  const rate4 = v.getByRole("group", { name: /Rate “NT2 - A2/ }).getByRole("button", { name: /Rate 4 of 5/ });
  await rate4.click();
  await expect(rate4).toHaveAttribute("aria-pressed", "true");
  await expect(v.getByText("Rated 4/5. Thanks!")).toBeVisible();
  const call = await waitFor(page, "tools/call", (p) => p.name === "rate_exercise");
  expect(call.params.arguments).toMatchObject({ rating: 4, level: "A2", theme: "perfectum" });
  await waitFor(page, "ui/update-model-context");
  const ratings = await callTool("list_ratings", {});
  expect(JSON.parse(ratings.content![0].text!).ratings[0]).toMatchObject({ rating: 4, level: "A2" });

  await shot(page, "results");
});

test("explanation view renders rule, table, examples and mistakes", async ({ page }) => {
  const args = fixture("explanation.json");
  const result = await callTool("show_explanation", args);
  await mountView(page, "explanation", args, result);
  const v = view(page);

  await expect(v.getByRole("heading", { level: 1 })).toHaveText("Het perfectum: hebben of zijn?");
  await expect(v.locator("table tbody tr")).toHaveCount(4);
  await expect(v.getByRole("rowheader", { name: "hij/zij" })).toBeVisible();
  await expect(v.locator(".examples li")).toHaveCount(3);
  await expect(v.locator(".summary strong").first()).toHaveText("hebben");
  await expect(v.locator("code").first()).toHaveText("Ik ben naar huis gegaan.");
  await expect(v.locator(".wrong").first()).toHaveText("Ik heb naar huis gegaan.");
  await expect(v.locator('section[aria-labelledby="s-0"] li')).toHaveCount(3);
  // Concertje: near-black canvas, white type, Redaction display headline
  await expect(v.locator("body")).toHaveCSS("background-color", "rgb(10, 10, 10)");
  await expect(v.locator("body")).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(v.locator("h1")).toHaveCSS("font-family", /Redaction/);
  expect(await v.locator("h1").evaluate(async () => {
    await document.fonts.ready;
    return document.fonts.check('16px "Redaction"') && document.fonts.check('800 16px Inter');
  })).toBe(true);
  await shot(page, "explanation");
});

test("views use the Concertje palette and follow the host's light/dark setting, not its colours", async ({ page }) => {
  const args = fixture("explanation.json");
  const result = await callTool("show_explanation", args);
  await mountView(page, "explanation", args, result, {
    theme: "light",
    variables: { "--color-background-primary": "rgb(38, 38, 36)", "--color-text-primary": "rgb(250, 240, 230)" },
  });
  const v = view(page);
  await expect(v.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(v.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(v.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(v.locator("body")).toHaveCSS("color", "rgb(10, 10, 10)");
  await shot(page, "explanation-light");
});

test("agent text is rendered as text, never as HTML", async ({ page }) => {
  const evil = '<img src=x onerror="window.parent.__pwned=1">';
  const args = {
    title: `Test ${evil}`,
    summary: `**vet** ${evil} [link](javascript:alert(1))`,
    examples: [{ nl: evil, en: "<script>alert(1)</script>" }],
    sections: [{ heading: "<b>kop</b>", body: "- <i>item</i>" }],
  };
  const result = await callTool("show_explanation", args);
  await mountView(page, "explanation", args, result);
  const v = view(page);
  await expect(v.getByRole("heading", { level: 1 })).toHaveText(`Test ${evil}`);
  await expect(v.locator("img, script:not([type=module]), b, i, a")).toHaveCount(0);
  await expect(v.locator(".summary strong")).toHaveText("vet");
  expect(await page.evaluate(() => (window as any).__pwned)).toBeUndefined();
});

test("player checks all five item types, gives feedback and reports the score", async ({ page }) => {
  const args = fixture("exercise_set.json");
  const result = await callTool("show_exercise_set", args);
  const setId = result.structuredContent!.set_id as string;
  await mountView(page, "player", args, result);
  const v = view(page);
  const q = (n: number) => v.locator(".item").nth(n);

  await expect(v.locator(".item")).toHaveCount(5);
  await expect(v.getByRole("button", { name: "Try again" })).toBeHidden();
  await expect(v.getByRole("button", { name: "Discuss my mistakes" })).toBeHidden();
  await shot(page, "player");

  // 1 mc: right (keyboard: focus the radio group and pick with the arrow keys)
  await q(0).getByRole("radio", { name: "heb" }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(q(0).getByRole("radio", { name: "ben" })).toBeChecked();
  // 2 gap: second gap wrong
  await q(1).getByLabel("Gap 1 of 2").fill("Hebben ");
  await q(1).getByLabel("Gap 2 of 2").fill("gekijkt");
  // 3 word order: right, using the keyboard
  for (const w of ["Ik", "heb", "mijn", "huiswerk", "gemaakt"]) {
    await q(2).getByRole("button", { name: `Add “${w}”` }).focus();
    await page.keyboard.press("Enter");
  }
  // 4 matching: right
  await q(3).getByLabel("Match for “lopen”").selectOption("gelopen");
  await q(3).getByLabel("Match for “zwemmen”").selectOption("gezwommen");
  await q(3).getByLabel("Match for “eten”").selectOption("gegeten");
  // 5 true/false: wrong
  await q(4).getByRole("radio", { name: "True" }).check();

  await v.getByRole("button", { name: "Check answers" }).click();
  await expect(v.getByLabel("Score: 3 out of 5")).toBeVisible();
  await expect(v.getByRole("button", { name: "Check answers" })).toBeHidden();
  await expect(q(0).locator(".feedback")).toContainText("Correct");
  await expect(q(1).locator(".feedback")).toContainText("Answer: hebben | gekeken");
  await expect(q(1).getByLabel("Gap 1 of 2")).toHaveAttribute("aria-invalid", "false");
  await expect(q(1).getByLabel("Gap 2 of 2")).toHaveAttribute("aria-invalid", "true");
  await expect(q(2).locator(".feedback")).toContainText("Correct");
  await expect(q(3).locator(".feedback")).toContainText("Correct");
  await expect(q(4).locator(".feedback")).toContainText("Not quite");
  await expect(q(4).locator(".feedback")).toContainText("Het is: ik ben gebleven.");

  const call = await waitFor(page, "tools/call", (p) => p.name === "record_attempt");
  expect(call.params.arguments.set_id).toBe(setId);
  expect(call.params.arguments.results.map((r: any) => r.correct)).toEqual([true, false, true, true, false]);
  const ctx = await waitFor(page, "ui/update-model-context");
  expect(ctx.params.content[0].text).toContain("3/5 correct on 'Perfectum: hebben of zijn?' (A2)");
  expect(ctx.params.structuredContent).toMatchObject({ set_id: setId, correct: 3, total: 5 });
  await expect(v.getByText("Your score is saved.")).toBeVisible();

  const attempts = JSON.parse((await callTool("list_attempts", {})).content![0].text!).attempts;
  expect(attempts[0]).toMatchObject({ set_id: setId, correct: 3, total: 5, wrong_items: ["q2", "q5"] });

  await v.getByRole("button", { name: "Discuss my mistakes" }).click();
  const message = await waitFor(page, "ui/message");
  expect(message.params.content[0].text).toContain("Can you explain my mistakes?");

  await shot(page, "player-checked");

  await v.getByRole("button", { name: "Try again" }).click();
  await expect(v.getByRole("button", { name: "Check answers" })).toBeEnabled();
  await expect(v.locator(".feedback")).toHaveCount(0);
});

test("player in the light theme", async ({ page }) => {
  const args = fixture("exercise_set.json");
  await mountView(page, "player", args, await callTool("show_exercise_set", args), { theme: "light" });
  const v = view(page);
  await expect(v.locator(".item")).toHaveCount(5);
  await expect(v.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await v.locator(".item").nth(0).getByRole("radio", { name: "is" }).check();
  await v.getByRole("button", { name: "Check answers" }).click();
  await expect(v.getByLabel(/Score: \d out of 5/)).toBeVisible();
  await shot(page, "player-light");
});

test("tool errors are shown as text", async ({ page }) => {
  await mountView(page, "player", {}, { isError: true, content: [{ type: "text", text: "items: field required" }] });
  await expect(view(page).getByRole("alert")).toHaveText("items: field required");
});
