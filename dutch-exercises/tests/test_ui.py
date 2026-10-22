"""MCP Apps UI tools: extension wiring, ui:// resources, text fallbacks, validation and attempt storage. Offline."""

import inspect
import json

import pytest
from mcp import Client
from mcp.client.extension import advertise

from dutch_exercises import server, ui_tools
from dutch_exercises.store import Store
from dutch_exercises.ui_models import ExerciseSet, normalize_answer

APPS = advertise("io.modelcontextprotocol/ui", {"mimeTypes": ["text/html;profile=mcp-app"]})
UI_TOOLS = {"show_exercises": ui_tools.RESULTS_URI, "show_explanation": ui_tools.EXPLANATION_URI,
            "show_exercise_set": ui_tools.PLAYER_URI, "record_attempt": ui_tools.PLAYER_URI}
EXISTING = {"find_exercises", "inspect_exercise", "rate_exercise", "list_sources", "list_themes", "list_ratings"}

EXERCISE_SET = {
    "title": "Perfectum", "level": "a2", "theme": "voltooide tijd",
    "items": [
        {"type": "mc", "prompt": "Ik ___ naar huis gegaan.", "options": ["heb", "ben"], "answer": 1},
        {"type": "gap", "text": "Wij ___ tv ___.", "answers": ["hebben", ["gekeken"]]},
        {"type": "order", "words": ["Ik", "heb", "gewerkt"]},
        {"type": "match", "pairs": [{"left": "lopen", "right": "gelopen"}, {"left": "eten", "right": "gegeten"}]},
        {"type": "truefalse", "statement": "Blijven gebruikt hebben.", "answer": False},
    ],
}
CARD = {"title": "Voltooide tijd 1", "url": "https://proefa.nt2taalmenu.nl/x/", "score": 80, "source": "NT2 TaalMenu",
        "level": {"stated": ["A2"], "estimated": None, "fit": "exact"}, "why": ["states level A2"], "warnings": []}


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_store", Store(tmp_path / "store.db"))


async def test_extension_advertised_and_tools_bound():
    async with Client(server.mcp) as c:
        assert "io.modelcontextprotocol/ui" in c.server_capabilities.extensions
        tools = {t.name: t for t in (await c.list_tools()).tools}
    for name, uri in UI_TOOLS.items():
        assert tools[name].meta["ui"]["resourceUri"] == uri
    assert tools["record_attempt"].meta["ui"]["visibility"] == ["app"]
    assert "visibility" not in tools["show_exercise_set"].meta["ui"]
    for name in EXISTING:  # existing tools are unchanged: no UI binding
        assert not (tools[name].meta or {}).get("ui")
    assert "list_attempts" in tools


async def test_resources_are_mcp_app_html():
    async with Client(server.mcp) as c:
        listed = {str(r.uri): r for r in (await c.list_resources()).resources}
        for uri in set(UI_TOOLS.values()):
            assert listed[uri].mime_type == "text/html;profile=mcp-app"
            content = (await c.read_resource(uri)).contents[0]
            assert content.mime_type == "text/html;profile=mcp-app"
            assert content.text.lstrip().lower().startswith("<!doctype html>")
            assert "<script" in content.text  # the built single-file view, not the "not built" placeholder


async def test_exercise_set_text_fallback_without_apps():
    async with Client(server.mcp) as c:
        r = await c.call_tool("show_exercise_set", EXERCISE_SET)
    assert not r.is_error
    sc = r.structured_content
    assert sc["view"] == "exercise_set" and sc["level"] == "A2" and sc["set_id"]
    assert [i["id"] for i in sc["items"]] == ["q1", "q2", "q3", "q4", "q5"]
    assert sc["items"][1]["answers"] == [["hebben"], ["gekeken"]]
    text = r.content[0].text
    assert "Answer key:" in text and "1. ben" in text and "3. Ik heb gewerkt" in text
    assert "Waar of niet waar? Blijven gebruikt hebben." in text


async def test_exercise_set_with_apps_hides_answer_key_in_text():
    async with Client(server.mcp, extensions=[APPS]) as c:
        r = await c.call_tool("show_exercise_set", EXERCISE_SET)
    assert "exercise player" in r.content[0].text and "Answer key" not in r.content[0].text


@pytest.mark.parametrize("bad", [
    {"type": "mc", "prompt": "x", "options": ["a", "b"], "answer": 2},
    {"type": "mc", "prompt": "x", "options": ["a", "A"], "answer": 0},
    {"type": "gap", "text": "geen gat", "answers": ["a"]},
    {"type": "gap", "text": "een ___ en ___", "answers": ["a"]},
    {"type": "order", "words": ["a", "b"], "alternatives": [["a", "c"]]},
    {"type": "match", "pairs": [{"left": "a", "right": "x"}, {"left": "a", "right": "y"}]},
    {"type": "essay", "prompt": "x"},
])
async def test_exercise_set_validation(bad):
    async with Client(server.mcp) as c:
        r = await c.call_tool("show_exercise_set", {"title": "t", "items": [bad]})
    assert r.is_error


async def test_record_attempt_and_list_attempts():
    async with Client(server.mcp, extensions=[APPS]) as c:
        set_id = (await c.call_tool("show_exercise_set", EXERCISE_SET)).structured_content["set_id"]
        r = await c.call_tool("record_attempt", {"set_id": set_id, "results": [
            {"item_id": "q1", "type": "mc", "correct": False, "given": "heb", "expected": "ben"},
            {"item_id": "q2", "type": "gap", "correct": True, "given": "hebben | gekeken", "expected": "hebben | gekeken"},
        ]})
        assert r.structured_content["correct"] == 1 and r.structured_content["total"] == 2
        summary = r.structured_content["summary"]
        assert summary.startswith("1/2 correct on 'Perfectum' (A2)")
        assert "q1 (mc: Ik ___ naar huis gegaan.) answered 'heb', expected 'ben'" in summary
        attempts = json.loads((await c.call_tool("list_attempts", {})).content[0].text)["attempts"]
    assert attempts[0] | {"at": 0} == {"set_id": set_id, "at": 0, "correct": 1, "total": 2, "title": "Perfectum",
                                       "level": "A2", "theme": "voltooide tijd", "wrong_items": ["q1"]}


async def test_explanation_fallback_is_markdown():
    args = {"title": "De of het?", "level": "A1", "summary": "Meestal **de**.",
            "table": {"headers": ["", "enkelvoud"], "rows": [["de", "de man"]]},
            "examples": [{"nl": "het huis", "en": "the house"}],
            "common_mistakes": [{"wrong": "de huis", "right": "het huis"}]}
    async with Client(server.mcp) as c:
        r = await c.call_tool("show_explanation", args)
        bad = await c.call_tool("show_explanation", {"title": "x", "table": {"headers": ["a", "b"], "rows": [["1"]]}})
    assert r.structured_content["view"] == "explanation"
    text = r.content[0].text
    assert "# De of het? (A1)" in text and "|  | enkelvoud |" in text and "- het huis — the house" in text
    assert "✗ de huis → ✓ het huis" in text
    assert bad.is_error


async def test_show_exercises_from_previous_results():
    async with Client(server.mcp) as c:
        r = await c.call_tool("show_exercises", {"results": [CARD], "theme": "perfectum", "level": "A2"})
        none = await c.call_tool("show_exercises", {})
        js = await c.call_tool("show_exercises", {"results": [CARD | {"url": "javascript:alert(1)"}]})
    assert r.structured_content["view"] == "exercise_results"
    assert r.structured_content["results"][0]["url"] == CARD["url"]
    assert "1. [80] Voltooide tijd 1" in r.content[0].text
    assert none.is_error and js.is_error


def test_show_exercises_mirrors_find_exercises_parameters():
    # show_exercises forwards its search parameters to find_exercises; keep the two signatures in step.
    find = set(inspect.signature(server.find_exercises).parameters)
    show = set(inspect.signature(ui_tools.show_exercises).parameters) - {"ctx", "results"}
    assert show == find


def test_normalize_answer():
    assert normalize_answer("  Ben. ") == "ben"
    assert normalize_answer("Hebben   gekeken!") == "hebben gekeken"
    assert ExerciseSet(title="t", items=[{"type": "truefalse", "statement": "s", "answer": True}]).items[0].id == "q1"
