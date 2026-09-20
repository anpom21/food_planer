"""ShoppingList merging — the household's one persistent, shared list.

This is the fiddliest logic in the app, so it lives in Python as a pure
function with unit tests behind the HTTP seam, rather than a ``useMemo``
debuggable only in a browser (spec.md → "Merging lives in Python, not React").

A *line* is one stored contribution — ``{id, name, quantity, source}``, where
``quantity`` is free text ("800 g", "2 cups", "1 pinch", "2") and ``source`` is
``{suggestionTitle, kind}`` for a dish-sourced line or ``None`` for a
hand-typed one. :func:`merge_shopping_list` folds the lines into one row per
ingredient:

- the headline ``totalQuantity`` is the sum across every dish that wants it;
- each dish's ``share`` is preserved on its source entry;
- where two dishes ask in units that don't match, the amounts are *joined*
  rather than silently summed ("5 dl and 2 cups"), each keeping its own unit.

Quantities are deliberately never split into number + unit on the way in
(spec.md → non-goals); the split happens here, at merge time, and what can't be
summed is joined.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

# A leading (optionally signed/decimal) number, then whatever unit trails it.
_NUMBER_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*(.*)$", re.DOTALL)


def parse_quantity(quantity: str) -> tuple[float | None, str]:
    """Split free text into ``(number, unit)``.

    ``"800 g"`` → ``(800.0, "g")``; ``"2"`` → ``(2.0, "")``. When there is no
    leading number (``"a pinch"``), the number is ``None`` and the whole trimmed
    string is returned as the unit — such a line can't be summed, only joined.
    """
    match = _NUMBER_RE.match(quantity or "")
    if match is None:
        return None, (quantity or "").strip()
    return float(match.group(1)), match.group(2).strip()


def format_number(value: float) -> str:
    """Render a summed amount without a spurious ``.0`` — ``1200.0`` → ``"1200"``."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _join_total(parsed: list[tuple[float | None, str]]) -> str:
    """Sum amounts that share a unit; join across units with " and "."""
    # Ordered buckets keyed by unit; unparseable lines pass through as opaque
    # tokens so nothing is silently dropped or wrongly summed.
    order: list[str] = []
    sums: dict[str, float] = {}
    opaque: list[str] = []
    for number, unit in parsed:
        if number is None:
            opaque.append(unit)
            continue
        if unit not in sums:
            sums[unit] = 0.0
            order.append(unit)
        sums[unit] += number

    tokens = [f"{format_number(sums[u])} {u}".strip() for u in order]
    tokens += opaque
    return " and ".join(token for token in tokens if token)


def _build_row(name: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = [parse_quantity(line.get("quantity", "")) for line in lines]

    # A dish's share is a bare unitless number when the whole row agrees on one
    # unit (the unit is stated once, on the total). When units are mismatched —
    # or a quantity couldn't be parsed — each line keeps its own full quantity,
    # so "5 dl" and "2 cups" stay distinguishable in their chips.
    units = {unit for number, unit in parsed if number is not None}
    bare_shares = len(units) == 1 and all(number is not None for number, _ in parsed)

    sources: list[dict[str, Any]] = []
    line_ids: list[str] = []
    for line, (number, _unit) in zip(lines, parsed):
        line_ids.append(line["id"])
        if bare_shares and number is not None:
            share = format_number(number)
        else:
            share = (line.get("quantity") or "").strip()
        source = line.get("source")
        if source is None:
            sources.append({"dishTitle": None, "kind": None, "share": share})
        else:
            sources.append(
                {
                    "dishTitle": source.get("suggestionTitle"),
                    "kind": source.get("kind"),
                    "share": share,
                }
            )

    # A hand-added line can carry a free-text note ("we're just out"); it rides
    # to the export's Notes column for rows that have no dish behind them.
    notes = [
        (line.get("note") or "").strip()
        for line in lines
        if line.get("source") is None and (line.get("note") or "").strip()
    ]

    return {
        "name": name,
        "totalQuantity": _join_total(parsed),
        "sources": sources,
        "lineIds": line_ids,
        "note": "; ".join(notes),
    }


def merge_shopping_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold stored lines into one merged row per ingredient, order preserved.

    Ingredients are matched case- and whitespace-insensitively so ``"Onion"``
    and ``"onion "`` land on the same row; the first spelling seen is the one
    displayed.
    """
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for line in items:
        display = (line.get("name") or "").strip()
        key = display.casefold()
        if key not in groups:
            groups[key] = {"name": display, "lines": []}
            order.append(key)
        groups[key]["lines"].append(line)

    return [_build_row(groups[key]["name"], groups[key]["lines"]) for key in order]


# --- Export: the two ways the list leaves the app (issue #30) ---------------
# Both work on a plain-HTTP home network (no ``navigator.share``, which needs
# HTTPS): plain text to paste into a chat, and a shopping-list.csv download.
# The formatting lives here, behind the seam, so per-dish shares in brackets,
# CSV quoting and the UTF-8 BOM are unit-testable without a browser.

_TEXT_HEADER = "Shopping list — Food Planner"

# A UTF-8 byte-order mark, written as an escape rather than an invisible glyph
# in the source, so Excel opens the CSV as UTF-8 (æ/ø/å intact).
_UTF8_BOM = "\ufeff"


def _dish_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The row's dish-backed source entries; hand-added lines are excluded."""
    return [s for s in row["sources"] if s.get("dishTitle")]


def shopping_list_text(rows: list[dict[str, Any]]) -> str:
    """Render merged rows as the plain text pasted into a messaging app.

    Each outstanding row shows its summed total; a row wanted by more than one
    dish also spells out each dish's share in brackets, since the headline
    amount alone hides where the total came from.
    """
    lines = [_TEXT_HEADER, ""]
    for row in rows:
        dishes = _dish_sources(row)
        total = (row.get("totalQuantity") or "").strip()
        line = f"[ ] {row['name']}"
        if total:
            line += f" — {total}"
        if len(dishes) > 1:
            shares = ", ".join(f"{s['dishTitle']} {s['share']}" for s in dishes)
            line += f" ({shares})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _notes_for(row: dict[str, Any]) -> str:
    """The Notes cell: provenance for dish rows, the hand-written note otherwise.

    One note per dish, joined with ``;``. A shared ingredient's note carries
    that dish's share (Quantity holds only the total); a single-dish row needs
    no share, so the note is just the dish name.
    """
    dishes = _dish_sources(row)
    if dishes:
        if len(dishes) > 1:
            return "; ".join(f"{s['dishTitle']} {s['share']}" for s in dishes)
        return dishes[0]["dishTitle"]
    return (row.get("note") or "").strip()


def shopping_list_csv(rows: list[dict[str, Any]]) -> str:
    """Render merged rows as CSV — ``Ingredient, Quantity, Notes``.

    One row per outstanding ingredient, standard RFC-4180 quoting (the ``csv``
    module handles commas and quotes), prefixed with a UTF-8 BOM so Excel reads
    æ/ø/å back correctly.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Ingredient", "Quantity", "Notes"])
    for row in rows:
        writer.writerow(
            [row["name"], (row.get("totalQuantity") or "").strip(), _notes_for(row)]
        )
    return _UTF8_BOM + buffer.getvalue()
