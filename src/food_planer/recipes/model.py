"""The shape of one scraped recipe, shared by every site adapter.

Every adapter fills the same :class:`Recipe`, so the stored JSON and the
``/api/recipes`` response look the same whichever website a recipe came from.
Site-specific facts that have no common field (valdemarsro's "Kan fryses",
say) go in ``extra`` rather than growing the shared shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RecipeRef:
    """A recipe found on a site's index page, before its own page is fetched."""

    url: str
    title: str
    thumbnail: str | None = None
    source_id: str | None = None


@dataclass
class Ingredient:
    """One ingredient line, as written on the page.

    ``group`` is the sub-heading the line sits under ("Til servering"), or
    ``None`` for the recipe's main list.
    """

    text: str
    group: str | None = None


@dataclass
class Recipe:
    source: str
    url: str
    title: str
    thumbnail: str | None = None
    image: str | None = None
    description: str | None = None
    ingredients: list[Ingredient] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    servings: str | None = None
    total_time: str | None = None
    work_time: str | None = None
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    author: str | None = None
    published: str | None = None
    source_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    scraped_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recipe:
        data = dict(data)
        data["ingredients"] = [Ingredient(**i) for i in data.get("ingredients", [])]
        return cls(**data)
