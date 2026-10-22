"""The curated source catalog (data/sources.json) and lookups against it."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from .levels import in_range

SKILLS = ["reading", "listening", "speaking", "writing", "vocabulary", "grammar"]

# Sites that rank for everything and are never the exercise itself.
BLOCKED_DOMAINS = {
    "pinterest.com", "pinterest.nl", "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com",
    "amazon.com", "amazon.nl", "bol.com", "reddit.com", "linkedin.com", "scribd.com", "studocu.com",
    "coursehero.com", "etsy.com", "teacherspayteachers.com",
}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    domains: tuple[str, ...]
    url: str
    levels: tuple[str, str]
    skills: tuple[str, ...]
    formats: tuple[str, ...]
    variant: str
    free: bool
    quality: int
    notes: str
    user_generated: bool = False
    site_search: str = ""
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    def covers(self, level: str) -> bool:
        return in_range(level, *self.levels)

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.name, "url": self.url, "levels": f"{self.levels[0]}-{self.levels[1]}",
            "skills": list(self.skills), "formats": list(self.formats), "variant": self.variant,
            "free": self.free, "quality": self.quality, "user_generated": self.user_generated, "notes": self.notes,
        }


def _load(path: Path) -> list[Source]:
    out = []
    for d in json.loads(path.read_text(encoding="utf-8")):
        out.append(Source(
            id=d["id"], name=d["name"], domains=tuple(d["domains"]), url=d["url"], levels=tuple(d["levels"]),
            skills=tuple(d["skills"]), formats=tuple(d["formats"]), variant=d.get("variant", "nl"),
            free=d.get("free", True), quality=int(d.get("quality", 3)), notes=d.get("notes", ""),
            user_generated=d.get("user_generated", False), site_search=d.get("site_search", ""),
        ))
    return out


@lru_cache(maxsize=1)
def catalog() -> tuple[Source, ...]:
    """Built-in catalog, plus/overridden by SOURCES_FILE (same JSON shape) if set."""
    items = {s.id: s for s in _load(Path(__file__).parent / "data" / "sources.json")}
    extra = os.environ.get("SOURCES_FILE")
    if extra:
        for s in _load(Path(extra).expanduser()):
            items[s.id] = s
    return tuple(items.values())


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def source_for_url(url: str) -> Source | None:
    host = host_of(url)
    for s in catalog():
        if any(_matches(host, d) for d in s.domains):
            return s
    return None


def is_blocked(url: str) -> bool:
    host = host_of(url)
    return any(_matches(host, d) for d in BLOCKED_DOMAINS)


def select_sources(level: str, skills: list[str], variant: str, free_only: bool,
                   include_user_generated: bool = False) -> list[Source]:
    """Catalog sources that cover the level, best first. Skill overlap and variant break ties."""
    picked = []
    for s in catalog():
        if not s.covers(level):
            continue
        if free_only and not s.free:
            continue
        if s.user_generated and not include_user_generated:
            continue
        if variant in ("nl", "be") and s.variant not in (variant, "both"):
            # Keep the other variant's sources, ranked lower: Dutch is Dutch for most exercises.
            penalty = 1
        else:
            penalty = 0
        overlap = len(set(skills) & set(s.skills)) if skills else 1
        if skills and overlap == 0:
            continue
        picked.append((s.quality - penalty, overlap, "exam" not in s.formats, s))
    picked.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [t[3] for t in picked]
