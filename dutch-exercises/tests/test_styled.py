"""render_styled: standalone HTML pages in the editorial and concertje styles. Offline."""

import pytest
from mcp import Client

from dutch_exercises import server
from dutch_exercises.styled import inline, markdown

EXPLANATION = {
    "title": "Het perfectum: hebben of zijn?", "level": "a2",
    "summary": "De voltooide tijd maak je met **hebben** of **zijn**.",
    "sections": [{"heading": "De regel", "body": "Meestal *hebben*.\n\n- gaan\n- komen"}],
    "table": {"caption": "Hebben of zijn", "headers": ["", "hebben", "zijn"], "rows": [["ik", "heb", "ben"]]},
    "examples": [{"nl": "Ik **ben** gegaan.", "en": "I went."}],
    "common_mistakes": [{"wrong": "Ik heb gegaan.", "right": "Ik ben gegaan.", "why": "richting"}],
}
EXERCISE_SET = {
    "title": "Perfectum", "level": "A2", "theme": "voltooide tijd",
    "items": [
        {"type": "mc", "prompt": "Ik ___ gegaan.", "options": ["heb", "ben"], "answer": 1, "explanation": "zijn"},
        {"type": "gap", "text": "Wij ___ tv ___.", "answers": ["hebben", ["gekeken"]]},
        {"type": "order", "words": ["Ik", "heb", "gewerkt"]},
        {"type": "match", "pairs": [{"left": "lopen", "right": "gelopen"}, {"left": "eten", "right": "gegeten"},
                                    {"left": "zien", "right": "gezien"}]},
        {"type": "truefalse", "statement": "Blijven gebruikt hebben.", "answer": False},
    ],
}
RESULTS = [
    {"score": 86, "title": "NT2 - A2 - Grammatica - Voltooide tijd - Oefening 1",
     "url": "https://proefa.nt2taalmenu.nl/a2-grammatica-voltooide-tijd-1/", "source": "NT2 TaalMenu",
     "level": {"stated": ["A2"], "estimated": None, "fit": "exact"}, "skills": ["grammar"], "formats": ["interactive"],
     "why": ["curated source (quality 5/5)", "states level A2"], "warnings": []},
    {"score": 38, "title": "Werkblad voltooide tijd (PDF)", "url": "https://www.klascement.net/downloads/12345/",
     "source": "KlasCement", "level": {"stated": ["B1"], "estimated": "B1", "fit": "close"},
     "skills": ["grammar", "writing"], "formats": ["worksheet", "pdf"], "why": ["theme in snippet: voltooide tijd"],
     "warnings": ["not fetched: scored from search snippet only", "level B1 is above A2"]},
]


async def _render(**args):
    async with Client(server.mcp) as c:
        return await c.call_tool("render_styled", args)


@pytest.mark.parametrize("style", ["editorial", "concertje"])
@pytest.mark.parametrize("content", [{"explanation": EXPLANATION}, {"exercise_set": EXERCISE_SET},
                                     {"results": RESULTS, "theme": "voltooide tijd", "level": "a2"}])
async def test_renders_standalone_page(style, content):
    r = await _render(style=style, **content)
    assert not r.is_error
    page = r.content[0].text
    assert page.startswith("<!doctype html>") and page.endswith("</html>")
    assert f'class="style-{style}"' in page
    assert "<script" not in page
    assert r.structured_content["style"] == style
    assert r.structured_content["content"] == next(iter(content))


async def test_editorial_is_default_and_square():
    page = (await _render(explanation=EXPLANATION)).content[0].text
    assert 'class="style-editorial"' in page
    assert "Libre+Caslon" in page and "--radius:0" in page
    assert '<h1 class="headline">Het perfectum: hebben of zijn?</h1>' in page
    assert "Uitleg · A2" in page  # level normalised
    assert "<strong>hebben</strong>" in page and "<li>gaan</li>" in page
    assert '<th scope="row">ik</th>' in page


async def test_exercise_set_worksheet_and_key():
    page = (await _render(exercise_set=EXERCISE_SET)).content[0].text
    assert page.count('<li class="item">') == 5
    assert "___" not in page  # gaps are drawn as write-in lines
    assert "Antwoorden" in page and "hebben | gekeken" in page
    # The key letters match the shuffled right-hand column of the matching item.
    right = page.split('<ol class="match-right">')[1].split("</ol>")[0]
    order = sorted(("gelopen", "gegeten", "gezien"), key=right.index)
    assert f"1{chr(97 + order.index('gelopen'))} (lopen = gelopen)" in page
    assert (await _render(exercise_set=EXERCISE_SET)).content[0].text == page  # deterministic shuffle
    no_key = (await _render(exercise_set=EXERCISE_SET, include_answers=False)).content[0].text
    assert "Antwoorden" not in no_key


async def test_agent_text_is_escaped():
    evil = {**EXPLANATION, "title": "<script>alert(1)</script>", "summary": '**<img src=x onerror="a()">**',
            "examples": [{"nl": '"><b>x</b>'}]}
    page = (await _render(explanation=evil)).content[0].text
    assert "<script>" not in page and "<img" not in page and "<b>x</b>" not in page
    assert "&lt;script&gt;" in page


async def test_results_links_are_http_only():
    bad = [{**RESULTS[0], "url": "javascript:alert(1)"}]
    assert (await _render(results=bad)).is_error
    page = (await _render(results=RESULTS[:1])).content[0].text
    assert 'href="https://proefa.nt2taalmenu.nl/' in page and 'rel="noopener noreferrer"' in page


@pytest.mark.parametrize("args", [{}, {"explanation": EXPLANATION, "results": RESULTS}, {"results": RESULTS,
                                                                                         "style": "neon"}])
async def test_needs_exactly_one_content_and_a_known_style(args):
    assert (await _render(**args)).is_error


def test_markdown_subset():
    assert inline("a **b** *c* `d` _e_ snake_case") == \
        "a <strong>b</strong> <em>c</em> <code>d</code> <em>e</em> snake_case"
    assert markdown("one\ntwo\n\n- x\n- y\nthree") == "<p>one<br>two</p><ul><li>x</li><li>y</li></ul><p>three</p>"
