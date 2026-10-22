"""MCP server that finds high-quality Dutch (NT2) learning exercises for a theme and CEFR level.

Tools:

  find_exercises     search curated NT2 sources + the web, fetch and grade each page, return a ranked list
  inspect_exercise   grade one URL in detail (level, skills, format, answer key, text excerpt)
  rate_exercise      record how good an exercise turned out; ratings steer future rankings
  list_sources       the curated source catalog, filterable by level/skill/variant
  list_themes        the theme taxonomy (everyday topics and grammar points)
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.requests import Request as HttpRequest
from starlette.responses import JSONResponse

from . import search as search_mod
from .analyze import FetchError, check_url
from .finder import Finder, normalize_url
from .levels import LEVELS, parse_level
from .scoring import Request, score
from .sources import SKILLS, catalog, host_of, select_sources, source_for_url
from .store import Store
from .themes import list_themes as _list_themes, resolve_theme

log = logging.getLogger("dutch_exercises")

VERSION = "0.1.0"

INSTRUCTIONS = """\
Finds existing, high-quality exercises for learners of Dutch (NT2 / Dutch as a second language).

Workflow:
1. Call find_exercises with a theme (any language: "boodschappen", "job interview", "perfectum") and a CEFR
   level (A0-C2, or "beginner", "Staatsexamen II", ...). Add skills/formats when the learner needs something
   specific, and variant="be" for Flemish material.
2. Results are ranked by score (0-100). Prefer verified results with level.fit "exact" and has_answer_key.
   Read `warnings`: "not fetched" results were scored from a search snippet only.
3. Before giving a learner an exercise you're unsure about, call inspect_exercise for the full picture.
4. After the learner has used an exercise, call rate_exercise (1-5) with a short note. Ratings of 1 hide the
   URL from future searches; good ratings boost it.
Never present an exercise as matching a level or theme unless the result says so; level estimates are rough.
"""

mcp = MCPServer(name="dutch-exercises", title="Dutch Exercise Finder", instructions=INSTRUCTIONS, version=VERSION)

_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def _level(value: str) -> str:
    lv = parse_level(value)
    if not lv:
        raise ToolError(f"Unknown level {value!r}. Use a CEFR level ({', '.join(LEVELS)}) or e.g. 'beginner'.")
    return lv


Skill = Literal["reading", "listening", "speaking", "writing", "vocabulary", "grammar"]
Format = Literal["interactive", "worksheet", "pdf", "video", "audio", "exam", "reading_text"]


@mcp.tool(description="Find ranked Dutch-learning exercises for a theme and CEFR level. Searches curated NT2 "
          "sources first (NT2 TaalMenu, Oefenen.nl, NedBox, official exam sites, ...) and then the open web, "
          "fetches each candidate and grades it on source reputation, level match, theme match, whether it is a "
          "real exercise, answer key, skills and access. Returns results with score, level fit, reasons and warnings.")
async def find_exercises(
    theme: str = Field(description="Topic or grammar point, in Dutch or English: 'boodschappen', 'at the doctor', "
                       "'de of het', 'perfectum', 'solliciteren'."),
    level: str = Field(description="CEFR level A0-C2, or a description like 'beginner', 'A2+', 'Staatsexamen I'."),
    skills: list[Skill] = Field(default_factory=list, description="Skills to practise; empty = any."),
    formats: list[Format] = Field(default_factory=list, description="Preferred formats; empty = any."),
    variant: Literal["any", "nl", "be"] = Field("any", description="'nl' Netherlands Dutch, 'be' Flemish, 'any'."),
    free_only: bool = Field(True, description="Skip paid or login-only material."),
    vetted_only: bool = Field(False, description="Only return pages from the curated source catalog."),
    include_user_generated: bool = Field(False, description="Also include Wordwall/Quizlet/LearningApps sets."),
    extra_terms: str = Field("", description="Extra search words, e.g. 'bakker' or 'sollicitatiebrief'."),
    max_results: int = Field(8, ge=1, le=20),
) -> dict:
    req = Request(level=_level(level), theme=resolve_theme(theme), skills=list(skills), formats=list(formats),
                  free_only=free_only)
    try:
        return await Finder(store()).find(req, variant=variant, max_results=max_results, vetted_only=vetted_only,
                                          include_user_generated=include_user_generated, extra_terms=extra_terms)
    except search_mod.SearchError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(description="Fetch one exercise page (HTML or PDF) and report what it is: stated and estimated CEFR "
          "level, skills, formats, interactive inputs, answer key, paywall, linked PDFs and a text excerpt. "
          "Give theme and level to also get a score against them.")
async def inspect_exercise(
    url: str = Field(description="The exercise URL."),
    level: str = Field("", description="Optional target level, to score the page against."),
    theme: str = Field("", description="Optional theme, to score the page against."),
    include_text: bool = Field(False, description="Include up to 8000 characters of the page text."),
    refresh: bool = Field(False, description="Ignore the 7-day page cache."),
) -> dict:
    try:
        await check_url(url)
    except FetchError as exc:
        raise ToolError(str(exc)) from exc
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8)) as client:
        a = await Finder(store(), client).analyze(client, url, refresh=refresh)
    src = source_for_url(a.final_url or url)
    out = {"analysis": a.public(with_text=include_text),
           "source": src.public() if src else None,
           "your_rating": None}
    r = store().rating_of(normalize_url(url))
    if r:
        out["your_rating"] = {"average": round(r[0], 2), "count": r[1]}
    if level:
        req = Request(level=_level(level), theme=resolve_theme(theme or a.title or "nederlands"))
        s = score(req, a.final_url or url, a.title, a.description, a, src, r, store().domain_rating(host_of(url)))
        out["score"] = {"score": s.score, "level_fit": s.level_fit, "why": s.reasons, "warnings": s.warnings}
    return out


@mcp.tool(description="Record how good an exercise was for a learner (1 = unusable, 5 = excellent). Ratings "
          "change future rankings: 1 hides the URL from find_exercises, 4-5 boost it and its site.")
def rate_exercise(
    url: str = Field(description="The exercise URL."),
    rating: int = Field(ge=1, le=5, description="1 unusable ... 5 excellent."),
    level: str = Field("", description="Level of the learner who used it."),
    theme: str = Field("", description="Theme it was used for."),
    note: str = Field("", max_length=500, description="What was good or bad: wrong level, errors, broken, ..."),
) -> dict:
    lv = parse_level(level) if level else ""
    store().rate(normalize_url(url), rating, lv or "", theme, note)
    avg, n = store().rating_of(normalize_url(url))
    return {"ok": True, "url": url, "average": round(avg, 2), "ratings": n}


@mcp.tool(description="List the curated Dutch-learning sources with their levels, skills, formats, variant "
          "(nl/be), cost and quality (1-5). Filter by level, skill and variant.")
def list_sources(
    level: str = Field("", description="Only sources covering this level."),
    skill: Skill | None = Field(None),
    variant: Literal["any", "nl", "be"] = Field("any"),
    include_paid: bool = Field(True),
) -> dict:
    if level:
        items = select_sources(_level(level), [skill] if skill else [], variant, not include_paid, True)
    else:
        items = [s for s in catalog() if (not skill or skill in s.skills) and (include_paid or s.free)
                 and (variant == "any" or s.variant in (variant, "both"))]
        items.sort(key=lambda s: s.quality, reverse=True)
    return {"sources": [s.public() for s in items]}


@mcp.tool(description="List known themes (everyday topics and grammar points) with their Dutch search terms. "
          "find_exercises also accepts any other theme as free text.")
def list_themes() -> dict:
    return {"themes": _list_themes(), "levels": LEVELS, "skills": SKILLS}


@mcp.tool(description="Show the most recent exercise ratings.")
def list_ratings(limit: int = Field(30, ge=1, le=200)) -> dict:
    return {"ratings": store().ratings(limit)}


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: HttpRequest):
    return JSONResponse({"ok": True, "search_provider": search_mod.provider_name()})


class BearerAuth:
    """Requires `Authorization: Bearer <MCP_TOKEN>` on the MCP endpoint."""

    def __init__(self, app, token: str, path: str = "/mcp"):
        self.app, self.token, self.path = app, token, path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.path):
            headers = dict(scope.get("headers") or [])
            given = headers.get(b"authorization", b"").decode()
            if not secrets.compare_digest(given, f"Bearer {self.token}"):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def http_app(host: str):
    allowed = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    app = mcp.streamable_http_app(
        host=host,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(allowed), allowed_hosts=allowed, allowed_origins=[],
        ),
    )
    token = os.environ.get("MCP_TOKEN", "")
    return BearerAuth(app, token) if token else app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dutch-exercises-mcp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transport", choices=["http", "stdio"], default=os.environ.get("TRANSPORT", "stdio"))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8010")))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    if args.transport == "stdio":
        mcp.run("stdio")
        return 0
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("MCP_TOKEN"):
        print("Refusing to listen on a public interface without MCP_TOKEN set.", file=sys.stderr)
        return 2
    import uvicorn

    log.info("MCP endpoint: http://%s:%d/mcp · search: %s", args.host, args.port, search_mod.provider_name())
    uvicorn.run(http_app(args.host), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
