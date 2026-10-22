"""Fetch a page and read what kind of Dutch exercise it is: level, skills, format, answer key, paywall."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import logging
import re
import socket
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .levels import estimate_level, stated_levels
from .search import UA

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings on nearly every real-world PDF

MAX_HTML_BYTES = 3_000_000
MAX_PDF_BYTES = 20_000_000

DUTCH_STOPWORDS = set("""
de het een en van ik je jij u hij zij ze wij we is zijn was waren niet op aan met voor dat die dit deze er
in te om naar ook maar of als bij nog wel geen heb heeft hebben kan kunnen wordt worden mijn jouw uw hun
wat wie waar hoe waarom welke zo dan al toch omdat want dus nu hier daar mag moet wil gaat
""".split())
ENGLISH_STOPWORDS = set("the and of to is are was were you your this that with for on in it be have has not "
                        "what which how why can will would should there their they".split())

EXERCISE_WORDS = [
    "oefening", "oefeningen", "opdracht", "vul in", "vul het", "invullen", "invuloefening", "kies het juiste",
    "kies de juiste", "kies het goede", "meerkeuze", "juist of fout", "waar of niet waar", "goed of fout",
    "sleep", "maak de zin", "zet in de juiste volgorde", "beantwoord de vragen", "luister en", "lees de tekst",
    "kruis aan", "omcirkel", "verbind", "schrijf", "spreekopdracht", "toets", "quiz",
    "exercise", "exercises", "fill in", "fill in the blanks", "choose the correct", "multiple choice", "quiz",
    "drag", "match the", "practice", "worksheet", "werkblad",
]
ANSWER_WORDS = [
    "antwoorden", "antwoordsleutel", "antwoordblad", "oplossing", "oplossingen", "correctiesleutel",
    "nakijken", "controleer", "controleren", "check je antwoord", "goed zo", "answer key", "answers",
    "check answers", "check your answers", "solutions", "feedback",
]
PAYWALL_WORDS = [
    "log in om", "inloggen om", "alleen voor abonnees", "abonnement", "licentie", "koop nu", "bestel nu",
    "in winkelwagen", "upgrade", "premium", "proefperiode", "subscribe to", "sign up to access",
    "members only", "purchase", "add to cart", "buy now", "free trial",
]
# Any one of these is enough to call it login-only.
LOGIN_WALL = [
    "meld aan of registreer", "registreer om", "log in om dit", "aanmelden om dit", "alleen voor leden",
    "log in to view", "log in to see", "sign in to view", "sign up to view", "members only",
]
SKILL_WORDS = {
    "reading": ["lezen", "leesoefening", "leestekst", "lees de tekst", "leesvaardigheid", "begrijpend lezen",
                "reading"],
    "listening": ["luisteren", "luisteroefening", "luistervaardigheid", "luister", "listening", "audio"],
    "speaking": ["spreken", "spreekoefening", "spreekvaardigheid", "uitspraak", "gesprek", "dialoog", "speaking",
                 "conversation", "pronunciation"],
    "writing": ["schrijven", "schrijfopdracht", "schrijfvaardigheid", "brief schrijven", "e-mail schrijven",
                "writing"],
    "vocabulary": ["woordenschat", "woorden", "woordenlijst", "vocabulaire", "vocabulary", "words", "flashcards"],
    "grammar": ["grammatica", "werkwoord", "werkwoorden", "zinsbouw", "vervoeging", "grammar", "verbs",
                "conjugation"],
}
EMBED_HOSTS = {
    "h5p": "h5p", "wordwall.net": "wordwall", "learningapps.org": "learningapps", "quizlet.com": "quizlet",
    "kahoot": "kahoot", "forms.gle": "form", "docs.google.com/forms": "form", "liveworksheets": "liveworksheets",
    "youtube.com": "video", "youtube-nocookie.com": "video", "youtu.be": "video", "vimeo.com": "video",
    "soundcloud.com": "audio",
}
BLANK = re.compile(r"_{3,}|\.{4,}|…{2,}|\(\s*\)\s*\w|\[\s*\]")
NUMBERED = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[a-h][.)])\s+\S")


class FetchError(Exception):
    pass


@dataclass
class Analysis:
    url: str
    final_url: str = ""
    ok: bool = False
    error: str = ""
    content_type: str = ""
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    language: str = "unknown"          # nl / en / mixed / unknown
    dutch_ratio: float = 0.0
    word_count: int = 0
    stated_levels: list[str] = field(default_factory=list)
    estimated: dict | None = None
    skills: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)  # interactive, pdf, video, audio, worksheet, reading_text...
    interactive_inputs: int = 0
    blanks: int = 0
    numbered_items: int = 0
    exercise_words: int = 0
    has_answer_key: bool = False
    paywall: bool = False
    embeds: list[str] = field(default_factory=list)
    linked_pdfs: list[str] = field(default_factory=list)
    excerpt: str = ""
    text: str = field(default="", repr=False)

    def public(self, with_text: bool = False, excerpt_chars: int = 600) -> dict:
        d = asdict(self)
        d.pop("text")
        d["excerpt"] = self.excerpt[:excerpt_chars]
        if with_text:
            d["text"] = self.text[:8000]
        return d


# --- fetching ---------------------------------------------------------------------------------

def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


async def check_url(url: str) -> None:
    """Only public http(s) URLs: the server may be reachable by an agent, so no internal fetches."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchError("Only http(s) URLs are supported.")
    if not await asyncio.to_thread(_is_public_host, p.hostname):
        raise FetchError(f"Refusing to fetch non-public host {p.hostname}.")


async def fetch(client: httpx.AsyncClient, url: str) -> tuple[str, str, bytes]:
    """GET with manual redirects (each hop re-checked). Returns (final_url, content_type, body)."""
    for _ in range(5):
        await check_url(url)
        async with client.stream("GET", url, headers={"User-Agent": UA, "Accept-Language": "nl,en;q=0.7"},
                                 follow_redirects=False) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers.get("location", ""))
                continue
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            limit = MAX_PDF_BYTES if ctype == "application/pdf" or url.lower().split("?")[0].endswith(".pdf") \
                else MAX_HTML_BYTES
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    if limit == MAX_PDF_BYTES:
                        raise FetchError("PDF too large")
                    break
            return str(r.url), ctype, bytes(body)
    raise FetchError("Too many redirects.")


# --- analysis ---------------------------------------------------------------------------------

_WORDS = re.compile(r"[a-zà-ÿ]+", re.I)


def language_of(text: str) -> tuple[str, float]:
    words = [w.lower() for w in _WORDS.findall(text)]
    if len(words) < 20:
        return "unknown", 0.0
    nl = sum(w in DUTCH_STOPWORDS for w in words)
    en = sum(w in ENGLISH_STOPWORDS for w in words)
    ratio = nl / max(1, nl + en)
    if nl + en < 8:
        return "unknown", round(ratio, 2)
    return ("nl" if ratio >= 0.7 else "en" if ratio <= 0.3 else "mixed"), round(ratio, 2)


def _count_phrases(phrases: list[str], text: str) -> int:
    return sum(len(re.findall(rf"(?<![\w]){re.escape(p)}(?![\w])", text)) for p in phrases)


def _signals(a: Analysis, text: str, url: str) -> None:
    low = text.lower()
    hay = f"{a.title} {' '.join(a.headings)} {url}".lower()
    a.language, a.dutch_ratio = language_of(text)
    a.word_count = len(_WORDS.findall(text))
    a.stated_levels = stated_levels(a.title, text, url)
    a.estimated = estimate_level(_dutch_sample(text)) if a.language in ("nl", "mixed") else None
    a.blanks = len(BLANK.findall(text))
    a.numbered_items = len(NUMBERED.findall(text))
    a.exercise_words = _count_phrases(EXERCISE_WORDS, low)
    a.has_answer_key = a.has_answer_key or _count_phrases(ANSWER_WORDS, low) > 0
    a.paywall = _count_phrases(PAYWALL_WORDS, low) >= 2 or _count_phrases(LOGIN_WALL, low) > 0
    skills = []
    for skill, words in SKILL_WORDS.items():
        strong = _count_phrases(words, hay)
        weak = _count_phrases(words, low)
        if strong or weak >= 3:
            skills.append(skill)
    if "video" in a.embeds or "audio" in a.embeds:
        skills.append("listening")
    a.skills = list(dict.fromkeys(skills))
    if a.word_count > 250 and a.exercise_words < 2 and not a.interactive_inputs and "reading_text" not in a.formats:
        a.formats.append("reading_text")
    if (a.blanks >= 3 or a.numbered_items >= 5) and "worksheet" not in a.formats:
        a.formats.append("worksheet")
    a.excerpt = re.sub(r"\s+", " ", text).strip()[:1200]


def _dutch_sample(text: str) -> str:
    """Sentences that look Dutch, so English instructions don't skew the estimate."""
    keep = []
    for s in re.split(r"(?<=[.!?])\s+|\n", text):
        words = [w.lower() for w in _WORDS.findall(s)]
        nl = sum(w in DUTCH_STOPWORDS for w in words)
        if nl and nl >= sum(w in ENGLISH_STOPWORDS for w in words):
            keep.append(s if s.rstrip().endswith((".", "!", "?")) else s + ".")
    return " ".join(keep)


def analyze_html(url: str, html: str) -> Analysis:
    a = Analysis(url=url, final_url=url, ok=True, content_type="text/html")
    soup = BeautifulSoup(html, "html.parser")
    a.title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:200]
    desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    a.description = (desc.get("content") or "")[:400] if desc else ""

    # Interactive elements, counted before boilerplate is stripped (forms can live anywhere).
    inputs = soup.find_all("input", attrs={"type": re.compile(r"^(text|radio|checkbox)$", re.I)})
    inputs += soup.find_all(["select", "textarea"])
    search_like = [i for i in inputs if re.search(r"search|zoek|email|newsletter|nieuwsbrief|login|password|comment|reactie|author|captcha",
                                                   " ".join(str(v) for v in i.attrs.values()), re.I)]
    a.interactive_inputs = len(inputs) - len(search_like)
    for tag in soup.find_all(["iframe", "embed", "object", "script", "div"], limit=4000):
        src = " ".join(str(tag.get(k, "")) for k in ("src", "data-src", "data", "class", "data-content-id"))
        for needle, kind in EMBED_HOSTS.items():
            if needle in src.lower() and kind not in a.embeds:
                a.embeds.append(kind)
    if soup.find("audio") or soup.find("source", attrs={"src": re.compile(r"\.(mp3|ogg|wav|m4a)", re.I)}):
        a.embeds.append("audio")
    if soup.find("video"):
        a.embeds.append("video")
    a.embeds = list(dict.fromkeys(a.embeds))
    if {"h5p", "wordwall", "learningapps", "liveworksheets", "quizlet"} & set(a.embeds):
        a.has_answer_key = True  # these tools check answers themselves
    if soup.find(["button", "input"], string=re.compile(r"controleer|nakijken|check|antwoord", re.I)) or \
            soup.find("input", attrs={"value": re.compile(r"controleer|nakijken|check", re.I)}):
        a.has_answer_key = True
    for link in soup.find_all("a", href=True):
        href = link["href"]
        label = link.get_text(" ", strip=True).lower()
        if href.lower().split("?")[0].endswith(".pdf"):
            a.linked_pdfs.append(urljoin(url, href))
        if re.search(r"antwoord|oplossing|sleutel|answer", label + " " + href.lower()):
            a.has_answer_key = True
    a.linked_pdfs = list(dict.fromkeys(a.linked_pdfs))[:10]

    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form[role=search]"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    a.headings = [h.get_text(" ", strip=True)[:120] for h in main.find_all(["h1", "h2", "h3"])][:15]
    text = main.get_text("\n", strip=True)
    a.text = text

    if a.interactive_inputs >= 3 or {"h5p", "wordwall", "learningapps", "quizlet", "liveworksheets", "form",
                                      "kahoot"} & set(a.embeds):
        a.formats.append("interactive")
    if "video" in a.embeds:
        a.formats.append("video")
    if "audio" in a.embeds:
        a.formats.append("audio")
    if a.linked_pdfs:
        a.formats.append("pdf_links")
    _signals(a, text, url)
    return a


def analyze_pdf(url: str, body: bytes) -> Analysis:
    a = Analysis(url=url, final_url=url, ok=True, content_type="application/pdf", formats=["pdf"])
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        meta = reader.metadata or {}
        a.title = str(meta.get("/Title") or "")[:200]
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:15])
    except Exception as exc:  # broken or scanned PDFs are common; keep what we know
        a.error = f"Could not read PDF text: {exc.__class__.__name__}"
        text = ""
    if not a.title:
        first = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 8), "")
        a.title = first[:120]
    a.text = text
    _signals(a, text, url)
    return a


async def analyze_url(client: httpx.AsyncClient, url: str) -> Analysis:
    try:
        final, ctype, body = await fetch(client, url)
    except (FetchError, httpx.HTTPError) as exc:
        return Analysis(url=url, ok=False, error=str(exc) or exc.__class__.__name__)
    if ctype == "application/pdf" or body[:5] == b"%PDF-":
        a = analyze_pdf(final, body)
    elif "html" in ctype or not ctype or body.lstrip()[:1] == b"<":
        a = analyze_html(final, body.decode("utf-8", errors="replace"))
    else:
        return Analysis(url=url, final_url=final, ok=False, content_type=ctype, error=f"Unsupported type {ctype}")
    a.url = url
    a.final_url = final
    return a
