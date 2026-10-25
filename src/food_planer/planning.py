"""The planning pass: prompt composition, the strict output schema, and model
config (issue #23, spec.md → "LLM contract").

Everything here is internal — it is reached through ``POST /api/planning-runs``
and tested through that seam. The two exceptions the spec pins directly are the
strict JSON schema and the config-driven model name, so those are plain pure
functions callable on their own.
"""

from __future__ import annotations

import copy
import os
import re
from typing import Any

from .discounts import offer_line
from .fridge import fridge_prompt_values
from .recipes.matching import RecipeMatch, recipe_prompt_line, recipe_refs

# OpenAI's cheapest Structured-Outputs-capable model at time of writing. The
# spec insists this be config, not a literal, so the spec doesn't go stale as
# models turn over — override with FOOD_PLANNER_OPENAI_MODEL.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def resolve_model() -> str:
    """The planner model name, from config with a sensible cheap default."""
    return os.environ.get("FOOD_PLANNER_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL


# --- The strict JSON schema the Responses API enforces ----------------------
# Strict mode rules: the root is an object (not a bare array); every object sets
# additionalProperties:false and lists *every* property in "required"; an
# optional field is a nullable union (e.g. ["string", "null"]), never omitted.

_INGREDIENT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "quantity": {"type": "string"},
    },
    "required": ["name", "quantity"],
}

# The model only points at an offer from the prompt's list by its short [id]
# and names the ingredient it covers; the backend swaps in the real offer
# (price, image, dates), so nothing about an offer is ever made up.
_DISCOUNT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "offerId": {"type": "string"},
        "matchedIngredient": {"type": ["string", "null"]},
    },
    "required": ["offerId", "matchedIngredient"],
}

_SUGGESTION = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "ingredients": {"type": "array", "items": _INGREDIENT},
        "estimatedCost": {"type": "number"},
        "prepTimeMinutes": {"type": "integer"},
        # null means an unknown dish the model invented; a string is a Dish id.
        "sourceDish": {"type": ["string", "null"]},
        # The [r…] id of the imported recipe a suggestion is based on, or null.
        # The backend swaps in the recipe's link, thumbnail and real times.
        "sourceRecipe": {
            "type": ["string", "null"],
            "description": (
                "The [r…] id of the recipe from the prompt's recipe list this "
                "dish is based on, or null if it isn't based on one."
            ),
        },
        # References into this run's offers; denormalized by the backend.
        "discounts": {
            "type": "array",
            "description": (
                "Every offer from the prompt's offer list this dish uses: one "
                "entry per offer, with the offer's [id] as offerId and the "
                "ingredient it covers. Empty only if it uses none."
            ),
            "items": _DISCOUNT,
        },
    },
    "required": [
        "title",
        "description",
        "ingredients",
        "estimatedCost",
        "prepTimeMinutes",
        "sourceDish",
        "sourceRecipe",
        "discounts",
    ],
}

_DAY = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "day": {"type": "integer"},
        "suggestions": {"type": "array", "items": _SUGGESTION},
    },
    "required": ["day", "suggestions"],
}

_PLAN = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"days": {"type": "array", "items": _DAY}},
    "required": ["days"],
}


def planning_json_schema(
    days: int | None = None, suggestions_per_day: int | None = None
) -> dict[str, Any]:
    """The root schema — an object with a nested ``days`` array, strict-clean.

    Given the run's numbers, both arrays are pinned to exactly that length with
    ``minItems``/``maxItems`` (strict mode enforces them), so the model can't
    hand back a short week and call it done.
    """
    schema = copy.deepcopy(_PLAN)
    day_array = schema["properties"]["days"]
    if days is not None:
        day_array["minItems"] = day_array["maxItems"] = days
    if suggestions_per_day is not None:
        suggestions = day_array["items"]["properties"]["suggestions"]
        suggestions["minItems"] = suggestions["maxItems"] = suggestions_per_day
    return schema


# --- Prompt composition -----------------------------------------------------


def _bias_sentence(bias: float) -> str:
    """Turn the 0..1 known-vs-unknown lean into an instruction the model reads."""
    if bias <= 0.34:
        return (
            "Lean strongly toward familiar dishes from our library; only invent "
            "a new one where the library can't cover a slot."
        )
    if bias >= 0.66:
        return (
            "Lean toward new dishes we haven't tried, using the library mainly "
            "for inspiration rather than repeating it."
        )
    return (
        "Balance familiar dishes from our library with a few new ones we "
        "haven't tried."
    )


def _dish_block(dishes: list[dict[str, Any]]) -> str:
    """The full Dish library verbatim — small households, filtering is premature."""
    if not dishes:
        return "Our library is empty; invent every suggestion from scratch."
    lines = []
    for dish in dishes:
        parts = [f"- [{dish['id']}] {dish['title']}"]
        if dish.get("favourite"):
            parts.append("(favourite)")
        line = " ".join(parts)
        if dish.get("ingredients"):
            line += f"\n    ingredients: {dish['ingredients']}"
        if dish.get("substitutes"):
            line += f"\n    substitutes: {dish['substitutes']}"
        if dish.get("recipe"):
            line += f"\n    recipe: {dish['recipe']}"
        lines.append(line)
    return "\n".join(lines)


# --- The editable prompt template --------------------------------------------
# The prompt is a household-wide template the Settings screen can edit. Values
# the backend derives from the library and the settings are injected wherever a
# ``{{variable}}`` appears; the default template reproduces the hand-composed
# prompt so an untouched install plans exactly as before.

# Every variable a template may use, with the one-line description the editor
# shows next to it. A template naming anything else is rejected on save.
PROMPT_VARIABLES: dict[str, str] = {
    "days": "Number of days to plan.",
    "suggestions_per_day": "Number of dinner suggestions per day.",
    "bias_instruction": "The known-vs-unknown lean, as an instruction.",
    "priority_order": "The priority order as a comma-separated list.",
    "priority_instruction": "The priority order, as an instruction (empty when unset).",
    "inspiration": "The Inspiration text, as typed.",
    "inspiration_instruction": "The Inspiration text, as an instruction (empty when unset).",
    "dish_library": "The full Dish library, one dish per line with its [id].",
    "offers": "This week's offers at your preferred shops, one per line with its [id].",
    "offers_instruction": "The offers, with how to use and cite them (empty when there are none).",
    "fridge_fresh": "The fresh items in the fridge, comma-separated.",
    "pantry_staples": "The pantry staples always in the house, comma-separated.",
    "fridge_instruction": "The fridge's fresh items and pantry staples, as an instruction (empty when both are empty).",
    "recipes": "Imported dinner recipes that use a fresh item or an offer, best match first, one per line with its [id].",
    "recipes_instruction": "Those recipes, with how to use them (empty when none match).",
}

DEFAULT_PROMPT_TEMPLATE = """You are planning a household's week of dinners.

Plan exactly {{days}} day(s), with {{suggestions_per_day}} dinner suggestion(s) per day.

Return the whole week in one response so no dish repeats across days.

For each suggestion set sourceDish to the [id] of the library dish it came from, or null when you invented a new dish.

Write every ingredient name in Danish, the way Danish shops label it (e.g. "kyllingebryst", "hakket oksekød", "løg"), so it can be matched to this week's offers and shopped for.

{{bias_instruction}}

{{priority_instruction}}

{{inspiration_instruction}}

{{fridge_instruction}}

{{offers_instruction}}

{{recipes_instruction}}

Our dish library:

{{dish_library}}"""

_VARIABLE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def template_variables(template: str) -> list[str]:
    """Every distinct ``{{variable}}`` name in a template, in first-use order."""
    return list(dict.fromkeys(_VARIABLE.findall(template)))


def unknown_variables(template: str) -> list[str]:
    """The variables a template names that the planner can't fill."""
    return [v for v in template_variables(template) if v not in PROMPT_VARIABLES]


def _offers_block(offers: dict[str, dict[str, Any]]) -> str:
    return "\n".join(offer_line(ref, offer) for ref, offer in offers.items())


# How the planner uses the imported recipes, per the Profile's recipeMode:
# "only" every dish is one, "mix" about half, "none" never (no list at all).
_RECIPE_SHARE = {
    "only": (
        "Every suggestion must be one of these recipes: set each suggestion's "
        "sourceRecipe to the recipe's [id]. Don't invent dishes or take them "
        "from the library."
    ),
    "mix": (
        "Base about half of the suggestions on these recipes (setting "
        "sourceRecipe to the recipe's [id]) and the rest on the library or new "
        "dishes, as the other instructions say."
    ),
}


def _recipes_instruction(mode: str) -> str:
    return (
        "These recipes from our recipe collection use fresh items we have at "
        "home or products on offer this week. "
        + _RECIPE_SHARE.get(mode, _RECIPE_SHARE["mix"])
        + " A dish based on a recipe is that recipe exactly — its title, "
        "ingredients and method are taken from it, so pick recipes whose "
        "ingredients suit the week as they are. \"check offer\" marks a "
        "product that may not be the ingredient it was matched to: judge from "
        "the product name, and only count it as on offer when it really is "
        "that ingredient."
    )


def prompt_values(
    dishes: list[dict[str, Any]],
    settings: dict[str, Any],
    offers: dict[str, dict[str, Any]] | None = None,
    fridge: dict[str, Any] | None = None,
    recipes: list[RecipeMatch] | None = None,
) -> dict[str, str]:
    """The value of every :data:`PROMPT_VARIABLES` entry for one run.

    ``daysToPlan`` and ``suggestionsPerDay`` go in as plain numbers; the
    priority order, the known-vs-unknown lean and the Inspiration text also
    come as natural-language instructions, because models follow prose more
    reliably than a raw settings blob (spec.md → "Prompt composition").

    ``offers`` maps each short offer ref (``o1``…) to its offer — the run's
    DiscountData, already food-filtered and ranked. ``fridge`` is what is in
    the house (see :mod:`food_planer.fridge`). ``recipes`` are the imported
    recipes that use some of either, already ranked and capped (see
    :mod:`food_planer.recipes.matching`).
    """
    offers = offers or {}
    recipe_mode = settings.get("recipeMode") or "mix"
    offer_ids = {offer["id"]: ref for ref, offer in offers.items()}
    recipe_list = "\n".join(
        recipe_prompt_line(ref, match, offer_ids)
        for ref, match in recipe_refs(recipes or []).items()
    )
    offer_list = _offers_block(offers)
    priority = settings.get("priority") or []
    inspiration = (settings.get("inspiration") or "").strip()
    return {
        "days": str(settings["daysToPlan"]),
        "suggestions_per_day": str(settings["suggestionsPerDay"]),
        # With only online recipes the library lean doesn't apply.
        "bias_instruction": (
            ""
            if recipe_mode == "only" and recipe_list
            else _bias_sentence(settings.get("knownVsUnknownBias", 0.5))
        ),
        "priority_order": ", ".join(priority),
        "priority_instruction": (
            "When choosing dishes, prioritise them in this order: "
            + ", ".join(priority)
            + " — the earliest matters most."
            if priority
            else ""
        ),
        "inspiration": inspiration,
        "inspiration_instruction": (
            f"The household is curious to try: {inspiration}" if inspiration else ""
        ),
        "dish_library": _dish_block(dishes),
        "offers": offer_list,
        "offers_instruction": (
            "These products are on offer this week at our shops. Prefer dishes "
            "that make good use of them. Whenever a suggestion uses one, add it "
            "to that suggestion's discounts: offerId is the offer's [id] (only "
            "ids from this list), and matchedIngredient is the name of the "
            "ingredient it covers, written exactly as in the suggestion's "
            "ingredients.\n\n" + offer_list
            if offers
            else ""
        ),
        **fridge_prompt_values(fridge or {"items": []}),
        "recipes": recipe_list,
        "recipes_instruction": (
            _recipes_instruction(recipe_mode) + "\n\n" + recipe_list
            if recipe_list
            else ""
        ),
    }


def _drop_empty_lines(template: str, values: dict[str, str]) -> str:
    """Remove lines that hold nothing but a variable whose value is empty.

    The blank line before such a line goes too, so an unset Inspiration leaves
    no hole in the prompt — the same effect as skipping an empty section.
    """
    out: list[str] = []
    for line in template.split("\n"):
        match = _VARIABLE.fullmatch(line.strip())
        if match and values.get(match.group(1)) == "":
            if out and not out[-1].strip():
                out.pop()
            continue
        out.append(line)
    return "\n".join(out).strip()


def render_prompt_segments(
    template: str, values: dict[str, str]
) -> list[dict[str, str | None]]:
    """The rendered prompt as ``{text, variable}`` pieces, in order.

    ``variable`` names the placeholder a piece was injected from, or is null for
    the template's own text — which is how the editor's preview highlights the
    injected values. A name with no value is left in place, braces and all.
    """
    cleaned = _drop_empty_lines(template, values)
    segments: list[dict[str, str | None]] = []
    pos = 0
    for match in _VARIABLE.finditer(cleaned):
        if match.start() > pos:
            segments.append({"text": cleaned[pos : match.start()], "variable": None})
        name = match.group(1)
        if name in values:
            segments.append({"text": values[name], "variable": name})
        else:
            segments.append({"text": match.group(0), "variable": None})
        pos = match.end()
    if pos < len(cleaned):
        segments.append({"text": cleaned[pos:], "variable": None})
    return segments


def compose_planning_prompt(
    dishes: list[dict[str, Any]],
    settings: dict[str, Any],
    template: str | None = None,
    offers: dict[str, dict[str, Any]] | None = None,
    fridge: dict[str, Any] | None = None,
    recipes: list[RecipeMatch] | None = None,
) -> str:
    """Compose the single planning call from the library, the settings, the
    run's offers, what is in the fridge and the recipes that use them.

    ``template`` is the household's edited prompt; ``None`` uses the default.
    """
    values = prompt_values(dishes, settings, offers, fridge, recipes)
    segments = render_prompt_segments(template or DEFAULT_PROMPT_TEMPLATE, values)
    return "".join(seg["text"] for seg in segments)
