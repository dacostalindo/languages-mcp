"""Print every checked candidate for a search, with score, warnings and reasons. Usage: debug_find.py THEME LEVEL [variant]"""
import asyncio
import logging
import sys

from dutch_exercises.finder import Finder
from dutch_exercises.levels import parse_level
from dutch_exercises.scoring import Request
from dutch_exercises.store import Store
from dutch_exercises.themes import resolve_theme

logging.basicConfig(level=logging.ERROR)


async def main(theme, level, variant="any"):
    req = Request(level=parse_level(level), theme=resolve_theme(theme))
    print("theme:", req.theme["key"], req.theme["search_terms"])
    r = await Finder(Store()).find(req, variant=variant, max_results=20, inspect_limit=20)
    print("queries:", *r["queries"], sep="\n  ")
    print("errors:", r.get("errors"), "| seen", r["candidates_seen"], "checked", r["candidates_checked"])
    for x in r["results"]:
        print(f'{x["score"]:>3} {x["source"][:18]:<18} {x["title"][:60]:<60} {x["url"][:90]}')
        print(f'      level={x["level"]} formats={x["formats"]} warn={x["warnings"]}')


asyncio.run(main(*sys.argv[1:]))
