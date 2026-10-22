"""Quality score (0-100) for a candidate exercise against a request, with human-readable reasons."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .analyze import Analysis
from .levels import distance, stated_levels
from .sources import Source
from .themes import theme_hits


EXAM_PAGE = re.compile(r"oefenexamen|voorbeeldexamen|oefentoets|oefenen|examens? oefenen|practice|takenbank|"
                       r"\.pdf\b|opgave|lezen|luisteren|schrijven|spreken", re.I)
OVERVIEW_PAGE = re.compile(r"materialen\s*(oefenen\.nl|overzicht)|materialenoverzicht|brochure|folder|jaarverslag|"
                           r"inschrijven|aanmelden|tarieven|veelgestelde vragen|\bfaq\b|over ons|contact", re.I)


@dataclass
class Request:
    level: str
    theme: dict
    skills: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    free_only: bool = True


@dataclass
class Scored:
    score: int
    level_fit: str
    reasons: list[str]
    warnings: list[str]
    levels: list[str]
    estimated_level: str | None


def score(req: Request, url: str, title: str, snippet: str, a: Analysis | None, src: Source | None,
          url_rating: tuple[float, int] | None = None, domain_rating: tuple[float, int] | None = None) -> Scored:
    pts = 0.0
    why: list[str] = []
    warn: list[str] = []
    verified = bool(a and a.ok)
    title = (a.title if verified and a.title else title) or ""

    # 1. Source reputation (0-25), nudged by the agent's own ratings.
    if src:
        pts += src.quality * 5
        why.append(f"{'curated' if not src.user_generated else 'user-made'} source {src.name} (quality {src.quality}/5)")
        if src.user_generated:
            warn.append("user-made content: check it for mistakes before using it")
    else:
        pts += 8
    if url_rating:
        pts += (url_rating[0] - 3) * 6
        why.append(f"you rated this {url_rating[0]:.1f}/5 ({url_rating[1]}x)")
    elif domain_rating and domain_rating[1] >= 2:
        pts += (domain_rating[0] - 3) * 3

    # 2. Level fit (-15..20).
    levels = list(a.stated_levels) if verified else []
    if not levels:
        levels = stated_levels(title, snippet, url)
    est = a.estimated["level"] if verified and a.estimated else None
    if levels:
        d = min(distance(req.level, lv) for lv in levels)
        if d == 0:
            broad = len(levels) > 3
            pts += 14 if broad else 20
            fit = "exact"
            why.append(f"stated level {'/'.join(levels[:3])}" + (" (page spans many levels)" if broad else ""))
        elif d == 1:
            pts += 8
            fit = "close"
            why.append(f"stated level {'/'.join(levels[:3])}, one step from {req.level}")
        else:
            pts -= 15
            fit = "off"
            warn.append(f"stated level {'/'.join(levels[:3])} doesn't match {req.level}")
    elif est:
        d = distance(req.level, est)
        pts += {0: 10, 1: 5}.get(d, -5)
        fit = {0: "estimated", 1: "estimated_close"}.get(d, "estimated_off")
        why.append(f"text reads like {est} (estimate)")
    else:
        fit = "unknown"
        if src and src.covers(req.level):
            pts += 4
        warn.append("level not stated on the page")

    # 3. Theme fit (0-20).
    kws = req.theme["keywords"]
    strong_text = " ".join([title, url.replace("-", " ").replace("_", " "), *(a.headings if verified else [])])
    strong = theme_hits(kws, strong_text)
    body = theme_hits(kws, (a.text if verified else snippet) or "")
    if strong:
        pts += min(12, 8 + 2 * len(strong))
        why.append(f"theme in title/headings: {', '.join(list(strong)[:3])}")
    if body:
        pts += min(8, sum(body.values()))
        if not strong:
            why.append(f"theme words in text: {', '.join(list(body)[:3])}")
    if not strong and not body:
        pts -= 8
        warn.append(f"no sign of theme '{req.theme['label']}'")

    # 4. Is it actually an exercise? (0-20)
    overview = False
    formats = list(a.formats) if verified else []
    # Only actual practice material on an exam site counts as an exam, not its registration or FAQ pages.
    if src and "exam" in src.formats and EXAM_PAGE.search(f"{title} {url}"):
        formats.append("exam")
    if verified:
        ex = 0
        if "interactive" in formats:
            ex += 10
            why.append("interactive exercise" + (f" ({a.interactive_inputs} inputs)" if a.interactive_inputs else ""))
        ex += min(6, a.exercise_words)
        if a.blanks >= 3 or a.numbered_items >= 5:
            ex += 4
            why.append(f"worksheet items ({max(a.blanks, a.numbered_items)})")
        if "exam" in formats:
            ex += 6
        if ex <= 3 and "reading_text" in formats:
            ex = 4
            warn.append("reading/listening material without exercises")
        elif ex <= 2 and not ({"pdf", "pdf_links", "video", "audio"} & set(formats)):
            pts -= 8
            warn.append("no exercise found on the page (info or overview page?)")
        if OVERVIEW_PAGE.search(f"{title} {url}"):
            overview = True
            warn.append("overview/brochure page: follow its links instead")
        pts += min(20, ex)
        if a.has_answer_key:
            pts += 6
            why.append("has answers/feedback")
        if a.word_count < 40 and "interactive" not in formats and "pdf" not in formats:
            pts -= 8
            warn.append("very little content (may need JavaScript or login)")
    else:
        if any(w in (title + " " + snippet).lower() for w in ("oefening", "exercise", "opdracht", "quiz", "oefenen")):
            pts += 6

    # 5. Skills and formats the agent asked for.
    skills = list(a.skills) if verified else []
    if src:
        skills = skills or [s for s in src.skills if s in req.skills]
    if req.skills:
        overlap = set(req.skills) & set(skills)
        if overlap:
            pts += 6
            why.append(f"skills: {', '.join(sorted(overlap))}")
        elif skills:
            pts -= 4
    if req.formats:
        have = set(formats) | ({"pdf"} if url.lower().split("?")[0].endswith(".pdf") else set())
        if "pdf_links" in have:
            have.add("pdf")
        if set(req.formats) & have:
            pts += 5
        elif verified:
            pts -= 3

    # 6. Penalties.
    if req.free_only and ((src and not src.free) or (verified and a.paywall)):
        pts -= 15
        warn.append("probably needs a login or payment")
    if verified and a.language == "en" and a.dutch_ratio < 0.15:
        pts -= 20
        warn.append("page is almost all English")
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if re.search(r"(^|&)(q|s|query|zoek|search)=", parsed.query) or re.search(r"\b(zoeken|search results|zoekresultaten)\b",
                                                                             title.lower()):
        pts -= 12
        warn.append("search results page: browse it for exercises rather than using it directly")
    if not path:
        pts -= 10
        warn.append("site home page, not a specific exercise")
    if not verified:
        warn.append("not fetched" + (f" ({a.error})" if a and a.error else "") + ": scored from the search snippet")
        pts = min(pts, 55)

    if overview:
        pts = min(pts - 10, 45)
    return Scored(score=max(0, min(100, round(pts))), level_fit=fit, reasons=why, warnings=warn,
                  levels=levels, estimated_level=est)
