"""What is in the fridge: the household's itemised stock, in two kinds.

- **Fresh items** keep for less than about a month (milk, chicken, salad). They
  come and go, so each one is added and removed by hand — picked from the
  common-items list, typed, or found by scanning photos of the fridge.
- **Pantry staples** keep for a month or longer (rice, flour, spices). For now
  they are simply assumed to always be in the house.

Everything here is pure; the endpoints in :mod:`food_planer.app` wrap it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

KINDS = ("fresh", "staple")

# The starting point of the common-items list. Names the household has added
# before are folded in on top (see :func:`common_items`), so the list grows
# toward what this household actually buys.
BASIC_ITEMS: dict[str, list[str]] = {
    "fresh": [
        "Milk",
        "Butter",
        "Eggs",
        "Yoghurt",
        "Cheese",
        "Cream",
        "Chicken",
        "Minced beef",
        "Minced pork",
        "Bacon",
        "Ham",
        "Fish",
        "Tomatoes",
        "Cucumber",
        "Lettuce",
        "Bell pepper",
        "Carrots",
        "Broccoli",
        "Spinach",
        "Mushrooms",
        "Leek",
        "Spring onions",
        "Fresh herbs",
        "Lemon",
        "Apples",
        "Bananas",
        "Bread",
    ],
    "staple": [
        "Salt",
        "Black pepper",
        "Olive oil",
        "Vegetable oil",
        "Flour",
        "Sugar",
        "Rice",
        "Pasta",
        "Oats",
        "Canned tomatoes",
        "Stock cubes",
        "Soy sauce",
        "Vinegar",
        "Mustard",
        "Ketchup",
        "Dried herbs",
        "Spices",
        "Onions",
        "Garlic",
        "Potatoes",
        "Honey",
        "Baking powder",
    ],
}


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def clean_name(name: str) -> str:
    """Trim and collapse whitespace; the first letter is upper-cased so a typed
    "milk" and a picked "Milk" read the same in the list."""
    name = " ".join(name.split())
    return name[:1].upper() + name[1:]


def add_items(
    fridge: dict[str, Any], new: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Add items to the fridge in place, remembering each name for next time.

    An item already in the fridge (same name, either kind) is left as it is,
    so a second scan that spots the same milk doesn't list it twice.
    """
    present = {_key(item["name"]) for item in fridge["items"]}
    remembered = {_key(entry["name"]): entry for entry in fridge["history"]}
    for item in new:
        key = _key(item["name"])
        if not key:
            continue
        if key not in present:
            fridge["items"].append(item)
            present.add(key)
        # The latest kind wins: re-adding "Potatoes" as a staple moves it.
        if key in remembered:
            remembered[key]["kind"] = item["kind"]
        else:
            entry = {"name": item["name"], "kind": item["kind"]}
            fridge["history"].append(entry)
            remembered[key] = entry
    return fridge


def common_items(fridge: dict[str, Any]) -> dict[str, list[str]]:
    """Per kind, every basic or previously added name not already in the
    fridge — the chips the household picks from."""
    present = {_key(item["name"]) for item in fridge["items"]}
    remembered = {_key(e["name"]): e for e in fridge["history"]}
    out: dict[str, list[str]] = {kind: [] for kind in KINDS}
    seen: set[str] = set()
    # Names added before come first: they are what this household buys.
    candidates = [(e["name"], e["kind"]) for e in fridge["history"]] + [
        (name, kind) for kind in KINDS for name in BASIC_ITEMS[kind]
    ]
    for name, kind in candidates:
        key = _key(name)
        if key in present or key in seen:
            continue
        seen.add(key)
        # A basic name the household filed under the other kind follows them.
        kind = remembered.get(key, {}).get("kind", kind)
        out[kind].append(name)
    return out


def fridge_body(fridge: dict[str, Any]) -> dict[str, Any]:
    """The API shape: the items in the house, grouped, plus the common list."""
    return {
        "fresh": [i for i in fridge["items"] if i["kind"] == "fresh"],
        "staples": [i for i in fridge["items"] if i["kind"] == "staple"],
        "common": common_items(fridge),
    }


# --- Is an ingredient something we have? -----------------------------------
# Recipes and Suggestions name ingredients in Danish, while the Fridge's
# built-in pick-list is English, so each item is expanded to the words a
# Danish recipe uses for it. A name with no entry is matched as typed.

# Danish words a recipe uses for each of the Fridge's built-in items, fresh
# and staple alike (see :data:`BASIC_ITEMS`).
ITEM_TERMS: dict[str, tuple[str, ...]] = {
    # fresh
    "milk": ("mælk", "sødmælk", "letmælk", "minimælk", "skummetmælk"),
    "butter": ("smør",),
    "eggs": ("æg", "æggeblomme", "æggehvide"),
    "yoghurt": ("yoghurt", "skyr"),
    "cheese": (
        "ost", "parmesan", "mozzarella", "feta", "cheddar", "burrata",
        "ricotta", "halloumi", "gruyère", "pecorino",
    ),
    "cream": ("fløde", "piskefløde", "madlavningsfløde", "cremefraiche", "creme fraiche"),
    "chicken": ("kylling",),
    "minced beef": ("hakket oksekød", "oksefars", "hakket kød"),
    "minced pork": ("hakket svinekød", "svinefars", "hakket grisekød"),
    "bacon": ("bacon",),
    "ham": ("skinke",),
    "fish": ("fisk", "laks", "torsk", "rødspætte", "kulmule", "sej", "tun", "rejer", "makrel"),
    "tomatoes": ("tomat", "cherrytomat", "cocktailtomat", "bøftomat"),
    "cucumber": ("agurk",),
    "lettuce": ("salat", "hjertesalat", "rucola", "romainesalat", "iceberg"),
    "bell pepper": ("peberfrugt",),
    "carrots": ("gulerod", "gulerødder"),
    "broccoli": ("broccoli",),
    "spinach": ("spinat",),
    "mushrooms": ("champignon", "svampe", "svamp", "østershatte", "shiitake"),
    "leek": ("porre", "porrer"),
    "spring onions": ("forårsløg",),
    "fresh herbs": ("persille", "basilikum", "koriander", "dild", "purløg", "mynte", "estragon"),
    "lemon": ("citron",),
    "apples": ("æble", "æbler"),
    "bananas": ("banan",),
    "bread": ("brød", "rugbrød", "flutes", "baguette", "sandwichbrød"),
    # staple
    "salt": ("salt", "flagesalt", "havsalt"),
    "black pepper": ("peber",),
    "olive oil": ("olivenolie",),
    "vegetable oil": ("olie", "rapsolie", "solsikkeolie", "neutral olie"),
    "flour": ("mel", "hvedemel"),
    "sugar": ("sukker", "farin", "flormelis", "rørsukker"),
    "rice": ("ris", "jasminris", "basmatiris", "risottoris"),
    "pasta": ("pasta", "spaghetti", "penne", "tagliatelle", "fusilli", "lasagneplader"),
    "oats": ("havregryn",),
    "canned tomatoes": ("hakkede tomater", "flåede tomater", "tomatpuré"),
    "stock cubes": ("bouillon", "bouillonterning", "grøntsagsbouillon", "hønsebouillon", "oksebouillon", "fond"),
    "soy sauce": ("soja", "sojasauce"),
    "vinegar": ("eddike", "balsamico"),
    "mustard": ("sennep",),
    "ketchup": ("ketchup",),
    "dried herbs": ("oregano", "timian", "rosmarin", "laurbærblad"),
    "spices": ("spidskommen", "paprika", "karry", "kanel", "chili", "chiliflager", "gurkemeje", "muskatnød", "koriander stødt"),
    "onions": ("løg", "rødløg", "skalotteløg"),
    "garlic": ("hvidløg",),
    "potatoes": ("kartofler", "kartoffel"),
    "honey": ("honning",),
    "baking powder": ("bagepulver",),
}



def item_terms(name: str) -> tuple[str, ...]:
    """The Danish words a recipe would use for a Fridge item."""
    key = name.strip().lower()
    return ITEM_TERMS.get(key, (key,))


def _term_pattern(term: str) -> re.Pattern[str]:
    """Every word of ``term`` must appear, starting or ending a word:
    "kylling" finds "kyllingebryst", "ost" finds "flødeost"."""
    return re.compile(
        "".join(
            rf"(?=.*(?:\b{re.escape(w)}|{re.escape(w)}(?:e|r|n|er|ne|erne|ene)?\b))"
            for w in term.split()
        )
    )


class OnHand:
    """Answers "do we have this?" for an ingredient name, by Fridge item."""

    def __init__(self, fresh: Iterable[str] = (), staples: Iterable[str] = ()) -> None:
        self._fresh = {n: [_term_pattern(t) for t in item_terms(n)] for n in fresh}
        self._staples = [_term_pattern(t) for n in staples for t in item_terms(n)]

    @classmethod
    def from_fridge(cls, fridge: dict[str, Any]) -> OnHand:
        items = fridge.get("items", [])
        return cls(
            [i["name"] for i in items if i["kind"] == "fresh"],
            [i["name"] for i in items if i["kind"] == "staple"],
        )

    def fresh_items(self, name: str) -> list[str]:
        """The fresh Fridge items an ingredient name is ("kyllingebryst" → ["Chicken"])."""
        name = name.lower()
        return [item for item, pats in self._fresh.items() if any(p.search(name) for p in pats)]

    def is_staple(self, name: str) -> bool:
        name = name.lower()
        return any(p.search(name) for p in self._staples)

    def kind(self, name: str) -> str | None:
        """``"fresh"`` or ``"staple"`` when we have it at home, else ``None``."""
        if self.fresh_items(name):
            return "fresh"
        return "staple" if self.is_staple(name) else None


# --- The photo scan --------------------------------------------------------
# One vision call per scan: the photos go in, a list of named, classified items
# comes out. Nothing is saved until the household confirms the list.

SCAN_PROMPT = """These photos show the inside of a household's fridge (and possibly its cupboards).

List every food item you can identify. Name each one generically and briefly in English, the way it would appear on a shopping list (e.g. "Milk", "Chicken", "Cheddar", "Bell pepper") — no brands, no quantities. List each item once even if several photos show it.

Set kind to "fresh" for anything that keeps for less than about a month once bought (dairy, meat, fish, most vegetables and fruit, bread, leftovers), and "staple" for anything that keeps for a month or longer (dry goods, condiments, spices, oils, tins, jars).

Leave out anything you can't make out with reasonable confidence."""

SCAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                },
                "required": ["name", "kind"],
            },
        }
    },
    "required": ["items"],
}


def scanned_items(output: dict[str, Any] | None) -> list[dict[str, str]]:
    """The model's list, cleaned and de-duplicated, in the order it gave."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in (output or {}).get("items", []):
        name = clean_name(str(item.get("name", "")))
        kind = item.get("kind")
        if not name or kind not in KINDS or _key(name) in seen:
            continue
        seen.add(_key(name))
        out.append({"name": name, "kind": kind})
    return out


# --- What the planner sees ------------------------------------------------


def fridge_prompt_values(fridge: dict[str, Any]) -> dict[str, str]:
    """The fridge's prompt variables: the two lists, and an instruction that
    is empty when the household hasn't told the app anything yet."""
    fresh = ", ".join(i["name"] for i in fridge["items"] if i["kind"] == "fresh")
    staples = ", ".join(i["name"] for i in fridge["items"] if i["kind"] == "staple")
    parts = []
    if fresh:
        parts.append(
            "We already have these fresh items at home — plan dishes that use "
            "them up before they spoil, and leave them out of what needs "
            f"buying where you can: {fresh}"
        )
    if staples:
        parts.append(
            "These pantry staples are always in the house; use them freely: "
            f"{staples}"
        )
    return {
        "fridge_fresh": fresh,
        "pantry_staples": staples,
        "fridge_instruction": "\n\n".join(parts),
    }
