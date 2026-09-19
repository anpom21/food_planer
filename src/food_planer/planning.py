"""The planning pass: prompt composition, the strict output schema, and model
config (issue #23, spec.md → "LLM contract").

Everything here is internal — it is reached through ``POST /api/planning-runs``
and tested through that seam. The two exceptions the spec pins directly are the
strict JSON schema and the config-driven model name, so those are plain pure
functions callable on their own.
"""

from __future__ import annotations

import os
from typing import Any

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

_DISCOUNT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "productName": {"type": "string"},
        "shop": {"type": "string"},
        "price": {"type": "number"},
        "originalPrice": {"type": "number"},
        "discountPercent": {"type": "number"},
        "validUntil": {"type": "string"},
        "matchedIngredient": {"type": ["string", "null"]},
    },
    "required": [
        "productName",
        "shop",
        "price",
        "originalPrice",
        "discountPercent",
        "validUntil",
        "matchedIngredient",
    ],
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
        # Denormalized offers; populated by the discount ticket, empty for now.
        "discounts": {"type": "array", "items": _DISCOUNT},
    },
    "required": [
        "title",
        "description",
        "ingredients",
        "estimatedCost",
        "prepTimeMinutes",
        "sourceDish",
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


def planning_json_schema() -> dict[str, Any]:
    """The root schema — an object with a nested ``days`` array, strict-clean."""
    import copy

    return copy.deepcopy(_PLAN)


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


def compose_planning_prompt(
    dishes: list[dict[str, Any]], settings: dict[str, Any]
) -> str:
    """Compose the single planning call from the library and the settings.

    ``daysToPlan`` and ``suggestionsPerDay`` go in as plain numbers; the
    priority order, the known-vs-unknown lean and the Inspiration text are
    rendered as natural-language instructions, because models follow prose more
    reliably than a raw settings blob (spec.md → "Prompt composition").
    """
    days = settings["daysToPlan"]
    per_day = settings["suggestionsPerDay"]
    priority = settings.get("priority") or []
    inspiration = (settings.get("inspiration") or "").strip()

    priority_line = (
        "When choosing dishes, prioritise them in this order: "
        + ", ".join(priority)
        + " — the earliest matters most."
        if priority
        else ""
    )
    inspiration_line = (
        f"The household is curious to try: {inspiration}" if inspiration else ""
    )

    sections = [
        "You are planning a household's week of dinners.",
        f"Plan exactly {days} day(s), with {per_day} dinner suggestion(s) per day.",
        "Return the whole week in one response so no dish repeats across days.",
        "For each suggestion set sourceDish to the [id] of the library dish it "
        "came from, or null when you invented a new dish.",
        _bias_sentence(settings.get("knownVsUnknownBias", 0.5)),
        priority_line,
        inspiration_line,
        "Our dish library:",
        _dish_block(dishes),
    ]
    return "\n\n".join(section for section in sections if section)
