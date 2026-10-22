"""The search pipeline behind find_exercises: plan queries, search, fetch, analyse, score, rank."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from . import search as search_mod
from .analyze import Analysis, analyze_url
from .connectors import CONNECTORS
from .levels import stated_levels
from .scoring import Request, score
from .sources import Source, host_of, is_blocked, select_sources, source_for_url
from .store import Store
from .themes import THEMES, theme_hits

# Bump when analysis logic changes so cached page analyses are redone.
ANALYSIS_VERSION = "4"

TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|mc_)")


def normalize_url(url: str) -> str:
    p = urlparse(url)
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    host = (p.hostname or "").lower()
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), host, path, "", query, ""))


def plan_queries(req: Request, sources: list[Source], vetted_only: bool, extra: str = "") -> list[tuple[str, list[str]]]:
    """(terms, domains) pairs. Site-restricted queries over the best sources first, then the open web.

    Topic queries include the level, because NT2 sites organise topics by level. Grammar queries don't:
    a grammar point lives at one level on a site (de/het is A2 on NT2 TaalMenu), and the level filter is
    applied when scoring anyway. English-language sites get English terms.
    """
    t = req.theme
    term = t["search_terms"][0]
    second = t["search_terms"][1] if len(t["search_terms"]) > 1 else term
    grammar = t["kind"] == "grammar"
    en = THEMES[t["key"]][3][0] if t["key"] else t["label"]
    extra = f" {extra.strip()}" if extra.strip() else ""
    level = "" if grammar else f" {req.level}"
    searchable = [s for s in sources if not s.connector]
    nl = [s.domains[0] for s in searchable if s.lang != "en"]
    en_sites = [s.domains[0] for s in searchable if s.lang == "en"]
    plans: list[tuple[str, list[str]]] = []
    if nl[:4]:
        plans.append((f"{term}{level}{extra}", nl[:4]))
    if nl[4:8]:
        plans.append((f"{term} oefening{extra}", nl[4:8]))
    if en_sites[:4]:
        plans.append((f"Dutch {en} exercise{extra}", en_sites[:4]))
    if not vetted_only:
        if grammar:
            plans.append((f"{second} oefening NT2{extra}", []))
            plans.append((f"Dutch grammar {en} exercises {req.level}{extra}", []))
        else:
            plans.append((f"{term} oefening NT2 {req.level}{extra}", []))
            plans.append((f"{second} Nederlands leren oefenen {req.level}{extra}", []))
    return plans


def singular(term: str) -> str:
    """Rough Dutch singular for one-word terms ('lidwoorden' -> 'lidwoord', 'boodschappen' -> 'boodschap').

    Site search engines (WordPress) match substrings, so the singular also finds the plural.
    """
    if " " in term or len(term) < 7:
        return term
    if term.endswith("en"):
        stem = term[:-2]
        if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            stem = stem[:-1]
        return stem
    if term.endswith("s") and term[-3:-1] in ("el", "er", "je"):
        return term[:-1]
    return term


def _prescore(req: Request, title: str, snippet: str, url: str) -> float:
    src = source_for_url(url)
    s = (src.quality * 2 if src else 3) - (3 if src and src.user_generated else 0)
    if theme_hits(req.theme["keywords"], f"{title} {url}"):
        s += 4
    if req.level in stated_levels(title, snippet, url):
        s += 3
    if not urlparse(url).path.strip("/"):
        s -= 4
    return s


def family(url: str) -> str:
    src = source_for_url(url)
    return src.id if src else host_of(url)


def diversify(hits: list, limit: int, per_family: int = 4) -> list:
    """Best-first, but at most `per_family` per site until other sites have had a turn."""
    first, rest, count = [], [], {}
    for h in hits:
        f = family(h.url)
        count[f] = count.get(f, 0) + 1
        (first if count[f] <= per_family else rest).append(h)
    return (first + rest)[:limit]


class Finder:
    def __init__(self, store: Store, client: httpx.AsyncClient | None = None):
        self.store = store
        self.client = client

    def _client(self) -> httpx.AsyncClient:
        return self.client or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8))

    async def _search(self, client, plans, region) -> tuple[list[search_mod.Hit], list[str], list[str]]:
        provider = search_mod.provider_name()
        queries = [search_mod.build_query(terms, domains) for terms, domains in plans]
        cached: dict[str, list] = {}
        todo = []
        for q in queries:
            hit = self.store.get_search(f"{provider}|{region}|{q}")
            if hit is not None:
                cached[q] = hit
            else:
                todo.append(q)
        fresh, errors = await search_mod.search_many(client, todo, per_query=10, region=region) if todo else ([], [])
        by_q: dict[str, list] = {}
        for h in fresh:
            by_q.setdefault(h.query, []).append(asdict(h))
        for q in todo:
            if q in by_q or not errors:  # don't cache a failed query as "no results"
                self.store.put_search(f"{provider}|{region}|{q}", by_q.get(q, []))
        hits = []
        for q in queries:
            for d in cached.get(q, by_q.get(q, [])):
                hits.append(search_mod.Hit(**d))
        return hits, errors, queries

    async def analyze(self, client, url: str, refresh: bool = False) -> Analysis:
        key = f"{ANALYSIS_VERSION}|{normalize_url(url)}"
        if not refresh:
            data = self.store.get_page(key)
            if data:
                return Analysis(**data)
        a = await analyze_url(client, url)
        if a.ok or "HTTP 4" in a.error:
            data = asdict(a)
            data["text"] = data["text"][:60000]
            self.store.put_page(key, data)
        return a

    async def _expand_hubs(self, client, req: Request, checked, seen: dict, check, max_new: int = 8) -> list:
        """Follow theme links one level down from on-theme hub pages ('Grammatica - Menu Lidwoord' ->
        'Lidwoord - Oef 1', 'Oef 2', ...). Exercises often sit one click below the page search finds."""
        kws = req.theme["keywords"]
        children: list[search_mod.Hit] = []
        for h, a in checked:
            if not (a.ok and a.links) or not theme_hits(kws, f"{a.title} {' '.join(a.headings)} {a.final_url}"):
                continue
            picked = 0
            for url, text in a.links:
                key = normalize_url(url)
                if key in seen or "?" in url or not theme_hits(kws, f"{text} {url.replace('-', ' ')}") \
                        or is_blocked(url):
                    continue
                seen[key] = search_mod.Hit(url, text, "", f"via:{a.final_url}")
                children.append(seen[key])
                picked += 1
                if picked >= 3 or len(children) >= max_new:
                    break
            if len(children) >= max_new:
                break
        return list(await asyncio.gather(*(check(h) for h in children)))

    async def find(self, req: Request, *, variant: str = "any", max_results: int = 8, vetted_only: bool = False,
                   include_user_generated: bool = False, extra_terms: str = "", inspect_limit: int = 14) -> dict:
        sources = select_sources(req.level, req.skills, variant, req.free_only, include_user_generated)
        plans = plan_queries(req, sources, vetted_only, extra_terms)
        region = "be" if variant == "be" else "nl"
        own_client = self.client is None
        client = self._client()
        try:
            native = [s for s in sources if s.site_search][:3]
            terms = list(dict.fromkeys(singular(x) for x in req.theme["search_terms"][:2]))
            native_jobs = [(s, term) for s in native for term in terms]
            connected = [s for s in sources if s.connector in CONNECTORS]
            web, *rest = await asyncio.gather(
                self._search(client, plans, region),
                *(search_mod.site_search(client, s.site_search, term) for s, term in native_jobs),
                *(CONNECTORS[s.connector](client, req, req.theme["search_terms"]) for s in connected),
            )
            site, direct = rest[:len(native_jobs)], rest[len(native_jobs):]
            hits, errors, queries = web
            # Site-native hits first among equals: they come straight from the best sources.
            hits = [h for group in site for h in group] + hits
            queries = queries + [f"{s.name} site search: {term}" for s, term in native_jobs]
            queries += [f"{s.name} API" for s in connected]

            seen: dict[str, search_mod.Hit] = {}
            for h in hits:
                if is_blocked(h.url):
                    continue
                src = source_for_url(h.url)
                if vetted_only and not src:
                    continue
                if src and src.user_generated and not include_user_generated:
                    continue
                if src and req.free_only and not src.free:
                    continue
                r = self.store.rating_of(normalize_url(h.url))
                if r and r[0] <= 1.5:
                    continue  # the agent rejected this one before
                seen.setdefault(normalize_url(h.url), h)

            ranked = sorted(seen.values(), key=lambda h: _prescore(req, h.title, h.snippet, h.url), reverse=True)
            to_check = diversify(ranked, inspect_limit)
            sem = asyncio.Semaphore(6)

            async def check(h):
                async with sem:
                    return h, await self.analyze(client, h.url)

            checked = list(await asyncio.gather(*(check(h) for h in to_check)))
            # Connector results arrive pre-analysed; keep the best few per connector.
            for pairs in direct:
                checked += sorted(pairs, key=lambda p: bool(theme_hits(req.theme["keywords"], p[1].text)),
                                  reverse=True)[:6]
            seen.update({normalize_url(h.url): h for pairs in direct for h, _ in pairs})
            checked += await self._expand_hubs(client, req, checked, seen, check)
        finally:
            if own_client:
                await client.aclose()

        results = []
        for h, a in checked:
            src = source_for_url(a.final_url or h.url)
            key = normalize_url(h.url)
            s = score(req, a.final_url or h.url, h.title, h.snippet, a, src,
                      self.store.rating_of(key), self.store.domain_rating(host_of(h.url)))
            results.append({
                "score": s.score,
                "title": (a.title if a.ok and a.title else h.title)[:160],
                "url": a.final_url or h.url,
                "source": src.name if src else host_of(h.url),
                "curated": bool(src and not src.user_generated),
                "level": {"stated": s.levels[:4], "estimated": s.estimated_level, "fit": s.level_fit},
                "skills": a.skills if a.ok else [],
                "formats": sorted(set(a.formats + (["exam"] if src and "exam" in src.formats else []))) if a.ok else [],
                "has_answer_key": a.has_answer_key if a.ok else None,
                "free": (src.free if src else None) if not (a.ok and a.paywall) else False,
                "verified": a.ok,
                "why": s.reasons,
                "warnings": s.warnings,
                "preview": (a.description or a.excerpt[:240]) if a.ok else h.snippet[:240],
                "linked_pdfs": a.linked_pdfs[:3] if a.ok else [],
            })
            if h.query.startswith("via:"):
                results[-1]["found_via"] = h.query[4:]

        results.sort(key=lambda r: r["score"], reverse=True)
        final, per_source, seen_keys = [], {}, set()
        for r in results:
            fam = family(r["url"])
            # The same lesson often lives on several subdomains or mirrors: dedupe on title within a site.
            title_key = (fam, re.sub(r"\W+", " ", r["title"].lower()).strip())
            if normalize_url(r["url"]) in seen_keys or title_key in seen_keys or per_source.get(fam, 0) >= 3:
                continue
            seen_keys.update({normalize_url(r["url"]), title_key})
            per_source[fam] = per_source.get(fam, 0) + 1
            final.append(r)
        final = final[:max_results]
        for i, r in enumerate(final, 1):
            r["rank"] = i

        out = {
            "request": {"theme": req.theme["label"], "theme_key": req.theme["key"], "level": req.level,
                        "skills": req.skills, "formats": req.formats, "variant": variant, "free_only": req.free_only},
            "search_provider": search_mod.provider_name(),
            "queries": queries,
            "results": final,
            "candidates_seen": len(seen),
            "candidates_checked": len(checked),
        }
        if errors:
            out["errors"] = errors
        if not final:
            out["fallback_sources"] = [s.public() for s in sources[:6]]
            out["tip"] = ("No exercises found. Browse fallback_sources directly, broaden the theme, try a "
                          "neighbouring level, or set vetted_only=false.")
        elif max(r["score"] for r in final) < 50:
            out["tip"] = "Weak matches only. Consider a broader theme, a neighbouring level, or extra_terms."
        return out
