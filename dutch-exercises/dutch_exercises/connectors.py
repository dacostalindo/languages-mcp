"""Source connectors: structured APIs for curated sites whose pages can't be scraped.

A connector returns (Hit, Analysis) pairs that skip the fetch step: the analysis is built from the
site's own metadata, which is better than anything we could read from a JavaScript-only page.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx

from .analyze import Analysis
from .search import UA, Hit
from .themes import theme_hits

log = logging.getLogger(__name__)

# --- NedBox (nedbox.be) -------------------------------------------------------------------
# Public JSON API used by their Angular app. NedBox's own "niveau" page: one star (EASY) is roughly
# A1, two stars (MEDIUM) A2, three stars (HARD) B1 or higher.

NEDBOX_API = "https://nedbox.be/api/Search/exercises"
NEDBOX_LEVELS = {"EASY": ["A1"], "MEDIUM": ["A2"], "HARD": ["B1"]}
NEDBOX_DIFFICULTY = {"A0": "EASY", "A1": "EASY", "A2": "MEDIUM", "B1": "HARD", "B2": "HARD", "C1": "HARD"}
NEDBOX_SKILLS = {"READING": "reading", "LISTENING": "listening", "SPEAKING": "speaking", "WRITING": "writing",
                 "VOCABULARY": "vocabulary", "GRAMMAR": "grammar"}
NEDBOX_THEME_LABELS = {
    "WERK": "werk", "KINDEREN": "kinderen", "CONSUMENT": "consument", "VRIJE_TIJD": "vrije tijd",
    "SOCIAAL_CONTACT": "sociaal contact", "LEVEN_IN_BELGIE": "leven in België", "GEZONDHEID": "gezondheid",
    "DE_WERELD": "de wereld", "ECHT_GEBEURD": "echt gebeurd", "NIEUW_LEVEN": "nieuw leven", "ALFA": "alfa",
}
# Our theme keys -> NedBox's theme filter.
NEDBOX_THEMES = {
    "werk": "WERK", "gezondheid": "GEZONDHEID", "boodschappen": "CONSUMENT", "kleding": "CONSUMENT",
    "vrije_tijd": "VRIJE_TIJD", "familie": "KINDEREN", "onderwijs": "KINDEREN", "kennismaken": "SOCIAAL_CONTACT",
    "communicatie": "SOCIAAL_CONTACT", "gevoelens": "SOCIAAL_CONTACT", "instanties": "LEVEN_IN_BELGIE",
    "maatschappij": "LEVEN_IN_BELGIE", "feesten": "LEVEN_IN_BELGIE", "natuur": "DE_WERELD", "wonen": "NIEUW_LEVEN",
}


def nedbox_analysis(item: dict, level: str) -> tuple[Hit, Analysis] | None:
    """Turn one NedBox search result into a pre-filled analysis, or None if it has nothing at `level`."""
    want = NEDBOX_DIFFICULTY.get(level)
    difficulties = set(item.get("difficulties") or [])
    if want and want not in difficulties:
        return None
    url = f"https://nedbox.be/exercise/{item['id']}"
    levels = sorted({lv for d in difficulties for lv in NEDBOX_LEVELS.get(d, [])})
    skills = list(dict.fromkeys(NEDBOX_SKILLS[s] for s in item.get("skills") or [] if s in NEDBOX_SKILLS))
    themes = " ".join(NEDBOX_THEME_LABELS.get(t, t.lower()) for t in item.get("themes") or [])
    name, desc = item.get("name", "").strip(), (item.get("description") or "").strip()
    media = item.get("media", "")
    formats = ["interactive"] + (["video"] if media == "VIDEO" else ["reading_text"] if media == "ARTICLE" else [])
    n = len(item.get("difficulties") or [])
    text = f"{name}. {desc}. Thema: {themes}."
    a = Analysis(
        url=url, final_url=url, ok=True, content_type="application/json", title=name, description=desc,
        headings=[name], language="nl", dutch_ratio=1.0, word_count=max(60, len(text.split())),
        stated_levels=[lv for lv in levels if lv == level] + [lv for lv in levels if lv != level],
        skills=skills, formats=formats, interactive_inputs=n, exercise_words=min(6, n), has_answer_key=True,
        excerpt=f"{desc} ({n} oefeningen: {', '.join(sorted(difficulties)).lower()}; {media.lower()})", text=text,
    )
    return Hit(url, name, desc, "nedbox-api"), a


async def nedbox(client: httpx.AsyncClient, req, terms: list[str], size: int = 12) -> list[tuple[Hit, Analysis]]:
    """Search by the mapped theme filter and by free-text term, keeping items that have the requested level."""
    queries = [{"Term": term} for term in terms[:2]]
    if req.theme.get("kind") == "grammar":
        queries = [{"Term": term, "Skill": "GRAMMAR"} for term in terms[:2]]
    elif NEDBOX_THEMES.get(req.theme.get("key") or ""):
        queries.append({"Theme": NEDBOX_THEMES[req.theme["key"]]})
    out: dict[str, tuple[Hit, Analysis]] = {}
    for params in queries:
        broad = "Term" not in params
        try:
            r = await client.get(NEDBOX_API, params={**params, "From": 0, "Size": size},
                                 headers={"Accept": "application/json", "User-Agent": UA})
            r.raise_for_status()
            items = r.json().get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("NedBox search failed: %s", exc)
            continue
        for item in items:
            pair = nedbox_analysis(item, req.level)
            if not pair or pair[0].url in out:
                continue
            # A theme category is broad (GEZONDHEID also holds cooking videos): keep those items only
            # when their own title or description is on topic.
            if broad and not theme_hits(req.theme["keywords"], f"{pair[1].title} {pair[1].description}"):
                continue
            if not broad:
                # NedBox matched the term somewhere in the item's content. For topics that's a fair theme
                # signal; for grammar it's often a passing word in a video, and we can't open the
                # exercises (login-only API) to check, so it's noted but not counted.
                if req.theme.get("kind") == "grammar":
                    pair[1].excerpt += f" NedBox found '{params['Term']}' in this item (unverified)."
                else:
                    pair[1].text += f" Inhoud: {params['Term']}."
            out[pair[0].url] = pair
    return list(out.values())


Connector = Callable[..., Awaitable[list[tuple[Hit, Analysis]]]]
CONNECTORS: dict[str, Connector] = {"nedbox": nedbox}
