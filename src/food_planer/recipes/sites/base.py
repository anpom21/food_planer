"""The contract a recipe website adapter fulfils, and the default parser.

Supporting a new website means writing one adapter with two jobs:

- ``discover`` — list every recipe on the site (title, URL, thumbnail);
- ``parse``    — turn one recipe page's HTML into a :class:`Recipe`.

:class:`SchemaOrgSite` does ``parse`` generically from the page's schema.org
data, so a well-behaved site often needs nothing but ``discover``. Override
``refine`` to patch what the generic parse gets wrong or leaves out.
"""

from __future__ import annotations

from typing import Iterator, Protocol

import httpx
from bs4 import BeautifulSoup

from ..model import Ingredient, Recipe, RecipeRef
from ..schema_org import SchemaRecipe, parse_schema_recipe


class SiteAdapter(Protocol):
    name: str

    def discover(self, http: httpx.Client) -> Iterator[RecipeRef]: ...

    def parse(self, html: str, ref: RecipeRef) -> Recipe | None: ...


class SchemaOrgSite:
    """An adapter whose ``parse`` reads schema.org JSON-LD or microdata."""

    name: str = ""

    def discover(self, http: httpx.Client) -> Iterator[RecipeRef]:
        raise NotImplementedError

    def parse(self, html: str, ref: RecipeRef) -> Recipe | None:
        """``None`` when the page holds no recipe (an article, a guide)."""
        soup = BeautifulSoup(html, "html.parser")
        schema = parse_schema_recipe(soup)
        if schema is None or not schema.ingredients:
            return None
        recipe = Recipe(
            source=self.name,
            url=ref.url,
            title=ref.title or schema.name or ref.url,
            thumbnail=ref.thumbnail or schema.image,
            image=schema.image or ref.thumbnail,
            description=schema.description,
            ingredients=[Ingredient(text=line) for line in schema.ingredients],
            instructions=schema.instructions,
            servings=schema.recipe_yield,
            total_time=schema.total_time,
            work_time=schema.prep_time or schema.cook_time,
            categories=schema.categories,
            keywords=schema.keywords,
            author=schema.author,
            published=schema.published or _meta(soup, "article:published_time"),
            source_id=ref.source_id,
        )
        return self.refine(recipe, soup, schema)

    def refine(self, recipe: Recipe, soup: BeautifulSoup, schema: SchemaRecipe) -> Recipe:
        return recipe


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop})
    return tag.get("content") if tag else None
