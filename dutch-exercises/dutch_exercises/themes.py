"""Theme taxonomy: everyday topics and grammar points, with the Dutch words exercises use for them."""

from __future__ import annotations

import re
import unicodedata

# key: (label, kind, Dutch keywords (first = best search term), English aliases)
THEMES: dict[str, tuple[str, str, list[str], list[str]]] = {
    # topics
    "kennismaken": ("Introductions & greetings", "topic",
                    ["kennismaken", "jezelf voorstellen", "begroeten", "naam", "afkomst", "land", "taal"],
                    ["introductions", "introduce yourself", "greetings", "greeting", "personal information", "self"]),
    "familie": ("Family", "topic", ["familie", "gezin", "ouders", "kinderen", "broer", "zus", "opa", "oma"],
                ["family", "relatives", "parents", "children"]),
    "wonen": ("Housing", "topic", ["wonen", "huis", "woning", "kamer", "verhuizen", "huur", "buren", "meubels"],
              ["housing", "home", "house", "renting", "neighbours", "neighbors", "moving"]),
    "boodschappen": ("Shopping & groceries", "topic",
                     ["boodschappen", "supermarkt", "winkel", "kopen", "markt", "prijs", "betalen", "kassa"],
                     ["shopping", "groceries", "supermarket", "shop", "store", "buying"]),
    "eten": ("Food, drink & restaurants", "topic",
             ["eten en drinken", "eten", "restaurant", "bestellen", "menu", "koken", "recept", "café"],
             ["food", "drink", "restaurant", "cooking", "recipe", "ordering food", "eating"]),
    "gezondheid": ("Health & the doctor", "topic",
                   ["gezondheid", "huisarts", "dokter", "ziek", "apotheek", "ziekenhuis", "lichaam", "pijn", "medicijn"],
                   ["health", "doctor", "gp", "pharmacy", "hospital", "body", "illness", "sick"]),
    "werk": ("Work & job applications", "topic",
             ["werk", "solliciteren", "sollicitatiegesprek", "vacature", "baan", "collega", "cv", "beroep"],
             ["work", "job", "jobs", "job interview", "applying", "career", "profession", "workplace"]),
    "onderwijs": ("School & studying", "topic", ["school", "onderwijs", "studeren", "cursus", "opleiding", "les"],
                  ["school", "education", "studying", "study", "course"]),
    "vervoer": ("Transport & directions", "topic",
                ["openbaar vervoer", "trein", "bus", "fiets", "station", "de weg vragen", "verkeer", "ov-chipkaart"],
                ["transport", "public transport", "train", "directions", "traffic", "cycling", "bike"]),
    "reizen": ("Travel & holidays", "topic", ["vakantie", "reizen", "hotel", "camping", "reis boeken"],
               ["travel", "holiday", "holidays", "vacation", "hotel", "trip"]),
    "tijd": ("Time, dates & appointments", "topic",
             ["afspraak maken", "klok", "tijd", "dagen", "maanden", "datum", "agenda"],
             ["time", "telling time", "clock", "dates", "appointments", "days of the week", "calendar"]),
    "weer": ("Weather & seasons", "topic", ["het weer", "weer", "seizoenen", "regen", "zon", "temperatuur"],
             ["weather", "seasons", "climate talk"]),
    "vrije_tijd": ("Hobbies, sport & free time", "topic",
                   ["vrije tijd", "hobby", "sport", "uitgaan", "film", "muziek", "lezen"],
                   ["hobbies", "hobby", "free time", "leisure", "sport", "sports", "going out"]),
    "kleding": ("Clothes", "topic", ["kleding", "kleren", "maat", "passen", "kleur"],
                ["clothes", "clothing", "fashion", "colours", "colors"]),
    "instanties": ("Officialdom: municipality, bank, forms", "topic",
                   ["gemeente", "formulier invullen", "bank", "verzekering", "belasting", "post", "brief", "DigiD"],
                   ["bureaucracy", "municipality", "forms", "bank", "insurance", "taxes", "official letters"]),
    "communicatie": ("Phone, email & letters", "topic",
                     ["telefoneren", "bellen", "e-mail schrijven", "brief schrijven", "bericht", "sms"],
                     ["phone call", "telephone", "email", "writing emails", "letters", "messages"]),
    "feesten": ("Holidays & traditions", "topic",
                ["feestdagen", "Sinterklaas", "Koningsdag", "Kerstmis", "verjaardag", "feest", "tradities"],
                ["festivals", "traditions", "celebrations", "birthday", "christmas", "sinterklaas", "kings day"]),
    "maatschappij": ("Society, news & culture (KNM)", "topic",
                     ["maatschappij", "nieuws", "politiek", "samenleving", "cultuur", "KNM", "normen en waarden"],
                     ["society", "news", "politics", "culture", "civic integration", "knm", "current affairs"]),
    "natuur": ("Nature & environment", "topic", ["natuur", "milieu", "klimaat", "afval", "duurzaam", "dieren"],
               ["nature", "environment", "climate", "sustainability", "animals", "recycling"]),
    "gevoelens": ("Feelings & opinions", "topic",
                  ["gevoelens", "mening geven", "emoties", "eens of oneens", "discussiëren"],
                  ["feelings", "emotions", "opinions", "giving your opinion", "debate", "discussion"]),
    # grammar
    "lidwoorden": ("Articles de/het/een", "grammar", ["de of het", "lidwoorden", "het lidwoord"],
                   ["articles", "de het", "definite article", "gender"]),
    "presens": ("Present tense", "grammar", ["tegenwoordige tijd", "presens", "werkwoorden vervoegen", "vervoeging"],
                ["present tense", "conjugation", "verb conjugation", "present simple"]),
    "perfectum": ("Perfect tense (hebben/zijn + voltooid deelwoord)", "grammar",
                  ["voltooide tijd", "perfectum", "voltooid deelwoord", "hebben of zijn"],
                  ["perfect tense", "present perfect", "past participle", "past tense perfect"]),
    "imperfectum": ("Simple past", "grammar", ["verleden tijd", "imperfectum", "onvoltooid verleden tijd", "'t kofschip"],
                    ["simple past", "past tense", "imperfect", "preterite", "kofschip"]),
    "onregelmatig": ("Irregular verbs", "grammar", ["onregelmatige werkwoorden", "sterke werkwoorden"],
                     ["irregular verbs", "strong verbs"]),
    "modaal": ("Modal verbs", "grammar", ["modale werkwoorden", "kunnen", "moeten", "willen", "mogen"],
               ["modal verbs", "modals"]),
    "scheidbaar": ("Separable verbs", "grammar", ["scheidbare werkwoorden"], ["separable verbs", "phrasal verbs"]),
    "woordvolgorde": ("Word order & inversion", "grammar", ["woordvolgorde", "inversie", "zinsbouw"],
                      ["word order", "inversion", "sentence structure", "v2"]),
    "bijzinnen": ("Subordinate clauses", "grammar", ["bijzinnen", "bijzin", "voegwoorden", "omdat", "dat"],
                  ["subordinate clauses", "conjunctions", "relative clauses", "clauses"]),
    "betrekkelijk": ("Relative pronouns (die/dat/wat)", "grammar",
                     ["betrekkelijke voornaamwoorden", "die of dat", "betrekkelijke bijzin"],
                     ["relative pronouns", "die dat"]),
    "er": ("The word 'er'", "grammar", ["het woordje er", "er gebruiken"], ["er", "use of er"]),
    "adjectieven": ("Adjectives & -e ending", "grammar", ["bijvoeglijk naamwoord", "adjectieven", "buigings-e"],
                    ["adjectives", "adjective endings", "adjective declension"]),
    "vergelijken": ("Comparatives & superlatives", "grammar", ["trappen van vergelijking", "vergelijken", "comparatief", "superlatief"],
                    ["comparatives", "superlatives", "comparison"]),
    "voornaamwoorden": ("Pronouns", "grammar",
                        ["persoonlijke voornaamwoorden", "bezittelijke voornaamwoorden", "voornaamwoorden", "wederkerend"],
                        ["pronouns", "possessive pronouns", "personal pronouns", "reflexive verbs", "reflexive"]),
    "meervoud": ("Plurals", "grammar", ["meervoud", "meervoud -en of -s"], ["plurals", "plural"]),
    "verkleinwoord": ("Diminutives", "grammar", ["verkleinwoorden", "verkleinwoord"], ["diminutives", "diminutive"]),
    "negatie": ("Negation: niet/geen", "grammar", ["niet of geen", "ontkenning"], ["negation", "niet geen"]),
    "voorzetsels": ("Prepositions", "grammar", ["voorzetsels", "vaste voorzetsels"], ["prepositions"]),
    "passief": ("Passive voice", "grammar", ["passief", "lijdende vorm", "worden"], ["passive", "passive voice"]),
    "futurum": ("Future (gaan/zullen)", "grammar", ["toekomende tijd", "zullen", "gaan + infinitief"],
                ["future tense", "future", "zullen"]),
    "dt": ("d/t spelling of verbs", "grammar", ["dt-regels", "d of t", "werkwoordspelling"],
           ["dt rules", "verb spelling", "d or t"]),
    "uitspraak": ("Pronunciation", "grammar", ["uitspraak", "klanken", "ui ij eu", "g en ch"],
                  ["pronunciation", "sounds", "phonetics"]),
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def resolve_theme(theme: str) -> dict:
    """Map free text ('groceries', 'het perfectum', 'job interview') to a theme with Dutch search terms.

    Unknown themes are kept as-is so any topic still works; they just get fewer synonyms.
    """
    q = _norm(theme)
    best, best_score = None, 0
    for key, (label, kind, nl, en) in THEMES.items():
        for term in [key, label, *nl, *en]:
            t = _norm(term)
            if not t:
                continue
            if q == t:
                score = 100 + len(t)
            elif re.search(rf"\b{re.escape(t)}\b", q) and len(t) >= 3:
                score = 50 + len(t)
            elif re.search(rf"\b{re.escape(q)}\b", t) and len(q) >= 4:
                score = 30 + len(q)
            else:
                continue
            if score > best_score:
                best, best_score = key, score
    if best is None:
        return {"key": None, "label": theme, "kind": "topic", "search_terms": [theme], "keywords": [theme.lower()]}
    label, kind, nl, en = THEMES[best]
    # Keep the user's own wording too if it isn't one of ours (e.g. "bij de bakker" inside boodschappen).
    # Search in Dutch first. Keep the user's own wording as a keyword, and as a search term only when it
    # looks Dutch (e.g. "bij de bakker"), since NT2 sites don't index English phrases.
    known = any(_norm(t) == q for t in [*nl, *en, label, best])
    extra = [] if known else [theme]
    dutchish = not known and not any(re.search(rf"\b{re.escape(_norm(e))}\b", q) for e in en)
    return {
        "key": best,
        "label": label,
        "kind": kind,
        "search_terms": (extra if dutchish else []) + nl[:3],
        "keywords": [k.lower() for k in dict.fromkeys(extra + nl + en)],
    }


def theme_hits(keywords: list[str], text: str) -> dict[str, int]:
    """Occurrences of each keyword (word-boundary, case-insensitive) in text."""
    low = text.lower()
    hits = {}
    for kw in keywords:
        # Whole words plus common Dutch/English endings: "huis" matches "huisje" but "werk" doesn't
        # match "werkwoorden" and "profession" doesn't match "professioneel".
        n = len(re.findall(rf"(?<![\w]){re.escape(kw.lower())}(?:en|s|e|je|jes|n)?(?![\w])", low))
        if n:
            hits[kw] = n
    return hits


def list_themes() -> list[dict]:
    return [
        {"key": k, "label": label, "kind": kind, "dutch": nl[:4]}
        for k, (label, kind, nl, _en) in THEMES.items()
    ]
