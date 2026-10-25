"""valdemarsro.dk — a Danish food blog.

Discovery: the index at ``/opskrifter/`` shows 60 recipes and a "Vis flere
opskrifter" button. The button fetches ``/opskrifter/?ajaxpage=N&pagesize=60``,
which returns ``{"success": true, "data": [{title, id, url, img_url}, ...]}``,
and hides itself once a page comes back with fewer than 60 items. We call that
same endpoint page by page until it does, which loads exactly what clicking
the button until it is gone would.

Parsing: the recipe is schema.org microdata, so the generic parse does most of
the work. ``refine`` adds the ingredient sub-headings (``li.ingredient-header``)
and the human-readable stat row (time, servings, shelf life, freezable).
"""

from __future__ import annotations

from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from ..model import Ingredient, Recipe, RecipeRef
from ..schema_org import SchemaRecipe, clean_text
from .base import SchemaOrgSite

BASE_URL = "https://www.valdemarsro.dk"
PAGE_SIZE = 60

# The stat-row labels that map onto shared Recipe fields; any other label
# ("Holdbarhed", "Kan fryses") is kept verbatim in ``extra``.
STAT_FIELDS = {"Tid i alt": "total_time", "Arbejdstid": "work_time", "Antal": "servings"}


class Valdemarsro(SchemaOrgSite):
    name = "valdemarsro"

    def discover(self, http: httpx.Client) -> Iterator[RecipeRef]:
        page = 1
        while True:
            resp = http.get(
                f"{BASE_URL}/opskrifter/", params={"ajaxpage": page, "pagesize": PAGE_SIZE}
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success"):
                raise RuntimeError(f"valdemarsro index page {page} failed: {body!r}")
            items = body.get("data") or []
            for item in items:
                yield RecipeRef(
                    url=item["url"],
                    title=clean_text(item.get("title")) or item["url"],
                    thumbnail=item.get("img_url") or None,
                    source_id=str(item["id"]) if item.get("id") is not None else None,
                )
            # Same stop rule as the site's own button.
            if len(items) < PAGE_SIZE:
                return
            page += 1

    def refine(self, recipe: Recipe, soup: BeautifulSoup, schema: SchemaRecipe) -> Recipe:
        ingredient_list = soup.select_one("ul.ingredientlist")
        if ingredient_list is not None:
            grouped: list[Ingredient] = []
            group: str | None = None
            for li in ingredient_list.find_all("li"):
                text = clean_text(li.get_text(" "))
                if not text:
                    continue
                if "ingredient-header" in (li.get("class") or []):
                    group = text
                else:
                    grouped.append(Ingredient(text=text, group=group))
            if grouped:
                recipe.ingredients = grouped

        for stat in soup.select(".recipe-stats .recipe-stat"):
            label_el = stat.select_one(".recipe-stat-label")
            label = clean_text(label_el.get_text(" ")) if label_el else None
            value = clean_text(stat.strong.get_text(" ")) if stat.strong else None
            if not label or not value:
                continue
            if label in STAT_FIELDS:
                setattr(recipe, STAT_FIELDS[label], value)
            else:
                recipe.extra[label] = value

        # The intro is several paragraphs of blog prose; keep it, but readable.
        intro = soup.select_one("#recipe-intro")
        if intro is not None:
            paragraphs = [clean_text(p.get_text(" ")) for p in intro.find_all("p")]
            recipe.description = "\n\n".join(p for p in paragraphs if p) or recipe.description

        recipe.categories = list(dict.fromkeys(recipe.categories + recipe.keywords))
        return recipe
