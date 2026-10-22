# Dutch Exercise Finder (MCP)

An MCP server that lets an agent find good, existing exercises for learners of
Dutch (NT2) by theme and CEFR level. It doesn't generate exercises. It finds
them, opens each page, and checks whether it really is an exercise at the right
level on the right topic.

| Tool | What it does |
| --- | --- |
| `find_exercises` | Takes a theme and a level, plus optional skills, formats, `nl`/`be` variant and free-only. Returns a ranked list with score, level fit, skills, formats, answer key, reasons and warnings. |
| `inspect_exercise` | Grades one URL (HTML or PDF) in detail and can score it against a level and theme. |
| `rate_exercise` | Records 1-5 feedback after a learner used something. A 1 hides the URL from future searches; a 4 or 5 boosts it and its site. |
| `list_sources` | The curated catalog, filtered by level, skill or variant. |
| `list_themes` | Everyday topics and grammar points with their Dutch search terms. |
| `list_ratings` | Recent ratings. |

## How it finds and grades exercises

```
theme + level ──► resolve  "at the doctor" → gezondheid: huisarts, dokter, apotheek…
                           "Staatsexamen I" → B1
             ──► pick curated sources covering the level (data/sources.json)
             ──► search    site-restricted web queries on the best sources
                           (English terms for English-language sites; no level for grammar)
                           + open-web queries
                           + the sites' own search pages (no API key needed)
                           + source APIs (NedBox) with structured level/skill data
             ──► fetch & analyse the top ~14 candidates (HTML or PDF), max 4 per site
             ──► follow theme links one level down from on-theme hub pages
             ──► score 0-100, dedupe mirrors, max 3 per source, rank
```

Each page gets a score from 0 to 100, built from these parts:

- **Source reputation (up to 25):** the catalog quality, 1-5. Unknown sites get 8, and user-made platforms get a warning. Your own ratings move it up or down by up to 12.
- **Level fit (-15 to +20):** what the page says about its level, from the title, the URL (`/a2-…`) or phrases like "niveau B1", "A1-A2" or "Staatsexamen II". Level menus are ignored. When the page states no level, a rough Flesch-Douma estimate of the Dutch text is used instead.
- **Theme fit (up to 20):** theme keywords in the title, URL and headings count most, then keywords in the body.
- **Is it an exercise? (up to 20):** H5P, Wordwall, LearningApps or form inputs; exercise wording ("vul in", "kies het juiste"…); blanks and numbered items. Exam sites count too. A text with no tasks is marked as reading material.
- **Answer key or feedback (+6):** an answer link, a "controleer" button, or a tool that checks answers itself (H5P and similar).
- **Requested skills and formats:** extra points for a match.
- **Penalties:** paywall or login, pages that are almost all English, home pages, search-results pages and forum threads. Pages with no sign of the theme, and overview or brochure pages, are capped at 45. A page that couldn't be fetched is scored from its search snippet only, capped at 55, and flagged.

The curated catalog has 20 sources. They include NT2 TaalMenu, Oefenen.nl
(including Taalklas.nl), NedBox, the official Staatsexamens Nt2, DUO and CNaVT
practice exams, Learn Dutch, DutchGrammar.com, Beter Spellen, Easy Dutch,
Wablieft and Jeugdjournaal. KlasCement and Wikiwijs are in too, with a lower
quality score. Paid platforms and user-made platforms are listed but excluded
by default. To add or override sources, set `SOURCES_FILE` to a JSON file with
the same shape.

## Run it

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/dutch-exercises-mcp                     # stdio (default)
.venv/bin/dutch-exercises-mcp --transport http    # http://127.0.0.1:8010/mcp
```

Claude Code / Claude Desktop:

```json
{
  "mcpServers": {
    "dutch-exercises": {
      "command": "/path/to/dutch-exercises/.venv/bin/dutch-exercises-mcp",
      "env": { "BRAVE_API_KEY": "…" }
    }
  }
}
```

### Search backends

Without an API key the server uses DuckDuckGo's HTML endpoint. It works, but it
rate-limits after a few queries. Results then come from the curated sites' own
search pages, and the response includes an `errors` entry saying so. For
reliable results, set one of these (the first one set wins):

| Variable | Backend |
| --- | --- |
| `BRAVE_API_KEY` | Brave Search API |
| `TAVILY_API_KEY` | Tavily |
| `SEARXNG_URL` | A self-hosted SearXNG instance (`format=json` enabled) |

You can force a backend with `SEARCH_PROVIDER=brave|tavily|searxng|duckduckgo`.

### Other settings

| Variable | Default | |
| --- | --- | --- |
| `DATA_DIR` | `~/.dutch-exercises` | SQLite cache (pages 7 days, searches 2 days) and ratings |
| `SOURCES_FILE` | | Extra or overriding catalog entries |
| `MCP_TOKEN` | | Bearer token for HTTP. Required to listen on a non-local interface. |
| `MCP_ALLOWED_HOSTS` | | Enables DNS-rebinding protection for these Host headers |

The server only fetches public http(s) URLs. Every redirect hop is checked
against private, loopback and link-local addresses.

## Tests

```bash
.venv/bin/pytest -q                                   # offline; no network needed
.venv/bin/python scripts/debug_find.py "de of het" A1  # live: every candidate with score and warnings
```

## Limits

- The level estimate measures how hard the text is to read, not how hard the
  exercise is. Treat `level.fit: "estimated*"` as a hint.
- NedBox is JavaScript-only, so it's searched through its public JSON API
  instead (`connectors.py`). Its levels come from NedBox's own mapping: one
  star ≈ A1, two ≈ A2, three ≈ B1+. Its exercise details need a login, so a
  grammar term that NedBox matched inside an item is shown but not counted as
  on-theme.
- Other JavaScript-built pages (parts of Oefenen.nl) show little text to the
  fetcher. They rank on source reputation, title and URL, and get a "very
  little content" warning.
- DutchGrammar.com and Quizlet block automated fetches, so they are scored from
  snippets.
