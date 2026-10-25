"""Import recipes from recipe websites into local JSON.

``food-planer-recipes valdemarsro`` scrapes every recipe on valdemarsro.dk into
``data/recipes/valdemarsro.json``. Adding a site means adding an adapter under
``sites/`` (see ``sites/base.py``) and registering it in ``sites/__init__.py``.
"""

from __future__ import annotations

import argparse
import os

from .model import Ingredient, Recipe, RecipeRef
from .scraper import load_site_file, recipes_dir, scrape
from .sites import SITES

__all__ = ["Ingredient", "Recipe", "RecipeRef", "SITES", "load_all_recipes", "main", "scrape"]


def load_all_recipes(data_dir: str | os.PathLike[str]) -> list[dict]:
    """Every stored recipe from every site file, in file order."""
    directory = recipes_dir(data_dir)
    if not directory.is_dir():
        return []
    return [
        recipe
        for path in sorted(directory.glob("*.json"))
        for recipe in load_site_file(path).get("recipes", [])
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape recipes into data/recipes/<site>.json")
    parser.add_argument("site", choices=sorted(SITES), help="which website to scrape")
    parser.add_argument(
        "--data-dir", default=os.environ.get("FOOD_PLANNER_DATA_DIR", "data")
    )
    parser.add_argument("--limit", type=int, help="only the first N recipes (for testing)")
    parser.add_argument("--workers", type=int, default=4, help="parallel page fetches")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds before each fetch")
    parser.add_argument(
        "--refresh", action="store_true", help="re-fetch recipes already stored"
    )
    args = parser.parse_args(argv)
    scrape(
        SITES[args.site],
        args.data_dir,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        refresh=args.refresh,
    )
