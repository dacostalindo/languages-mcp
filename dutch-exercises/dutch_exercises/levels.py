"""CEFR levels: parsing what an agent or a page says, and a rough difficulty estimate for Dutch text."""

from __future__ import annotations

import re

LEVELS = ["A0", "A1", "A2", "B1", "B2", "C1", "C2"]

# Phrases learners, teachers and Dutch exam bodies use for a level. Checked longest first.
ALIASES = {
    "alfabetisering": "A0", "alfa": "A0", "absolute beginner": "A0", "pre-a1": "A0", "analfabeet": "A0",
    "beginner": "A1", "beginners": "A1", "starter": "A1", "breakthrough": "A1",
    "elementary": "A2", "basis": "A2", "waystage": "A2", "inburgering": "A2", "inburgeringsexamen": "A2",
    "pre-intermediate": "A2",
    "intermediate": "B1", "threshold": "B1", "gemiddeld": "B1", "staatsexamen i": "B1", "programma i": "B1",
    "staatsexamen 1": "B1", "programma 1": "B1", "nt2 i": "B1",
    "upper intermediate": "B2", "upper-intermediate": "B2", "vantage": "B2", "gevorderd": "B2",
    "staatsexamen ii": "B2", "programma ii": "B2", "staatsexamen 2": "B2", "programma 2": "B2", "nt2 ii": "B2",
    "advanced": "C1", "vergevorderd": "C1", "staatsexamen iii": "C1", "programma iii": "C1",
    "staatsexamen 3": "C1", "programma 3": "C1",
    "proficiency": "C2", "near native": "C2", "near-native": "C2", "moedertaal": "C2",
}

_CODE = re.compile(r"\b([ABC])\s?([0-2])(?:\.\d)?\+?(?![\w])", re.I)


def parse_level(value: str) -> str | None:
    """Turn 'B1', 'a2+', 'Staatsexamen II', 'beginner'... into a CEFR code, or None."""
    text = value.strip().lower()
    m = _CODE.search(text)
    if m:
        code = f"{m.group(1).upper()}{m.group(2)}"
        if code in LEVELS:
            return code
    for alias in sorted(ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", text):
            return ALIASES[alias]
    return None


def level_index(level: str) -> int:
    return LEVELS.index(level)


def distance(a: str, b: str) -> int:
    return abs(level_index(a) - level_index(b))


def in_range(level: str, lo: str, hi: str) -> bool:
    return level_index(lo) <= level_index(level) <= level_index(hi)


# Level statements on a page: "niveau A2", "A1-A2", "B1+", "Staatsexamen programma II", "NT2 B1".
_LEVEL_CONTEXT = re.compile(
    r"(?:niveau|level|cefr|erk|ERK|nt2|ne?derlands)\W{0,3}((?:[ABC][0-2]\+?)(?:\s?[-/–]\s?[ABC][0-2]\+?)?)",
    re.I,
)
_LEVEL_BARE = re.compile(r"(?<![\w/.-])([ABC][0-2])(?:\s?[-/–]\s?([ABC][0-2]))?\+?(?![\w/.-])")
_LEVEL_URL = re.compile(r"(?:^|[/_\-.])([abc][0-2])(?=$|[/_\-.])", re.I)
_EXAM = re.compile(r"(staatsexamen|programma)\s+(iii|ii|i|1|2|3)\b", re.I)


def _expand(lo: str, hi: str | None) -> list[str]:
    lo = lo.upper()
    hi = (hi or lo).upper()
    if lo not in LEVELS or hi not in LEVELS:
        return []
    a, b = sorted((level_index(lo), level_index(hi)))
    return LEVELS[a:b + 1] if b - a <= 2 else [lo, hi]


def stated_levels(title: str, text: str, url: str = "") -> list[str]:
    """CEFR levels a page claims for itself, strongest evidence first (title, URL, explicit 'niveau X', exams)."""
    found: dict[str, int] = {}

    def add(levels: list[str], weight: int) -> None:
        for lv in levels:
            found[lv] = found.get(lv, 0) + weight

    for m in _LEVEL_BARE.finditer(title):
        add(_expand(m.group(1), m.group(2)), 5)
    for m in _LEVEL_URL.finditer(url.lower()):
        add(_expand(m.group(1), None), 4)
    for m in _LEVEL_CONTEXT.finditer(text):
        if re.match(r"[\s,|]+[ABC][0-2]\b", text[m.end():m.end() + 6]):
            continue  # "Kies je niveau: A0 A1 A2 ..." is a menu, not a statement
        parts = re.split(r"\s?[-/–]\s?", m.group(1).replace("+", ""))
        add(_expand(parts[0], parts[1] if len(parts) > 1 else None), 3)
    for m in _EXAM.finditer(title + " " + text[:4000]):
        lv = parse_level(f"{m.group(1)} {m.group(2)}")
        if lv:
            add([lv], 2)
    # Bare codes in the body are weak evidence: menus often list every level.
    bare = [m for m in _LEVEL_BARE.finditer(text[:6000])]
    if 0 < len({m.group(1).upper() for m in bare}) <= 2:
        for m in bare:
            add(_expand(m.group(1), m.group(2)), 1)
    strong = {lv: w for lv, w in found.items() if w >= 2}
    return sorted(strong, key=lambda lv: (-strong[lv], level_index(lv)))


# --- rough difficulty estimate ------------------------------------------------------------

_SENT = re.compile(r"[.!?]+(?:\s|$)")
_WORD = re.compile(r"[a-zà-ÿ]+(?:[-'][a-zà-ÿ]+)*", re.I)
_SYLL = re.compile(r"(?:ij|aa|ee|oo|uu|ie|oe|eu|ui|ei|ou|au|[aeiouyàáâäèéêëïíîóôöúûü])+", re.I)


def syllables(word: str) -> int:
    return max(1, len(_SYLL.findall(word)))


def estimate_level(text: str) -> dict | None:
    """Flesch-Douma reading ease plus word-length stats, mapped to a CEFR band.

    This measures text difficulty, not exercise difficulty, and is only a hint: short
    sentences full of rare words still score as 'easy'. Needs at least ~120 words.
    """
    words = _WORD.findall(text)
    if len(words) < 120:
        return None
    sentences = max(1, len(_SENT.findall(text)))
    wps = len(words) / sentences
    spw = sum(syllables(w) for w in words) / len(words)
    long_ratio = sum(1 for w in words if len(w) >= 10) / len(words)
    douma = 206.835 - 0.93 * wps - 77 * spw
    # Bands tuned on easy-language news (A2), NT2 B1 readers and newspaper prose (B2-C1).
    if douma >= 85 and wps <= 11:
        level = "A1"
    elif douma >= 72:
        level = "A2"
    elif douma >= 60:
        level = "B1"
    elif douma >= 48:
        level = "B2"
    elif douma >= 35:
        level = "C1"
    else:
        level = "C2"
    if long_ratio > 0.12 and level_index(level) < level_index("B2"):
        level = LEVELS[level_index(level) + 1]
    return {
        "level": level,
        "flesch_douma": round(douma, 1),
        "words_per_sentence": round(wps, 1),
        "long_word_ratio": round(long_ratio, 3),
        "words": len(words),
    }
