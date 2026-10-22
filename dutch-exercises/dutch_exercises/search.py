"""Web search backends. Picks the first configured one: Brave, Tavily, SearXNG, then DuckDuckGo (no key)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


@dataclass
class Hit:
    url: str
    title: str
    snippet: str
    query: str


class SearchError(Exception):
    pass


def provider_name() -> str:
    forced = os.environ.get("SEARCH_PROVIDER", "auto").lower()
    if forced != "auto":
        return forced
    if os.environ.get("BRAVE_API_KEY"):
        return "brave"
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    if os.environ.get("SEARXNG_URL"):
        return "searxng"
    return "duckduckgo"


def build_query(terms: str, domains: list[str] | None) -> str:
    if not domains:
        return terms
    sites = " OR ".join(f"site:{d}" for d in domains)
    return f"{terms} ({sites})" if len(domains) > 1 else f"{terms} site:{domains[0]}"


async def _brave(client: httpx.AsyncClient, query: str, n: int, region: str) -> list[Hit]:
    r = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(n, 20), "country": region.upper(), "search_lang": "nl"},
        headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"], "Accept": "application/json"},
    )
    r.raise_for_status()
    return [Hit(x["url"], x.get("title", ""), _strip(x.get("description", "")), query)
            for x in r.json().get("web", {}).get("results", [])]


async def _tavily(client: httpx.AsyncClient, query: str, n: int, region: str) -> list[Hit]:
    r = await client.post(
        "https://api.tavily.com/search",
        json={"query": query, "max_results": min(n, 20), "search_depth": "basic"},
        headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
    )
    r.raise_for_status()
    return [Hit(x["url"], x.get("title", ""), x.get("content", "")[:400], query) for x in r.json().get("results", [])]


async def _searxng(client: httpx.AsyncClient, query: str, n: int, region: str) -> list[Hit]:
    base = os.environ["SEARXNG_URL"].rstrip("/")
    r = await client.get(f"{base}/search", params={"q": query, "format": "json", "language": f"nl-{region.upper()}"})
    r.raise_for_status()
    return [Hit(x["url"], x.get("title", ""), x.get("content", ""), query) for x in r.json().get("results", [])[:n]]


_DDG_LINK = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:a|div|td)>', re.S)


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _ddg_url(href: str) -> str:
    href = unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        return unquote(parse_qs(parsed.query).get("uddg", [href])[0])
    return href


def parse_ddg(html: str, query: str) -> list[Hit]:
    hits = []
    blocks = html.split('class="result__a"')[1:]
    for block in blocks:
        link = _DDG_LINK.search('class="result__a"' + block)
        if not link:
            continue
        href, title = link.groups()
        snip = _DDG_SNIPPET.search(block)
        snippet = snip.group(1) if snip else ""
        url = _ddg_url(href)
        if "duckduckgo.com/y.js" in url or not url.startswith("http"):
            continue  # ads
        hits.append(Hit(url, _strip(title), _strip(snippet), query))
    return hits


async def _duckduckgo(client: httpx.AsyncClient, query: str, n: int, region: str) -> list[Hit]:
    for wait in (3, 8, None):
        r = await client.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": f"{region}-nl"},
                              headers={"User-Agent": UA, "Referer": "https://html.duckduckgo.com/"})
        if r.status_code == 200 and "result__a" in r.text:
            return parse_ddg(r.text, query)[:n]
        throttled = "anomaly" in r.text.lower() or r.status_code in (202, 403, 429)
        if not throttled:
            return []
        if wait is None:
            raise SearchError("DuckDuckGo is rate-limiting this server, so web results are partial; set "
                              "BRAVE_API_KEY or TAVILY_API_KEY for reliable search.")
        await asyncio.sleep(wait)
    return []


# --- site-native search (no key needed) ---------------------------------------------------

_LINK = re.compile(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.S | re.I)
_CHROME = re.compile(r"(?si)<(nav|header|footer|aside|script|style)\b.*?</\1>")
_SKIP_PATH = re.compile(r"/(tag|category|author|page|feed|wp-content|wp-json|privacy|cookie|contact|login|"
                        r"cart|shop|winkelwagen|account)\b|privacyverklaring|\?|\.(png|jpe?g|svg|css|js)$", re.I)


def parse_site_search(html: str, base_url: str, query: str) -> list[Hit]:
    """Content links from a site's own search results page (navigation and chrome stripped)."""
    from urllib.parse import urljoin

    host = (urlparse(base_url).hostname or "").removeprefix("www.")
    body = _CHROME.sub(" ", html)
    hits, seen = [], set()
    for href, label in _LINK.findall(body):
        url = urljoin(base_url, unescape(href))
        p = urlparse(url)
        h = (p.hostname or "").removeprefix("www.")
        text = _strip(label)
        if not (h == host or h.endswith("." + host)) or len(p.path.strip("/")) < 6 or _SKIP_PATH.search(url):
            continue
        if url in seen or len(text) < 4:
            continue
        seen.add(url)
        hits.append(Hit(url, text[:160], "", query))
    return hits


async def site_search(client: httpx.AsyncClient, template: str, terms: str, n: int = 15) -> list[Hit]:
    from urllib.parse import quote_plus

    url = template.replace("{q}", quote_plus(terms))
    try:
        r = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    return parse_site_search(r.text, str(r.url), f"site-search:{url}")[:n]


BACKENDS = {"brave": _brave, "tavily": _tavily, "searxng": _searxng, "duckduckgo": _duckduckgo}


async def search_many(client: httpx.AsyncClient, queries: list[str], per_query: int = 10,
                      region: str = "nl") -> tuple[list[Hit], list[str]]:
    """Run queries with the configured backend. Returns hits (in query order) and error messages."""
    name = provider_name()
    backend = BACKENDS.get(name)
    if backend is None:
        raise SearchError(f"Unknown SEARCH_PROVIDER {name!r}; use one of {', '.join(BACKENDS)}.")
    # DuckDuckGo throttles bursts, so go one at a time there.
    sem = asyncio.Semaphore(1 if name == "duckduckgo" else 4)
    errors: list[str] = []

    async def one(q: str) -> list[Hit]:
        async with sem:
            try:
                hits = await backend(client, q, per_query, region)
                if name == "duckduckgo":
                    await asyncio.sleep(0.8)
                return hits
            except SearchError as exc:
                errors.append(str(exc))
            except httpx.HTTPError as exc:
                errors.append(f"{name} search failed for {q!r}: {exc}")
            return []

    results = await asyncio.gather(*(one(q) for q in queries))
    return [h for hits in results for h in hits], list(dict.fromkeys(errors))
