"""Generic extraction of a schema.org ``Recipe`` from a recipe page.

Most recipe websites publish the recipe in one of two standard forms so search
engines can read it: a JSON-LD ``<script>`` block, or microdata (``itemprop``
attributes on the visible HTML). :func:`parse_schema_recipe` tries JSON-LD
first and falls back to microdata. Either way it returns the same flat
:class:`SchemaRecipe`, which a site adapter then refines with whatever the
site does differently.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass
class SchemaRecipe:
    name: str | None = None
    description: str | None = None
    image: str | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    recipe_yield: str | None = None
    total_time: str | None = None
    cook_time: str | None = None
    prep_time: str | None = None
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    author: str | None = None
    published: str | None = None


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace (including non-breaking spaces); empty → ``None``."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return text or None


def split_list(value: str | None) -> list[str]:
    """Split a comma-separated schema.org field ("Suppe, Vegetar")."""
    if not value:
        return []
    return [part for part in (clean_text(p) for p in value.split(",")) if part]


def parse_schema_recipe(soup: BeautifulSoup) -> SchemaRecipe | None:
    return _from_json_ld(soup) or _from_microdata(soup)


# --- JSON-LD ---------------------------------------------------------------


def _is_recipe(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "Recipe" in kinds


def _find_recipe_node(data: Any) -> dict | None:
    """Depth-first search for a ``Recipe`` in a JSON-LD document (``@graph`` included)."""
    if _is_recipe(data):
        return data
    children = data.values() if isinstance(data, dict) else data if isinstance(data, list) else []
    for child in children:
        found = _find_recipe_node(child)
        if found:
            return found
    return None


def _first_str(value: Any) -> str | None:
    """Reduce a JSON-LD value that may be a string, list or object to one string."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list) and value:
        return _first_str(value[0])
    if isinstance(value, dict):
        return _first_str(value.get("url") or value.get("name") or value.get("@id"))
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return split_list(value)
    if isinstance(value, list):
        return [s for s in (_first_str(v) for v in value) if s]
    return []


def _instruction_steps(value: Any) -> list[str]:
    """Flatten ``recipeInstructions``: a string, ``HowToStep``s, or ``HowToSection``s."""
    if isinstance(value, str):
        soup = BeautifulSoup(value, "html.parser")
        parts = [clean_text(p.get_text(" ")) for p in soup.find_all(["p", "li"])]
        parts = [p for p in parts if p] or [clean_text(soup.get_text(" "))]
        return [p for p in parts if p]
    if isinstance(value, list):
        return [step for item in value for step in _instruction_steps(item)]
    if isinstance(value, dict):
        if "itemListElement" in value:
            return _instruction_steps(value["itemListElement"])
        return _instruction_steps(value.get("text") or value.get("name") or "")
    return []


def _from_json_ld(soup: BeautifulSoup) -> SchemaRecipe | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        node = _find_recipe_node(data)
        if not node:
            continue
        return SchemaRecipe(
            name=_first_str(node.get("name")),
            description=_first_str(node.get("description")),
            image=_first_str(node.get("image")),
            ingredients=[s for s in (clean_text(i) for i in node.get("recipeIngredient", [])) if s],
            instructions=_instruction_steps(node.get("recipeInstructions")),
            recipe_yield=_first_str(node.get("recipeYield")),
            total_time=_first_str(node.get("totalTime")),
            cook_time=_first_str(node.get("cookTime")),
            prep_time=_first_str(node.get("prepTime")),
            categories=_str_list(node.get("recipeCategory")),
            keywords=_str_list(node.get("keywords")),
            author=_first_str(node.get("author")),
            published=_first_str(node.get("datePublished")),
        )
    return None


# --- Microdata -------------------------------------------------------------


def _own_props(scope: Tag, name: str) -> list[Tag]:
    """Elements carrying ``itemprop=name`` that belong to ``scope`` itself.

    A property inside a nested ``itemscope`` (the author's ``name``, say)
    belongs to that nested item, not to the recipe, so it is skipped.
    """
    found = []
    for el in scope.find_all(attrs={"itemprop": name}):
        parent = el.parent
        while parent is not None and parent is not scope and not parent.has_attr("itemscope"):
            parent = parent.parent
        if parent is scope:
            found.append(el)
    return found


def _prop_value(el: Tag) -> str | None:
    if el.has_attr("content"):
        return clean_text(el["content"])
    if el.name in ("img", "source") and el.has_attr("src"):
        return el["src"]
    if el.name in ("a", "link") and el.has_attr("href"):
        return el["href"]
    if el.name == "time" and el.has_attr("datetime"):
        return el["datetime"]
    return clean_text(el.get_text(" "))


def _from_microdata(soup: BeautifulSoup) -> SchemaRecipe | None:
    scope = soup.find(attrs={"itemtype": re.compile(r"schema\.org/Recipe$", re.I)})
    if not isinstance(scope, Tag):
        return None

    def first(name: str) -> str | None:
        for el in _own_props(scope, name):
            value = _prop_value(el)
            if value:
                return value
        return None

    def every(name: str) -> list[str]:
        return [v for v in (_prop_value(el) for el in _own_props(scope, name)) if v]

    instructions: list[str] = []
    for block in _own_props(scope, "recipeInstructions"):
        steps = [clean_text(p.get_text(" ")) for p in block.find_all(["p", "li"])]
        steps = [s for s in steps if s] or [_prop_value(block)]
        instructions.extend(s for s in steps if s)

    author = next(iter(_own_props(scope, "author")), None)
    return SchemaRecipe(
        name=first("name"),
        description=first("description"),
        image=first("image"),
        ingredients=every("recipeIngredient") or every("ingredients"),
        instructions=instructions,
        recipe_yield=first("recipeYield"),
        total_time=first("totalTime"),
        cook_time=first("cookTime"),
        prep_time=first("prepTime"),
        categories=[c for v in every("recipeCategory") for c in split_list(v)],
        keywords=[k for v in every("keywords") for k in split_list(v)],
        author=(_prop_value(author.find(attrs={"itemprop": "name"}) or author) if author else None),
        published=first("datePublished"),
    )
