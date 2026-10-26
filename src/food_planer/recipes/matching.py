"""Which imported recipes are worth showing the planner this week.

There are far too many recipes to put them all in the prompt, so a recipe
only makes the cut when it uses something we want to use anyway: a **fresh
item** from the Fridge (use it before it spoils) or a product **on offer** at
the household's shops. Pantry staples never count, not even when on offer:
they are always in the house, and nearly every recipe has an onion in it.

Matching works on the ingredient's *name*, cut out of the recipe's line:
"500 g porre, i ringe" → "porre". Fridge items are found with
:class:`~food_planer.fridge.OnHand` ("Leek" → "porre"). Offers are matched
with the rule the planner uses to tie a Suggestion's ingredient to an offer
(:func:`~food_planer.discounts.offer_for_ingredient`) and graded the same way
(:func:`~food_planer.discounts.match_grade`): a match that isn't 1:1 is kept
but flagged ``review``, shown to the planner as one to check, and counts half.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..discounts import match_grade, offer_for_ingredient
from ..fridge import OnHand

# How many matched recipes go into the prompt, best first, and how many of
# each one's remaining ingredients its prompt line names.
MAX_PROMPT_RECIPES = 40
RECIPE_LINE_OTHERS = 8

# The planner plans dinners, so only recipes filed under one of these
# categories (compared case-insensitively) are candidates. Covers valdemarsro's
# "Aftensmad" and the usual English labels for sites added later.
DINNER_CATEGORIES = frozenset({"aftensmad", "hovedret", "dinner", "main course", "mains"})

# Quantities and units that lead an ingredient line, and words that describe
# rather than name it. Stripped before matching.
_UNITS = frozenset(
    "g gr gram kg ml cl dl l liter tsk spsk stk fed dåse dåser glas pakke pakker "
    "bundt bdt håndfuld håndfulde knsp knivspids skive skiver stykke stykker "
    "bakke bakker pose poser net ds pk store stor små lille mellemstore "
    "ca evt cirka".split()
)
_DESCRIPTIVE = frozenset(
    "frisk friske fint groft revet revne tørret tørrede "
    "finthakket finthakkede grofthakket fintrevet friskkværnet kværnet "
    "økologisk øko blød bløde kold kolde varm varme dryp drys lidt "
    "rød røde grøn grønne gul gule hvid hvide sort sorte "
    "blandet blandede tør tørt naturel".split()
)
# Where the name ends: everything after one of these words is a note about
# it ("smør til stegning", "oliven uden sten", "ansjoser i olie").
_TRAILING = re.compile(r"\b(?:til|à|a|uden|i|på|eller|og|som)\b.*$")
_QUANTITY = re.compile(r"^[\d½¼¾⅓⅔.,/\-–\s]+")


def is_dinner(recipe: dict[str, Any]) -> bool:
    return any(c.lower() in DINNER_CATEGORIES for c in recipe.get("categories", []))


def ingredient_name(line: str) -> str:
    """The ingredient a recipe line names: "500 g porre, i ringe" → "porre".

    Cuts at the first comma, bracket or sentence end (preparation notes) and
    at a trailing note ("til stegning"), drops the leading amount and unit,
    and the descriptive words around the name. A line that is nothing but
    description falls back to what it was.
    """
    text = re.split(r"[,(]|\. ", line.lower(), maxsplit=1)[0]
    text = re.sub(r"\d+\s*%", "", text)  # "cremefraiche 18 %"
    text = _QUANTITY.sub("", text)
    text = _TRAILING.sub("", text)
    words = text.split()
    while words and (words[0].strip(".") in _UNITS or _QUANTITY.fullmatch(words[0])):
        words.pop(0)
    named = [w for w in words if w not in _DESCRIPTIVE]
    return " ".join(named or words).strip(" .")


@dataclass
class RecipeMatch:
    recipe: dict[str, Any]
    # Fridge item name → the recipe ingredient that uses it.
    fresh: dict[str, str] = field(default_factory=dict)
    # One entry per offer used: {"ingredient", "offer", "review"}; ``review``
    # marks a match that isn't 1:1 and needs the model's judgement.
    offers: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


def match_recipes(
    recipes: Iterable[dict[str, Any]],
    on_hand: OnHand,
    offers: list[dict[str, Any]],
    limit: int | None = None,
) -> list[RecipeMatch]:
    """The recipes that use a fresh item or an offer, best first.

    An ingredient we already have (a fresh item or a pantry staple) is never
    matched to an offer: there is nothing to buy. Each match is weighted by how
    rare it is across the recipes (inverse document frequency): butter is in
    half of them, so using up the butter says little about a recipe, while
    using up the chicken says a lot. A fresh item counts double an offer, an
    offer still to be reviewed half. Ties keep the site's own order.
    ``offers`` should be food offers.
    """
    recipes = list(recipes)
    offer_cache: dict[str, dict[str, Any] | None] = {}

    def offer_for(name: str) -> dict[str, Any] | None:
        if name not in offer_cache:
            offer = _offer_for_name(name, offers)
            offer_cache[name] = offer and {
                "offer": offer,
                "review": match_grade(name, offer) != "exact",
            }
        return offer_cache[name]

    matches: list[RecipeMatch] = []
    name_counts: Counter[str] = Counter()
    for recipe in recipes:
        match = RecipeMatch(recipe)
        seen_offers: set[str] = set()
        names = {ingredient_name(i["text"]) for i in recipe.get("ingredients", [])} - {""}
        name_counts.update(names)
        for name in sorted(names):
            fresh = on_hand.fresh_items(name)
            for item in fresh:
                match.fresh.setdefault(item, name)
            if fresh or on_hand.is_staple(name):
                continue
            found = offer_for(name)
            if found is not None and found["offer"]["id"] not in seen_offers:
                seen_offers.add(found["offer"]["id"])
                match.offers.append({"ingredient": name, **found})
        if match.fresh or match.offers:
            matches.append(match)

    total = len(recipes)
    item_counts = Counter(item for m in matches for item in m.fresh)

    def rarity(count: int) -> float:
        return math.log((total + 1) / (count + 1)) + 0.1  # never quite zero

    for m in matches:
        m.score = 2 * sum(rarity(item_counts[i]) for i in m.fresh) + sum(
            rarity(name_counts[o["ingredient"]]) * (0.5 if o["review"] else 1)
            for o in m.offers
        )
    matches.sort(key=lambda m: -m.score)  # stable: site order breaks ties
    return matches[:limit] if limit is not None else matches


def match_dinner_recipes(
    recipes: Iterable[dict[str, Any]],
    fridge: dict[str, Any],
    offers: list[dict[str, Any]],
    limit: int | None = None,
) -> list[RecipeMatch]:
    """:func:`match_recipes` over the dinner recipes, fed from the Fridge."""
    return match_recipes(
        (r for r in recipes if is_dinner(r)), OnHand.from_fridge(fridge), offers, limit
    )


def recipe_refs(matches: list[RecipeMatch]) -> dict[str, RecipeMatch]:
    """Short per-run references (``r1``, ``r2``…) → match, in ranked order,
    so the model can say which recipe a Suggestion came from."""
    return {f"r{i}": m for i, m in enumerate(matches, start=1)}


def recipe_prompt_line(
    ref: str, match: RecipeMatch, offer_ids: dict[str, str] | None = None
) -> str:
    """One matched recipe as a compact prompt line, led by its ``[ref]``: what
    it uses up, what it saves on (with the offer's ``[id]`` when the offer is
    in the prompt's list), the uncertain offers to check, and the rest of its
    ingredients by name only. ``offer_ids`` maps a Tjek offer id to its ref."""
    recipe = match.recipe
    offer_ids = offer_ids or {}
    used = set(match.fresh.values()) | {o["ingredient"] for o in match.offers}
    parts = [f"- [{ref}] {recipe['title']}"]
    if match.fresh:
        parts.append("uses up: " + ", ".join(dict.fromkeys(match.fresh.values())))

    def where(offer: dict[str, Any]) -> str:
        cited = offer_ids.get(offer["id"])
        return f"{offer['shop']} [{cited}]" if cited else offer["shop"]

    sure = [o for o in match.offers if not o["review"]]
    check = [o for o in match.offers if o["review"]]
    if sure:
        parts.append(
            "on offer: " + ", ".join(f"{o['ingredient']} ({where(o['offer'])})" for o in sure)
        )
    if check:
        parts.append(
            "check offer: "
            + ", ".join(
                f"{o['ingredient']} ≈ \"{o['offer']['item_name']}\" ({where(o['offer'])})"
                for o in check
            )
        )
    others = dict.fromkeys(
        name
        for name in (ingredient_name(i["text"]) for i in recipe.get("ingredients", []))
        if name and name not in used
    )
    if others:
        # Enough for the model to recognise the dish; not the whole list.
        parts.append("also: " + ", ".join(list(others)[:RECIPE_LINE_OTHERS]))
    return " — ".join(parts)


def minutes(text: str | None) -> int | None:
    """A recipe's human-readable time in minutes: "30 min." → 30,
    "1 time og 15 min." → 75, "1½ time" → 90, "2 dage" → 2880. ``None`` when
    unreadable (valdemarsro has one recipe whose time reads "Array")."""
    if not text:
        return None
    text = text.lower().replace("½", ".5").replace(",", ".")
    total = 0.0
    for pattern, scale in ((r"dage?\b", 24 * 60), (r"(?:timer|time|t\b|h\b)", 60), (r"(?:min|m\b)", 1)):
        found = re.search(r"(\d+(?:\.\d+)?|\.5)\s*" + pattern, text)
        if found:
            total += float(found.group(1)) * scale
    return round(total) or None


def recipe_link(recipe: dict[str, Any]) -> dict[str, Any]:
    """What a Suggestion keeps of the recipe it came from: enough to show the
    thumbnail, the real times and servings, and link to the full recipe."""
    return {
        "title": recipe["title"],
        "url": recipe["url"],
        "source": recipe.get("source"),
        "thumbnail": recipe.get("thumbnail") or recipe.get("image"),
        "totalTime": recipe.get("total_time"),
        "workTime": recipe.get("work_time"),
        "servings": recipe.get("servings"),
    }


# A rough price for a recipe, in DKK: what each ingredient still to buy costs
# on offer this week, or this much when it isn't on offer. Anything we have
# costs nothing. Deliberately crude — a pack price, not the share a recipe uses.
UNPRICED_ITEM_KR = 20.0

_LEADING_AMOUNT = re.compile(
    r"^(?:ca\.?\s*)?[\d½¼¾⅓⅔][\d½¼¾⅓⅔.,/\-–\s]*"
    r"(?:(?:" + "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True)) + r")\b\.?)?",
    re.IGNORECASE,
)


def rough_cost(ingredients: list[dict[str, Any]], discounts: list[dict[str, Any]]) -> int:
    """The rough price of a list of shopping items (``name``, ``have``) given
    the offers tied to them (``matchedIngredient``, ``price``): each offer's
    price, :data:`UNPRICED_ITEM_KR` for anything else to buy, nothing for what
    we have. Used for recipe cards and recipe dishes alike, so the same recipe
    costs the same on the Inspiration screen and on the plan."""
    priced = {d.get("matchedIngredient"): d.get("price") for d in discounts}
    return round(
        sum(priced.get(i["name"]) or UNPRICED_ITEM_KR for i in ingredients if not i.get("have"))
    )


def parse_ingredient_line(line: str) -> dict[str, str]:
    """A recipe line as a shopping item: "500 g porre, i ringe" →
    ``{"name": "porre", "quantity": "500 g"}``. The amount and unit lead the
    line; the name runs to the first comma or bracket (preparation notes).
    A line without an amount ("salt og peber") keeps it all as the name."""
    text = " ".join(line.split())
    found = _LEADING_AMOUNT.match(text)
    quantity = found.group(0).strip() if found else ""
    rest = text[found.end():] if found else text
    name = re.split(r"[,(]", rest, maxsplit=1)[0].strip(" .") or rest.strip()
    return {"name": name, "quantity": quantity}


def first_paragraph(text: str | None) -> str:
    return (text or "").split("\n\n", 1)[0].strip()


def recipe_items(recipe: dict[str, Any], on_hand: OnHand) -> list[dict[str, Any]]:
    """Every ingredient line of a recipe, parsed and marked: the line itself
    (``text``, ``group``), the shopping item (``name``, ``quantity``) and
    whether we have it (``have``)."""
    items = []
    for ingredient in recipe.get("ingredients", []):
        parsed = parse_ingredient_line(ingredient["text"])
        items.append(
            {
                "text": ingredient["text"],
                "group": ingredient.get("group"),
                **parsed,
                "have": on_hand.kind(ingredient_name(ingredient["text"])),
            }
        )
    return items


def recipe_card(
    recipe: dict[str, Any], match: RecipeMatch | None, on_hand: OnHand
) -> dict[str, Any]:
    """A recipe shaped like a Suggestion card: parsed, marked ingredients, the
    offers it uses (denormalized like a Suggestion's discounts, each tied to
    its ingredient's item name — 1:1 matches only), how many ingredients are in
    the fridge, the pantry or on offer, and a rough price."""
    from ..discounts import denormalize_discount

    items = recipe_items(recipe, on_hand)
    by_core = {o["ingredient"]: o for o in (match.offers if match else [])}
    discounts: list[dict[str, Any]] = []
    for item in items:
        if item["have"]:
            continue
        found = by_core.pop(ingredient_name(item["text"]), None)
        # Only 1:1 matches: a card has no model to review a guess ("K-Salat
        # bearnaisesauce" for lettuce), and its offers travel on to the
        # shopping list. The planner still sees the guesses, marked to check.
        if found is None or found["review"]:
            continue
        discount = denormalize_discount(found["offer"], item["name"], "name")
        discounts.append(discount)
    return {
        **{k: recipe.get(k) for k in ("source", "url", "title", "thumbnail", "servings", "total_time", "categories")},
        "description": first_paragraph(recipe.get("description")),
        "ingredients": items,
        "discounts": discounts,
        "estimatedCost": rough_cost(items, discounts),
        "prepTimeMinutes": minutes(recipe.get("total_time")),
        "counts": {
            "fresh": sum(1 for i in items if i["have"] == "fresh"),
            "staple": sum(1 for i in items if i["have"] == "staple"),
            "offers": len(discounts),
        },
        "recipe": recipe_link(recipe),
    }


def _offer_for_name(name: str, offers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The offer for an ingredient name. Only headings containing the name's
    longest word are passed on, which keeps the regex matching cheap."""
    key = max(name.split(), key=len)
    pool = [o for o in offers if key in (o.get("item_name") or "").lower()]
    return offer_for_ingredient(name, pool) if pool else None
