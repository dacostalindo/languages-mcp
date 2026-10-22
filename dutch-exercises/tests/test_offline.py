"""Offline tests: parsing, analysis and scoring on canned pages. No network."""

from dutch_exercises.analyze import analyze_html, language_of
from dutch_exercises.finder import diversify, normalize_url, plan_queries
from dutch_exercises.search import Hit
from dutch_exercises.levels import estimate_level, parse_level, stated_levels
from dutch_exercises.scoring import Request, score
from dutch_exercises.search import build_query, parse_ddg, parse_site_search
from dutch_exercises.sources import is_blocked, select_sources, source_for_url
from dutch_exercises.store import Store
from dutch_exercises.themes import resolve_theme

EXERCISE_PAGE = """<html><head><title>NT2 - A2 - Grammatica - Voltooide tijd - Oefening 1</title>
<meta name="description" content="Oefen de voltooide tijd op niveau A2."></head><body>
<nav>Home A0 A1 A2 B1 B2 Contact</nav>
<main><h1>Voltooide tijd - oefening 1</h1>
<p>Vul in: kies het juiste hulpwerkwoord, hebben of zijn. Daarna controleer je je antwoorden.</p>
<div class="h5p-iframe-wrapper"><iframe src="https://nt2taalmenu.nl/wp-admin/admin-ajax.php?action=h5p_embed&id=12"></iframe></div>
<ol><li>Ik ___ gisteren naar de markt gegaan.</li><li>Wij ___ een boek gelezen.</li>
<li>Zij ___ thuis gebleven.</li><li>Hij ___ zijn huiswerk gemaakt.</li></ol>
</main><footer>Privacy</footer></body></html>"""

READING_TEXT = ("Ik woon in een klein huis in Utrecht. Het huis heeft een tuin. In de tuin staan bloemen. "
                "Mijn buren zijn aardig. Ze hebben een hond. De hond heet Max. Elke dag loop ik met Max. "
                "We gaan naar het park. Daar spelen kinderen. Ik vind het park mooi. ") * 4

NEWSPAPER = ("De minister van Binnenlandse Zaken heeft dinsdag in de Tweede Kamer uitvoerig toegelicht waarom "
             "de voorgestelde decentralisatie van verantwoordelijkheden naar gemeenten volgens het kabinet "
             "noodzakelijk is, ondanks aanhoudende kritiek van oppositiepartijen en belangenorganisaties die "
             "vrezen voor onvoldoende financiering en toenemende bestuurlijke complexiteit. ") * 4


def test_parse_level():
    assert parse_level("B1") == "B1"
    assert parse_level("a2+") == "A2"
    assert parse_level("Staatsexamen II") == "B2"
    assert parse_level("programma I") == "B1"
    assert parse_level("absolute beginner") == "A0"
    assert parse_level("beginner") == "A1"
    assert parse_level("xyz") is None


def test_stated_levels_ignore_level_menus():
    assert stated_levels("Oefening niveau A2", "", "") == ["A2"]
    assert stated_levels("Lezen", "Kies je niveau: A0 A1 A2 B1 B2", "https://x.nl/b1/lezen-3/") == ["B1"]
    assert "B1" in stated_levels("", "Dit is een tekst op niveau B1.", "")


def test_estimate_level_orders_texts():
    easy, hard = estimate_level(READING_TEXT), estimate_level(NEWSPAPER)
    assert easy["level"] in ("A1", "A2") and hard["level"] in ("B2", "C1", "C2")
    assert estimate_level("te kort") is None


def test_resolve_theme_searches_in_dutch():
    t = resolve_theme("at the doctor")
    assert t["key"] == "gezondheid" and t["search_terms"][0] == "gezondheid"
    assert "at the doctor" in t["keywords"]
    assert resolve_theme("perfectum")["kind"] == "grammar"
    assert resolve_theme("bij de bakker")["search_terms"] == ["bij de bakker"]


def test_sources():
    assert source_for_url("https://proefa.nt2taalmenu.nl/x/").id == "nt2taalmenu"
    assert source_for_url("https://www.oefenen.nl/a").id == "oefenen"
    assert source_for_url("https://example.com") is None
    assert is_blocked("https://nl.pinterest.com/pin/1")
    ids = [s.id for s in select_sources("A1", [], "any", free_only=True)]
    assert "staatsexamens" not in ids and "nt2nl" not in ids and "wordwall" not in ids
    assert ids[0] in ("nt2taalmenu", "oefenen", "nedbox", "inburgeren")
    assert "wordwall" in [s.id for s in select_sources("A1", [], "any", True, include_user_generated=True)]


def test_query_planning():
    req = Request(level="A2", theme=resolve_theme("perfectum"))
    plans = plan_queries(req, select_sources("A2", [], "any", True), vetted_only=False)
    assert plans[0][0] == "voltooide tijd A2" and len(plans[0][1]) == 4
    assert any("Dutch grammar" in p[0] for p in plans)
    assert all(p[1] for p in plan_queries(req, select_sources("A2", [], "any", True), vetted_only=True))
    assert build_query("x", ["a.nl", "b.nl"]) == "x (site:a.nl OR site:b.nl)"


def test_parse_ddg():
    html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnt2taalmenu.nl%2Fa%2F'
            '&amp;rut=1">NT2 <b>A1</b></a><a class="result__snippet" href="#">Oefening <b>boodschappen</b></a>')
    [h] = parse_ddg(html, "q")
    assert h.url == "https://nt2taalmenu.nl/a/" and h.title == "NT2 A1" and "boodschappen" in h.snippet


def test_parse_site_search_drops_chrome():
    html = ('<nav><a href="https://nt2taalmenu.nl/menu-item-long/">Menu</a></nav><main>'
            '<h2><a href="https://nt2taalmenu.nl/nt2-a1-lezen-les-3/">A1 lezen les 3</a></h2>'
            '<a href="https://nt2taalmenu.nl/category/a1/">A1</a><a href="https://other.com/abcdefg/">Ext</a></main>')
    hits = parse_site_search(html, "https://nt2taalmenu.nl/?s=x", "q")
    assert [h.url for h in hits] == ["https://nt2taalmenu.nl/nt2-a1-lezen-les-3/"]


def test_analyze_exercise_page():
    a = analyze_html("https://nt2taalmenu.nl/nt2-a2-grammatica-voltooide-tijd-oefening1/", EXERCISE_PAGE)
    assert a.stated_levels == ["A2"]
    assert "interactive" in a.formats and "h5p" in a.embeds
    assert a.has_answer_key and a.blanks >= 3
    assert a.language in ("nl", "mixed", "unknown")
    assert "Home A0 A1" not in a.text  # nav stripped


def test_language():
    assert language_of(READING_TEXT)[0] == "nl"
    assert language_of("The quick brown fox is not what you think, and it was there with the dog for you " * 3)[0] == "en"


def test_scoring_prefers_matching_curated_exercise():
    req = Request(level="A2", theme=resolve_theme("perfectum"))
    url = "https://nt2taalmenu.nl/nt2-a2-grammatica-voltooide-tijd-oefening1/"
    good = score(req, url, "", "", analyze_html(url, EXERCISE_PAGE), source_for_url(url))
    off = score(Request(level="C1", theme=resolve_theme("boodschappen")), url, "", "",
                analyze_html(url, EXERCISE_PAGE), source_for_url(url))
    assert good.score >= 70 and good.level_fit == "exact"
    assert off.score < good.score - 30 and off.level_fit == "off"
    unverified = score(req, "https://example.com/oefening-a2", "Voltooide tijd oefening A2", "", None, None)
    assert unverified.score <= 55 and any("not fetched" in w for w in unverified.warnings)
    search_page = score(req, "https://www.klascement.net/lesmateriaal/?q=voltooide+tijd", "Zoeken", "", None,
                        source_for_url("https://www.klascement.net/"))
    assert any("search results" in w for w in search_page.warnings)


def test_store_ratings(tmp_path):
    s = Store(tmp_path / "s.db")
    u = normalize_url("https://www.Example.com/a/?utm_source=x&id=2#frag")
    assert u == "https://www.example.com/a?id=2"
    s.rate(u, 5)
    s.rate(u, 3)
    assert s.rating_of(u) == (4.0, 2)
    assert s.domain_rating("example.com")[1] == 2
    s.put_page(u, {"x": 1})
    assert s.get_page(u) == {"x": 1}


def test_diversify_gives_other_sites_a_turn():
    hits = [Hit(f"https://nt2taalmenu.nl/les-{i}/", "", "", "q") for i in range(10)]
    hits += [Hit("https://nedbox.be/x/abc", "", "", "q"), Hit("https://oefenen.nl/a/b", "", "", "q")]
    picked = [h.url for h in diversify(hits, 6)]
    assert "https://nedbox.be/x/abc" in picked and "https://oefenen.nl/a/b" in picked
    assert sum("nt2taalmenu" in u for u in picked) == 4


def test_info_pages_on_exam_sites_rank_low():
    req = Request(level="B1", theme=resolve_theme("wonen"))
    info = "<html><head><title>Inschrijven voor een examen - CNaVT</title></head><body><main>" + \
           "<p>Schrijf je in voor het examen op niveau B1. Neem contact op met een exameninstelling.</p>" * 10 + \
           "</main></body></html>"
    url = "https://cnavt.org/inschrijven"
    s = score(req, url, "", "", analyze_html(url, info), source_for_url(url))
    assert s.score < 40 and any("overview" in w or "no exercise" in w for w in s.warnings)


def test_login_wall_detected():
    html = ("<html><head><title>De of het: Reeks 1 - Interactieve oefening</title></head><body><main>"
            "<p>Test je kennis van de lidwoorden. Meld aan of registreer om dit leermiddel volledig te bekijken.</p>"
            "</main></body></html>")
    assert analyze_html("https://www.klascement.net/oefeningen/1/x/", html).paywall
