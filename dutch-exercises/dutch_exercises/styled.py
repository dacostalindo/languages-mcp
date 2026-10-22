"""Render server content as a standalone, styled HTML page (the `render_styled` tool).

Three kinds of content can be rendered: an explanation, an exercise set (as a printable worksheet with an optional
answer key) and `find_exercises` results (as a reading list). Two styles share the same markup:

  editorial   New Yorker-inspired: Caslon display headlines, an italic deck, a drop cap, small-caps labels,
              hairline and thick-thin rules and an end mark, set in a modern layout with square edges throughout.
  concertje   The Concertje look from the concert digest emails (dacostalindo/concerts): near-black canvas,
              Redaction display, heavy Inter, uppercase tracked labels and pill chips.

The output is one HTML document with inline CSS and no scripts. Fonts come from a font CDN, with system serif and
sans fallbacks when it is blocked. The agent writes the content, so every string is HTML-escaped; the markdown
subset (**bold**, *italic*, `code`, "- " bullets, blank-line paragraphs) is parsed into escaped tags here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import re
from html import escape
from typing import Literal

from .content import (
    GAP_RE,
    ExerciseCard,
    ExerciseSet,
    Explanation,
    GapFill,
    Matching,
    MultipleChoice,
    TrueFalse,
    WordOrder,
    answer_key,
)

Style = Literal["editorial", "concertje"]
STYLES: tuple[str, ...] = ("editorial", "concertje")

_MONTHS = ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december")

_ITEM_LABELS = {"mc": "Meerkeuze", "gap": "Invullen", "order": "Zinsbouw", "match": "Verbinden",
                "truefalse": "Waar of niet waar"}

_FIT = {"exact": "Juist niveau", "close": "Bijna", "off": "Ander niveau", "estimated": "Geschat niveau",
        "estimated_close": "Geschat, bijna", "estimated_off": "Geschat, ander niveau", "unknown": "Niveau onbekend"}


def _e(text: object) -> str:
    return escape(str(text), quote=True)


# ------------------------------------------------------------------------------------------------- markdown

_INLINE_RE = re.compile(r"\*\*([^*\n]+)\*\*|`([^`\n]+)`|\*([^*\n]+)\*|(?<![^\W_])_([^_\n]+)_(?![^\W_])")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")


def inline(text: str) -> str:
    """Inline markdown subset (**bold**, *italic* / _italic_, `code`) as escaped HTML."""
    out, last = [], 0
    for m in _INLINE_RE.finditer(text):
        out.append(_e(text[last:m.start()]))
        if m[1] is not None:
            out.append(f"<strong>{_e(m[1])}</strong>")
        elif m[2] is not None:
            out.append(f"<code>{_e(m[2])}</code>")
        else:
            out.append(f"<em>{_e(m[3] if m[3] is not None else m[4])}</em>")
        last = m.end()
    out.append(_e(text[last:]))
    return "".join(out)


def markdown(text: str) -> str:
    """Block markdown subset: blank-line separated paragraphs and "- " bullet lists, as escaped HTML."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        para: list[str] = []
        bullets: list[str] = []

        def flush() -> None:
            if para:
                out.append("<p>" + "<br>".join(para) + "</p>")
                para.clear()
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets.clear()

        for line in (ln.rstrip() for ln in block.split("\n")):
            if not line.strip():
                continue
            if _BULLET_RE.match(line):
                if para:
                    flush()
                bullets.append(inline(_BULLET_RE.sub("", line)))
            else:
                if bullets:
                    flush()
                para.append(inline(line))
        flush()
    return "".join(out)


# --------------------------------------------------------------------------------------------------- pieces


def _rng(*parts: object) -> random.Random:
    """A seeded RNG so the same content always renders the same shuffle."""
    seed = hashlib.sha256(json.dumps(parts, default=str, ensure_ascii=False).encode()).hexdigest()
    return random.Random(seed)


def _shuffled(values: list[str], rng: random.Random) -> list[str]:
    """Shuffle, avoiding the original order when there is another one."""
    out = values[:]
    for _ in range(8):
        rng.shuffle(out)
        if out != values or len(set(values)) < 2:
            break
    return out


def _today() -> str:
    d = dt.date.today()
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _section(heading: str, body: str, cls: str = "") -> str:
    return f'<section class="section {cls}"><h2 class="section-head">{_e(heading)}</h2>{body}</section>'


def _table(t) -> str:
    row_headers = t.headers[0].strip() == ""
    head = "".join(f'<th scope="col">{_e(c)}</th>' for c in t.headers)
    rows = []
    for row in t.rows:
        cells = [f'<th scope="row">{_e(c)}</th>' if i == 0 and row_headers else f"<td>{inline(c)}</td>"
                 for i, c in enumerate(row)]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    caption = f"<figcaption>{_e(t.caption)}</figcaption>" if t.caption else ""
    return (f'<figure class="table"><div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>{caption}</figure>')


# -------------------------------------------------------------------------------------------- explanation


def _explanation_body(d: Explanation) -> str:
    parts = [_section(s.heading, markdown(s.body)) for s in d.sections]
    if d.table:
        parts.append(_table(d.table))
    if d.examples:
        items = "".join(
            f'<li><p class="nl">{inline(x.nl)}</p>'
            + (f'<p class="en">{_e(x.en)}</p>' if x.en else "")
            + (f'<p class="note">{_e(x.note)}</p>' if x.note else "") + "</li>"
            for x in d.examples)
        parts.append(_section("Voorbeelden", f'<ol class="examples">{items}</ol>'))
    if d.common_mistakes:
        items = "".join(
            f'<li><p><span class="mark bad" aria-label="Fout">✗</span><span class="wrong">{_e(m.wrong)}</span></p>'
            f'<p><span class="mark good" aria-label="Goed">✓</span><span class="right">{_e(m.right)}</span></p>'
            + (f'<p class="why">{_e(m.why)}</p>' if m.why else "") + "</li>"
            for m in d.common_mistakes)
        parts.append(f'<aside class="box"><h2 class="box-head">Veelgemaakte fouten</h2>'
                     f'<ul class="mistakes">{items}</ul></aside>')
    return "".join(parts)


# ------------------------------------------------------------------------------------------- exercise set


def _blank(n: int | None = None) -> str:
    label = f"invullen {n}" if n else "invullen"
    return f'<span class="blank"><span class="visually-hidden">{label}</span></span>'


def _with_blanks(text: str) -> str:
    """Escaped text with each ___ drawn as a write-in line."""
    pieces = GAP_RE.split(text)
    numbered = len(pieces) > 2
    return _e(pieces[0]) + "".join(_blank(i if numbered else None) + _e(p) for i, p in enumerate(pieces[1:], 1))


def _item_html(item, rng: random.Random) -> str:
    if isinstance(item, MultipleChoice):
        opts = "".join(f'<li><span class="box-tick" aria-hidden="true"></span>'
                       f'<span class="letter">{chr(97 + i)}</span>{_e(o)}</li>' for i, o in enumerate(item.options))
        return f'<p class="prompt">{_with_blanks(item.prompt)}</p><ul class="options">{opts}</ul>'
    if isinstance(item, GapFill):
        text = _with_blanks(item.text)
        hint = f' <span class="hint">{_e(item.hint)}</span>' if item.hint else ""
        return f'<p class="prompt gap-text">{text}{hint}</p>'
    if isinstance(item, WordOrder):
        tiles = "".join(f'<li class="tile">{_e(w)}</li>' for w in _shuffled(item.words, rng))
        prompt = f'<p class="prompt">{_e(item.prompt)}</p>' if item.prompt else ""
        return f'{prompt}<ul class="tiles">{tiles}</ul><p class="write-line" aria-hidden="true"></p>'
    if isinstance(item, Matching):
        rights = _shuffled([p.right for p in item.pairs], rng)
        left = "".join(f"<li><span class=\"letter\">{i}</span>{_e(p.left)}"
                       f'<span class="answer-slot" aria-hidden="true"></span></li>'
                       for i, p in enumerate(item.pairs, 1))
        right = "".join(f'<li><span class="letter">{chr(97 + i)}</span>{_e(r)}</li>' for i, r in enumerate(rights))
        prompt = f'<p class="prompt">{_e(item.prompt)}</p>' if item.prompt else ""
        return f'{prompt}<div class="match"><ol class="match-left">{left}</ol><ol class="match-right">{right}</ol></div>'
    if isinstance(item, TrueFalse):
        tick = '<span class="box-tick" aria-hidden="true"></span>'
        return (f'<p class="prompt">{_e(item.statement)}</p>'
                f'<ul class="options inline"><li>{tick}Waar</li><li>{tick}Niet waar</li></ul>')
    raise TypeError(type(item))


def _matching_key(item: Matching, rng: random.Random) -> str:
    rights = _shuffled([p.right for p in item.pairs], rng)
    letter = {r: chr(97 + i) for i, r in enumerate(rights)}
    return ", ".join(f"{i}{letter[p.right]} ({_e(p.left)} = {_e(p.right)})" for i, p in enumerate(item.pairs, 1))


def _exercise_body(ex: ExerciseSet, include_answers: bool) -> str:
    # One RNG per item, seeded by the item, so the worksheet and the key agree on the shuffle.
    def rng(i: int, item) -> random.Random:
        return _rng(ex.title, i, item.model_dump())

    items = "".join(
        f'<li class="item"><span class="num" aria-hidden="true">{i}</span><div class="item-body">'
        f'<p class="item-type">{_ITEM_LABELS[item.type]}</p>{_item_html(item, rng(i, item))}</div></li>'
        for i, item in enumerate(ex.items, 1))
    out = f'<ol class="items">{items}</ol>'
    if include_answers:
        rows = []
        for i, item in enumerate(ex.items, 1):
            key = _matching_key(item, rng(i, item)) if isinstance(item, Matching) else _e(answer_key(item))
            why = f'<span class="why">{inline(item.explanation)}</span>' if item.explanation else ""
            rows.append(f"<li><strong>{key}</strong>{why}</li>")
        out += f'<aside class="box key"><h2 class="box-head">Antwoorden</h2><ol>{"".join(rows)}</ol></aside>'
    return out


# ------------------------------------------------------------------------------------------------ results


def _results_body(results: list[ExerciseCard]) -> str:
    if not results:
        return '<p class="empty">Geen oefeningen gevonden.</p>'
    rows = []
    for r in results:
        lv = r.level or {}
        level = "/".join(lv.get("stated") or []) or lv.get("estimated") or ""
        meta = [r.source, level, _FIT.get(lv.get("fit") or "unknown", str(lv.get("fit")))]
        meta_html = '<span class="sep" aria-hidden="true">·</span>'.join(_e(m) for m in meta if m)
        tags = "".join(f'<li class="tag">{_e(t)}</li>' for t in [*r.skills, *r.formats])
        score = round(float(r.score))
        why = f'<p class="why">{_e("; ".join(r.why[:4]))}</p>' if r.why else ""
        warn = "".join(f'<p class="warn">{_e(w)}</p>' for w in r.warnings[:4])
        rows.append(
            f'<li class="result"><span class="score{" low" if score < 50 else ""}" aria-label="score {score}">'
            f'{score}</span><div><p class="meta">{meta_html}</p>'
            f'<h2 class="result-title"><a href="{_e(r.url)}" target="_blank" rel="noopener noreferrer">'
            f'{_e(r.title)}</a></h2>'
            + (f'<ul class="tags">{tags}</ul>' if tags else "") + why + warn + "</div></li>")
    return f'<ol class="results">{"".join(rows)}</ol>'


# --------------------------------------------------------------------------------------------------- page

_FONTS = {
    "editorial": ["https://fonts.googleapis.com/css2?family=Libre+Caslon+Display&family=Libre+Caslon+Text:ital,"
                  "wght@0,400;0,700;1,400&family=Inter+Tight:wght@500;600;700;800&display=swap"],
    "concertje": ["https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800&display=swap",
                  "https://cdn.jsdelivr.net/npm/@fontsource/redaction@5/index.css"],
}

_BASE_CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:var(--body-size)/1.6 var(--serif);
  font-feature-settings:"kern","liga","onum";-webkit-font-smoothing:antialiased}
.page{max-width:720px;margin:0 auto;padding:40px 28px 64px}
a{color:inherit;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
a:hover{color:var(--accent)}
p{margin:0 0 .9em}p:last-child{margin-bottom:0}
ul,ol{margin:0;padding:0}
strong{font-weight:700}
code{font:600 .86em var(--sans);background:var(--box);padding:1px 5px;border-radius:var(--radius-sm)}
.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.label,.masthead,.kicker,.byline,.section-head,.box-head,.item-type,.meta,.tag,figcaption,thead th,.colophon{
  font-family:var(--sans);text-transform:uppercase;letter-spacing:.14em;font-size:11px;line-height:16px;font-weight:700}

.masthead{display:flex;justify-content:space-between;gap:16px;align-items:baseline;color:var(--ink);
  padding:10px 0 8px;border-top:var(--masthead-rule);border-bottom:1px solid var(--rule-strong)}
.masthead .issue{color:var(--muted);font-weight:600}
.kicker{margin:44px 0 14px;color:var(--accent)}
.headline{margin:0;font:var(--headline-weight) var(--headline-size)/1.02 var(--display);letter-spacing:-.015em;
  color:var(--ink);text-wrap:balance}
.deck{margin:18px 0 0;font:italic 21px/1.45 var(--serif);color:var(--soft);text-wrap:pretty}
.deck p{margin:0 0 .5em}
.byline{margin:26px 0 0;padding:10px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
  color:var(--muted);display:flex;flex-wrap:wrap;gap:6px 18px}
.byline b{color:var(--ink);font-weight:700}

.body{margin-top:36px}
.body::after{content:"";display:block;width:10px;height:10px;margin-top:28px;background:var(--ink);
  border-radius:var(--radius-sm)}
.section{margin:0 0 34px}
.section-head{margin:0 0 12px;color:var(--ink);display:flex;align-items:center;gap:10px}
.section-head::before{content:"";flex:none;width:8px;height:8px;background:var(--accent);border-radius:var(--radius-sm)}
.section p,.section li{text-wrap:pretty}
.section ul{padding-left:1.1em}
.section ul li{margin:0 0 .35em}
.section ul li::marker{color:var(--accent)}
.body>.section:first-child>p:first-of-type::first-letter{float:left;font:400 4.1em/.8 var(--display);
  margin:.06em .1em 0 0;color:var(--ink)}

.table{margin:0 0 34px}
.table-wrap{overflow-x:auto;border-top:2px solid var(--ink);border-bottom:1px solid var(--ink)}
table{width:100%;border-collapse:collapse;font:16px/1.4 var(--serif)}
thead th{text-align:left;padding:10px 14px 8px 0;color:var(--muted);border-bottom:1px solid var(--rule-strong)}
td,tbody th{text-align:left;padding:9px 14px 9px 0;border-bottom:1px solid var(--rule)}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
tbody th{font-style:italic;font-weight:400;color:var(--soft)}
td{font-weight:700}
figcaption{margin-top:8px;color:var(--muted);font-weight:600}

.examples{list-style:none;counter-reset:ex}
.examples li{counter-increment:ex;position:relative;padding:12px 0 12px 40px;border-top:1px solid var(--rule)}
.examples li:first-child{border-top:0;padding-top:4px}
.examples li::before{content:counter(ex);position:absolute;left:0;top:10px;font:400 22px/1 var(--display);
  color:var(--accent);font-feature-settings:"lnum"}
.examples li:first-child::before{top:2px}
.nl{margin:0;font-size:19px;line-height:1.4;color:var(--ink)}
.en{margin:4px 0 0;font:500 13px/1.45 var(--sans);color:var(--muted)}
.note{margin:4px 0 0;font-style:italic;font-size:15px;color:var(--soft)}

.box{margin:8px 0 34px;border:1px solid var(--ink);border-radius:var(--radius);background:var(--box-bg);
  overflow:hidden}
.box-head{margin:0;padding:9px 16px;background:var(--ink);color:var(--paper)}
.mistakes{list-style:none;padding:4px 16px}
.mistakes li{padding:12px 0;border-top:1px solid var(--rule)}
.mistakes li:first-child{border-top:0}
.mistakes p{margin:0}
.mark{display:inline-block;width:1.4em;font:700 14px var(--sans)}
.mark.bad{color:var(--bad)}.mark.good{color:var(--good)}
.wrong{text-decoration:line-through;text-decoration-thickness:1px;color:var(--muted)}
.right{font-weight:700}
.why{display:block;margin-top:4px;font:italic 15px/1.45 var(--serif);color:var(--soft)}

.items{list-style:none}
.item{display:grid;grid-template-columns:44px 1fr;gap:0 12px;padding:20px 0;border-top:1px solid var(--rule)}
.item:first-child{border-top:0;padding-top:0}
.num{font:400 34px/1 var(--display);color:var(--ink);font-feature-settings:"lnum"}
.item-type{margin:0 0 6px;color:var(--accent)}
.prompt{margin:0 0 10px;font-size:19px;line-height:1.45}
.gap-text{line-height:2}
.blank{display:inline-block;min-width:6.5em;border-bottom:1px solid var(--ink);margin:0 4px;
  vertical-align:-2px;height:1.1em}
.hint{font-style:italic;color:var(--muted)}
.options{list-style:none;display:grid;gap:6px}
.options.inline{display:flex;gap:24px}
.options li{display:flex;align-items:center;gap:10px}
.box-tick{flex:none;width:14px;height:14px;border:1.5px solid var(--ink);border-radius:var(--radius-sm)}
.letter{font:700 11px var(--sans);text-transform:uppercase;letter-spacing:.1em;color:var(--muted);min-width:1.2em}
.tiles{list-style:none;display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.tile{padding:5px 12px;border:1px solid var(--ink);border-radius:var(--radius);font:600 15px/1.3 var(--sans)}
.write-line{height:28px;border-bottom:1px solid var(--rule-strong);margin:0}
.match{display:grid;grid-template-columns:1fr 1fr;gap:6px 28px}
.match ol{list-style:none;display:grid;gap:8px;align-content:start}
.match li{display:flex;align-items:baseline;gap:8px}
.answer-slot{flex:none;margin-left:auto;width:2.2em;border-bottom:1px solid var(--ink);height:1em}
.key{margin-top:34px}
.key ol{padding:14px 16px 14px 40px;font-size:16px}
.key li{margin:0 0 8px}
.key li::marker{font:700 12px var(--sans);color:var(--muted)}
.key .why{font-size:14px}

.results{list-style:none}
.result{display:grid;grid-template-columns:64px 1fr;gap:0 16px;padding:22px 0;border-top:1px solid var(--rule)}
.result:first-child{border-top:0;padding-top:0}
.score{font:400 40px/1 var(--display);color:var(--accent);font-feature-settings:"lnum"}
.score.low{color:var(--muted)}
.meta{margin:2px 0 6px;color:var(--muted);font-weight:600}
.sep{margin:0 .5em;color:var(--rule-strong)}
.result-title{margin:0 0 10px;font:400 25px/1.2 var(--display);letter-spacing:-.005em}
.result-title a{text-decoration:none}
.result-title a:hover{text-decoration:underline}
.tags{list-style:none;display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.tag{padding:3px 8px;border:1px solid var(--rule-strong);border-radius:var(--radius);color:var(--soft);
  font-size:10px;letter-spacing:.12em}
.result .why{margin:0}
.warn{margin:6px 0 0;font:600 13px/1.4 var(--sans);color:var(--bad)}
.warn::before{content:"! ";font-weight:800}
.empty{font-style:italic;color:var(--muted)}

.colophon{margin-top:44px;padding-top:10px;border-top:var(--masthead-rule);color:var(--muted);font-weight:600;
  display:flex;justify-content:space-between;gap:16px}

@media (max-width:560px){
  .page{padding:24px 18px 48px}
  .deck{font-size:19px}
  .match{grid-template-columns:1fr}
  .result{grid-template-columns:48px 1fr}.score{font-size:32px}
}
@media print{
  body{background:#fff;color:#000}
  .page{max-width:none;padding:0}
  .key{break-before:page}
  .item,.result,.box{break-inside:avoid}
  a{text-decoration:none}
}
"""

_STYLE_CSS = {
    # New Yorker-inspired, but modern: Caslon type, warm paper, one red accent, square corners everywhere.
    "editorial": """
:root{color-scheme:light dark;
  --paper:#fbfaf6;--ink:#111111;--soft:#3a3a3a;--muted:#6f6c66;--rule:#e0ddd5;--rule-strong:#b9b5ac;
  --accent:#c8102e;--box:#efece4;--box-bg:transparent;--good:#1f6b3a;--bad:#c8102e;
  --display:"Libre Caslon Display","Big Caslon","Iowan Old Style",Baskerville,Georgia,serif;
  --serif:"Libre Caslon Text","Iowan Old Style",Baskerville,Georgia,"Times New Roman",serif;
  --sans:"Inter Tight","Helvetica Neue",Helvetica,Arial,sans-serif;
  --headline-size:60px;--headline-weight:400;--body-size:18px;
  --radius:0;--radius-sm:0;--masthead-rule:4px solid var(--ink)}
@media (prefers-color-scheme:dark){:root{
  --paper:#141413;--ink:#f3f0e8;--soft:#cfcbc2;--muted:#9a968d;--rule:#2c2b28;--rule-strong:#4a4843;
  --accent:#ff5a5f;--box:#22211f;--good:#5fd38d;--bad:#ff5a5f}}
.headline{font-feature-settings:"liga","dlig"}
@media (max-width:560px){:root{--headline-size:42px}}
""",
    # The Concertje look from the concert digest emails.
    "concertje": """
:root{color-scheme:dark light;
  --paper:#0a0a0a;--ink:#ffffff;--soft:#d4d4d4;--muted:#a1a1a1;--rule:#262626;--rule-strong:#404040;
  --accent:#fcbb00;--box:#171717;--box-bg:#171717;--good:#05df72;--bad:#ff6568;
  --display:"Redaction","Redaction 35",Georgia,"Times New Roman",serif;
  --serif:"Redaction 35","Redaction",Georgia,"Times New Roman",serif;
  --sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  --headline-size:46px;--headline-weight:400;--body-size:16px;
  --radius:999px;--radius-sm:999px;--masthead-rule:1px solid var(--rule)}
@media (prefers-color-scheme:light){:root{
  --paper:#ffffff;--ink:#0a0a0a;--soft:#262626;--muted:#525252;--rule:#e5e5e5;--rule-strong:#d4d4d4;
  --accent:#a16207;--box:#f5f5f5;--box-bg:#f5f5f5;--good:#047857;--bad:#c81e1e}}
body{font-family:var(--sans)}
.box{border-radius:0;border-color:var(--rule)}
.box-head{background:transparent;color:var(--muted);border-bottom:1px solid var(--rule)}
.prompt,.result-title{font-family:var(--sans);font-weight:800;font-size:18px;letter-spacing:-.01em}
.nl{font-family:var(--serif)}
table{font-family:var(--sans);font-size:15px}
.tag{border-color:var(--rule-strong);padding:4px 10px}
.tile{padding:6px 14px}
.body>.section:first-child>p:first-of-type::first-letter{float:none;font:inherit;margin:0;color:inherit}
@media (max-width:560px){:root{--headline-size:36px}}
""",
}


def render_page(*, style: Style, kicker: str, title: str, deck: str, byline: list[tuple[str, str]], body: str,
                lang: str = "nl") -> str:
    if style not in _STYLE_CSS:
        raise ValueError(f"unknown style {style!r}; choose one of {', '.join(STYLES)}")
    fonts = "".join(f'<link rel="stylesheet" href="{u}">' for u in _FONTS[style])
    by = "".join(f"<span>{_e(k)} <b>{_e(v)}</b></span>" for k, v in byline if v)
    return (
        f'<!doctype html><html lang="{_e(lang)}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f"{fonts}<style>{_BASE_CSS}{_STYLE_CSS[style]}</style></head>"
        f'<body class="style-{style}"><article class="page">'
        f'<header class="masthead"><span class="brand">Dutch Exercises</span>'
        f'<span class="issue">{_e(_today())}</span></header>'
        f'<p class="kicker">{_e(kicker)}</p><h1 class="headline">{_e(title)}</h1>'
        + (f'<div class="deck">{markdown(deck)}</div>' if deck else "")
        + (f'<div class="byline">{by}</div>' if by else "")
        + f'<div class="body">{body}</div>'
        '<footer class="colophon"><span>Dutch Exercises</span><span>NT2</span></footer>'
        "</article></body></html>")


def render_explanation(d: Explanation, style: Style = "editorial") -> str:
    return render_page(style=style, kicker="Uitleg" + (f" · {d.level}" if d.level else ""), title=d.title,
                       deck=d.summary, byline=[("Niveau", d.level)], body=_explanation_body(d))


def render_exercise_set(ex: ExerciseSet, style: Style = "editorial", include_answers: bool = True) -> str:
    return render_page(style=style, kicker="Oefeningen" + (f" · {ex.level}" if ex.level else ""), title=ex.title,
                       deck=ex.instructions,
                       byline=[("Niveau", ex.level), ("Thema", ex.theme), ("Opgaven", str(len(ex.items)))],
                       body=_exercise_body(ex, include_answers))


def render_results(results: list[ExerciseCard], style: Style = "editorial", title: str = "", theme: str = "",
                   level: str = "") -> str:
    deck = f"{len(results)} oefening{'en' if len(results) != 1 else ''}, gerangschikt op score." if results else ""
    return render_page(style=style, kicker="Leeslijst" + (f" · {level}" if level else ""),
                       title=title or (f"Oefeningen: {theme}" if theme else "Gevonden oefeningen"), deck=deck,
                       byline=[("Thema", theme), ("Niveau", level)], body=_results_body(results))
