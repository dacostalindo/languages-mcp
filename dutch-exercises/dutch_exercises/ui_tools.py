"""MCP Apps (`io.modelcontextprotocol/ui`) views for the dutch-exercises server.

Tools bound to a `ui://` view:

  show_exercises      find_exercises results as cards (open link, 1-5 rating buttons)
  show_explanation    a grammar/vocabulary explanation the agent wrote (rule, examples, table, mistakes)
  show_exercise_set   an interactive exercise player (mc, gap, order, match, truefalse); checks answers in the view
  record_attempt      app-only: the player stores the learner's per-item results

Plus `list_attempts` (a plain tool) so the agent can look back at earlier scores.

Hosts without MCP Apps support get the same content as readable text, so every tool stays useful there. The views
are single-file HTML builds of `ui/` (see README), shipped in `ui_dist/` so running the server needs no Node.
"""

from __future__ import annotations

import secrets
from importlib import resources

from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent
from pydantic import Field

from .levels import parse_level
from .ui_models import (
    Example,
    ExerciseCard,
    ExerciseSet,
    ExplanationSection,
    GapFill,
    Item,
    ItemResult,
    Matching,
    Mistake,
    MultipleChoice,
    Table,
    TrueFalse,
    WordOrder,
    answer_key,
)

RESULTS_URI = "ui://dutch-exercises/results.html"
EXPLANATION_URI = "ui://dutch-exercises/explanation.html"
PLAYER_URI = "ui://dutch-exercises/player.html"

VIEWS = {RESULTS_URI: "results.html", EXPLANATION_URI: "explanation.html", PLAYER_URI: "player.html"}

UI_INSTRUCTIONS = """\

Showing things to the learner (hosts with MCP Apps render these as interactive views; others get text):
- show_exercises renders find_exercises results as cards with Open links and 1-5 rating buttons. Pass the
  `results` of an earlier find_exercises call to avoid searching again.
- show_explanation renders a grammar or vocabulary explanation you write: rule, Dutch examples with
  translations, an optional table (e.g. a conjugation) and common mistakes.
- show_exercise_set renders exercises you write (mc, gap, order, match, truefalse) with their answer keys. The
  view checks answers and reports the score back to you; list_attempts shows earlier scores.
Write the content in Dutch and keep UI-facing explanations short.
"""

apps = Apps()


def _html(filename: str) -> str:
    try:
        return (resources.files("dutch_exercises") / "ui_dist" / filename).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ("<!doctype html><meta charset=utf-8><title>dutch-exercises</title>"
                "<p>This view has not been built. Run <code>npm run build</code> in <code>ui/</code>.</p>")


def _store():
    from .server import store  # lazy: server imports this module before it is fully initialised

    return store()


def _level(value: str) -> str:
    return (parse_level(value) or value.strip()) if value else ""


def _result(text: str, structured: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=structured)


def _ui_note(ctx: Context, view: str) -> str:
    if client_supports_apps(ctx):
        return f"Shown to the learner in the {view} view; don't repeat it in full.\n\n"
    return ""


# --------------------------------------------------------------------------------------------- show_exercises


def _cards_text(results: list[dict]) -> str:
    if not results:
        return "No exercises found."
    lines = []
    for i, r in enumerate(results, 1):
        lv = r.get("level") or {}
        level = "/".join(lv.get("stated") or []) or lv.get("estimated") or "?"
        lines.append(f"{i}. [{r.get('score', '?')}] {r.get('title', '')} ({r.get('source', '')}; level {level}, "
                     f"fit {lv.get('fit', '?')})\n   {r.get('url', '')}")
        if r.get("why"):
            lines.append("   why: " + "; ".join(r["why"][:4]))
        if r.get("warnings"):
            lines.append("   warnings: " + "; ".join(r["warnings"][:4]))
    return "\n".join(lines)


@apps.tool(resource_uri=RESULTS_URI, title="Show exercises",
           description="Show find_exercises results to the learner as cards (title, source, score, level fit, "
           "skills, formats, reasons, warnings, an Open link and 1-5 rating buttons). Either pass `results` from "
           "an earlier find_exercises call (no new search), or the same search parameters as find_exercises.")
async def show_exercises(
    ctx: Context,
    theme: str = Field("", description="As in find_exercises. Required unless `results` is given."),
    level: str = Field("", description="As in find_exercises. Required unless `results` is given."),
    skills: list[str] = Field(default_factory=list, description="As in find_exercises."),
    formats: list[str] = Field(default_factory=list, description="As in find_exercises."),
    variant: str = Field("any", description="As in find_exercises: 'any', 'nl' or 'be'."),
    free_only: bool = Field(True),
    vetted_only: bool = Field(False),
    include_user_generated: bool = Field(False),
    extra_terms: str = Field(""),
    max_results: int = Field(8, ge=1, le=20),
    results: list[ExerciseCard] | None = Field(None, max_length=20,
                                                description="The `results` list of an earlier find_exercises "
                                                "call; when given, no search is run."),
) -> CallToolResult:
    if results is not None:
        out = {"request": {"theme": theme, "level": _level(level)},
               "results": [r.model_dump(mode="json") for r in results]}
    else:
        if not theme or not level:
            raise ToolError("Give theme and level, or the `results` of an earlier find_exercises call.")
        from .server import find_exercises  # one search pipeline for both tools

        out = await find_exercises(theme=theme, level=level, skills=skills, formats=formats, variant=variant,
                                   free_only=free_only, vetted_only=vetted_only,
                                   include_user_generated=include_user_generated, extra_terms=extra_terms,
                                   max_results=max_results)
    structured = {"view": "exercise_results", "request": out.get("request", {}), "results": out.get("results", [])}
    for key in ("tip", "errors"):
        if out.get(key):
            structured[key] = out[key]
    text = _ui_note(ctx, "exercise results") + _cards_text(structured["results"])
    if structured.get("tip"):
        text += f"\n\nTip: {structured['tip']}"
    return _result(text, structured)


# ------------------------------------------------------------------------------------------- show_explanation


def _explanation_text(d: dict) -> str:
    out = [f"# {d['title']}" + (f" ({d['level']})" if d["level"] else "")]
    if d["summary"]:
        out.append(d["summary"])
    for s in d["sections"]:
        out += [f"## {s['heading']}", s["body"]]
    if d["table"]:
        t = d["table"]
        if t["caption"]:
            out.append(f"**{t['caption']}**")
        rows = [t["headers"], ["---"] * len(t["headers"]), *t["rows"]]
        out.append("\n".join("| " + " | ".join(r) + " |" for r in rows))
    if d["examples"]:
        out.append("## Voorbeelden")
        out.append("\n".join(f"- {e['nl']}" + (f" — {e['en']}" if e["en"] else "") + (f" ({e['note']})" if e["note"]
                             else "") for e in d["examples"]))
    if d["common_mistakes"]:
        out.append("## Veelgemaakte fouten")
        out.append("\n".join(f"- ✗ {m['wrong']} → ✓ {m['right']}" + (f" ({m['why']})" if m["why"] else "")
                             for m in d["common_mistakes"]))
    return "\n\n".join(out)


@apps.tool(resource_uri=EXPLANATION_URI, title="Show explanation",
           description="Show the learner a grammar or vocabulary explanation that you write: a short summary, "
           "sections, Dutch example sentences with translations, an optional table (e.g. a verb conjugation) and "
           "common mistakes. Content in Dutch; translations in the learner's language. Section bodies support "
           "**bold**, *italic*, `code` and '- ' bullet lines.")
def show_explanation(
    ctx: Context,
    title: str = Field(min_length=1, max_length=200, description="E.g. 'Het perfectum: hebben of zijn?'"),
    level: str = Field("", max_length=20, description="CEFR level, e.g. 'A2'."),
    summary: str = Field("", max_length=2000, description="The rule in one or two sentences."),
    sections: list[ExplanationSection] = Field(default_factory=list, max_length=12),
    examples: list[Example] = Field(default_factory=list, max_length=30),
    table: Table | None = Field(None, description="Optional table, e.g. headers ['', 'hebben', 'zijn']."),
    common_mistakes: list[Mistake] = Field(default_factory=list, max_length=15),
) -> CallToolResult:
    structured = {"view": "explanation", "title": title, "level": _level(level), "summary": summary,
                  "sections": [s.model_dump() for s in sections], "examples": [e.model_dump() for e in examples],
                  "table": table.model_dump() if table else None,
                  "common_mistakes": [m.model_dump() for m in common_mistakes]}
    return _result(_ui_note(ctx, "explanation") + _explanation_text(structured), structured)


# ------------------------------------------------------------------------------------------ show_exercise_set


def _item_text(n: int, item) -> str:
    if isinstance(item, MultipleChoice):
        opts = "  ".join(f"{chr(97 + i)}) {o}" for i, o in enumerate(item.options))
        return f"{n}. {item.prompt}\n   {opts}"
    if isinstance(item, GapFill):
        return f"{n}. {item.text}" + (f" {item.hint}" if item.hint else "")
    if isinstance(item, WordOrder):
        shuffled = sorted(item.words, key=lambda w: (len(w), w.casefold()))
        return f"{n}. {item.prompt + ' — ' if item.prompt else ''}Zet in de goede volgorde: " + " / ".join(shuffled)
    if isinstance(item, Matching):
        rights = sorted((p.right for p in item.pairs), key=str.casefold)
        return (f"{n}. {item.prompt or 'Verbind'}: " + ", ".join(p.left for p in item.pairs)
                + "  ↔  " + ", ".join(rights))
    if isinstance(item, TrueFalse):
        return f"{n}. Waar of niet waar? {item.statement}"
    raise TypeError(type(item))


@apps.tool(resource_uri=PLAYER_URI, title="Show exercise set",
           description="Give the learner interactive exercises that you write (or take from a source), with "
           "answer keys. Item types: 'mc' (prompt, options, answer index), 'gap' (text with ___ per gap, answers: "
           "accepted answers per gap), 'order' (words in the correct order; shuffled for the learner), 'match' "
           "(pairs of left/right), 'truefalse' (statement, answer). Add a short `explanation` per item for "
           "feedback. The view checks the answers, shows feedback per item and reports the score back to you.")
def show_exercise_set(
    ctx: Context,
    title: str = Field(min_length=1, max_length=200),
    items: list[Item] = Field(min_length=1, max_length=40),
    level: str = Field("", max_length=20),
    theme: str = Field("", max_length=120),
    instructions: str = Field("", max_length=2000, description="Shown above the items, in Dutch."),
) -> CallToolResult:
    ex = ExerciseSet(title=title, level=_level(level), theme=theme, instructions=instructions, items=items)
    set_id = secrets.token_hex(6)
    data = ex.model_dump()
    _store().put_exercise_set(set_id, ex.title, ex.level, ex.theme, data)
    structured = {"view": "exercise_set", "set_id": set_id, **data}

    lines = [f"# {ex.title}" + (f" ({ex.level})" if ex.level else "")]
    if ex.instructions:
        lines.append(ex.instructions)
    lines += [_item_text(i, it) for i, it in enumerate(ex.items, 1)]
    if client_supports_apps(ctx):
        text = (f"Shown to the learner in the exercise player (set_id {set_id}). The view checks the answers and "
                "will report the score to you; don't reveal the answers.\n\n" + "\n".join(lines))
    else:
        key = "\n".join(f"{i}. {answer_key(it)}" for i, it in enumerate(ex.items, 1))
        text = ("Present these exercises to the learner, then check their answers against the key (keep the key "
                f"hidden until they have answered).\n\n" + "\n\n".join(lines) + f"\n\nAnswer key:\n{key}")
    return _result(text, structured)


# --------------------------------------------------------------------------------------------- record_attempt


def _attempt_summary(ex: dict | None, results: list[ItemResult]) -> str:
    right = sum(r.correct for r in results)
    head = f"{right}/{len(results)} correct"
    if ex:
        head += f" on '{ex['title']}'" + (f" ({ex['level']})" if ex.get("level") else "")
    wrong = [r for r in results if not r.correct]
    if not wrong:
        return head + ". No errors."
    by_id = {it["id"]: it for it in (ex or {}).get("items", [])}
    parts = []
    for r in wrong[:10]:
        it = by_id.get(r.item_id, {})
        prompt = it.get("prompt") or it.get("text") or it.get("statement") or ""
        what = f"{r.item_id} ({r.type}" + (f": {prompt[:80]}" if prompt else "") + ")"
        parts.append(f"{what} answered {r.given or '(blank)'!r}, expected {r.expected!r}")
    return head + ". Errors: " + "; ".join(parts) + ("; …" if len(wrong) > 10 else "")


@apps.tool(resource_uri=PLAYER_URI, visibility=["app"], title="Record attempt",
           description="Called by the exercise player: store the learner's per-item results for an exercise set "
           "and return a short summary.")
def record_attempt(
    set_id: str = Field(min_length=1, max_length=40),
    results: list[ItemResult] = Field(min_length=1, max_length=40),
) -> CallToolResult:
    s = _store()
    ex = s.get_exercise_set(set_id)
    s.record_attempt(set_id, [r.model_dump() for r in results])
    right = sum(r.correct for r in results)
    summary = _attempt_summary(ex, results)
    return _result(summary, {"ok": True, "set_id": set_id, "correct": right, "total": len(results),
                             "summary": summary})


# ------------------------------------------------------------------------------------------- plain tools


def list_attempts(limit: int = Field(20, ge=1, le=200)) -> dict:
    """Recent exercise-player attempts with score, title, level, theme and the ids of wrong items."""
    return {"attempts": _store().attempts(limit)}


def register(mcp: MCPServer) -> None:
    """Add the non-UI companion tools to `mcp` (the UI tools come in through `extensions=[apps]`)."""
    mcp.add_tool(list_attempts, description="Show the learner's recent scores in the exercise player (from "
                 "show_exercise_set): correct/total, title, level, theme and which items were wrong.")


for _uri, _file in VIEWS.items():
    apps.add_html_resource(_uri, _html(_file), name=_file.removesuffix(".html"),
                           title={"results.html": "Exercise results", "explanation.html": "Explanation",
                                  "player.html": "Exercise player"}[_file])
