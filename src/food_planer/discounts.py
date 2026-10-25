"""The tilbudsavis: one chain's current Offers, fetched from Tjek and cached.

Pipeline steps 1–4 of spec.md → "Discount sourcing": hold the dealer list,
resolve a chain name to a dealer by name, list that dealer's offers and
normalise each into the ``Offer`` shape. Both listings are cached for a day —
offers only change weekly, and the Tjek ToS caveat wants call volume tiny.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .clients import TjekClient

log = logging.getLogger(__name__)

# Dealer list and per-dealer offers are refreshed at most once a day.
CACHE_TTL_SECONDS = 24 * 60 * 60

# Offer validity is printed in Danish local time; Tjek sends it in UTC.
_LOCAL_TZ = ZoneInfo("Europe/Copenhagen")

# Catalog chains whose Tjek dealer goes by another name.
DEALER_ALIASES: dict[str, str] = {
    "Coop 365": "365discount",
}


def _fold(name: str) -> str:
    """Case- and punctuation-insensitive form of a name, for matching."""
    return re.sub(r"[^0-9a-zæøå]+", "", name.lower())


def resolve_dealer(
    shop_name: str, dealers: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The Tjek dealer for a chain name, or ``None`` when Tjek carries none.

    An exact (folded) name match wins; otherwise the shortest dealer name that
    contains the chain's name — so "Meny" finds "MENY" before "MENY Vin".
    """
    wanted = _fold(DEALER_ALIASES.get(shop_name, shop_name))
    if not wanted:
        return None
    for dealer in dealers:
        if _fold(dealer.get("name", "")) == wanted:
            return dealer
    partial = [d for d in dealers if wanted in _fold(d.get("name", ""))]
    return min(partial, key=lambda d: len(d["name"])) if partial else None


def _local_date(stamp: str | None) -> str | None:
    """A Tjek timestamp (``2026-10-16T22:00:00+0000``) as a Danish date."""
    if not stamp:
        return None
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    return moment.astimezone(_LOCAL_TZ).date().isoformat()


def _format_amount(value: float) -> str:
    return f"{value:g}"


def _unit_size(quantity: dict[str, Any] | None) -> str | None:
    """Tjek's ``quantity`` block as text: ``"8 pcs"``, ``"400-500 g"``."""
    if not quantity:
        return None
    size = quantity.get("size") or {}
    symbol = (quantity.get("unit") or {}).get("symbol")
    low, high = size.get("from"), size.get("to")
    if low is None or not symbol:
        return None
    amount = _format_amount(low)
    if high is not None and high != low:
        amount += f"-{_format_amount(high)}"
    return f"{amount} {symbol}"


def normalize_offer(
    raw: dict[str, Any], *, shop: str, fetched_at: str
) -> dict[str, Any]:
    """One raw Tjek offer in the spec's ``Offer`` shape.

    ``discount_percent`` is only computable when the offer advertises a
    markdown (``pre_price`` above ``price``); most are flat weekly prices.
    """
    pricing = raw.get("pricing") or {}
    price = pricing.get("price")
    pre_price = pricing.get("pre_price")
    discount = (
        round((pre_price - price) / pre_price * 100, 1)
        if price is not None and pre_price and pre_price > price
        else None
    )
    return {
        "id": raw["id"],
        "source": "tjek_api",
        "item_name": raw.get("heading") or "",
        "description": raw.get("description") or None,
        "shop": shop,
        "price": price,
        "pre_price": pre_price,
        "discount_percent": discount,
        "currency": pricing.get("currency") or "DKK",
        "unit_size": _unit_size(raw.get("quantity")),
        "valid_from": _local_date(raw.get("run_from")),
        "valid_to": _local_date(raw.get("run_till")),
        # Tjek's category_ids is empty on most offers — never relied on.
        "category": None,
        # The tilbudsavis it was printed in — e.g. "Bilka Food Uge 43".
        "catalog": raw.get("catalog_label"),
        "image_url": (raw.get("images") or {}).get("view"),
        "fetched_at": fetched_at,
    }


class OfferCatalog:
    """Day-long in-memory caches of the dealer list and each dealer's offers.

    Held on ``app.state`` for the life of the process; the Tjek client is passed
    per call so tests reach it through ``dependency_overrides`` like any other.
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.ttl = ttl_seconds
        self._dealers: tuple[float, list[dict[str, Any]]] | None = None
        self._offers: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
        # Several shops are fetched at once; on a cold cache each would list
        # the dealers (and a chain's offers) itself. The locks make the
        # first caller fetch while the others wait for its result.
        self._dealers_lock = asyncio.Lock()
        self._offer_locks: dict[str, asyncio.Lock] = {}

    def _fresh(self, stamp: float) -> bool:
        return time.monotonic() - stamp < self.ttl

    async def dealers(self, tjek: TjekClient) -> list[dict[str, Any]]:
        async with self._dealers_lock:
            if self._dealers is None or not self._fresh(self._dealers[0]):
                self._dealers = (time.monotonic(), await tjek.list_dealers())
                log.info("tilbudsavis: fetched %d dealers", len(self._dealers[1]))
            return self._dealers[1]

    async def offers_for(self, shop_name: str, tjek: TjekClient) -> dict[str, Any]:
        """``{dealer, offers, fetchedAt}`` for a chain; ``dealer`` is null when
        Tjek carries no such chain, and then there are no offers either."""
        dealer = resolve_dealer(shop_name, await self.dealers(tjek))
        if dealer is None:
            log.info("tilbudsavis: %s has no Tjek dealer; no offers", shop_name)
            return {"dealer": None, "offers": [], "fetchedAt": None}
        async with self._offer_locks.setdefault(dealer["id"], asyncio.Lock()):
            cached = await self._dealer_offers(shop_name, dealer, tjek)
        return {
            "dealer": {"id": dealer["id"], "name": dealer["name"]},
            "offers": cached[2],
            "fetchedAt": cached[1],
        }

    async def _dealer_offers(
        self, shop_name: str, dealer: dict[str, Any], tjek: TjekClient
    ) -> tuple[float, str, list[dict[str, Any]]]:
        cached = self._offers.get(dealer["id"])
        if cached is None or not self._fresh(cached[0]):
            started = time.monotonic()
            fetched_at = datetime.now(timezone.utc).isoformat()
            raw = await tjek.list_offers(dealer_id=dealer["id"])
            offers = [
                normalize_offer(r, shop=dealer["name"], fetched_at=fetched_at)
                for r in raw
            ]
            cached = (time.monotonic(), fetched_at, offers)
            self._offers[dealer["id"]] = cached
            log.info(
                "tilbudsavis: fetched %d offers for %s (dealer %s) in %.1fs",
                len(offers), shop_name, dealer["id"], time.monotonic() - started,
            )
        else:
            log.debug(
                "tilbudsavis: %d cached offers for %s (fetched %s)",
                len(cached[2]), shop_name, cached[1],
            )
        return cached

    async def offers_for_shops(
        self, shop_names: list[str], tjek: TjekClient
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Every offer across several chains, plus the chains that failed.

        A failing chain is reported, not raised: a plan without one shop's
        offers is still a plan (spec.md → #11's provisional default).
        """
        results = await asyncio.gather(
            *(self.offers_for(name, tjek) for name in shop_names),
            return_exceptions=True,
        )
        offers: list[dict[str, Any]] = []
        failed: list[str] = []
        for name, result in zip(shop_names, results):
            if isinstance(result, BaseException):
                log.warning(
                    "tilbudsavis: fetching %s failed: %r — planning without it",
                    name, result,
                )
                failed.append(name)
            else:
                offers.extend(result["offers"])
        return offers, failed


# --- DiscountData: the offers one PlanningRun steers by ----------------------
# Pipeline of spec.md → "LLM contract": strip non-food with a keyword denylist
# (Tjek's category_ids is too sparse to filter on), rank offers that match a
# Dish ingredient first and fill the rest by discount, cap the lot.

# How many offers reach the model unless the household sets its own limit
# (the prompt editor, stored in data/prompt.json); ~20 tokens apiece. The
# ceiling keeps one prompt from growing without bound.
MAX_PROMPT_OFFERS = 1000
OFFER_LIMIT_CEILING = 2000

# Non-food words, matched against the end of a word in the offer's heading so
# Danish compounds are caught ("kattefoder", "vinterjakke", "stegepande")
# along with common plural endings. Deliberately heading-only: descriptions
# are full of pack words ("glas", "bakke") that would knock out real food.
NON_FOOD_WORDS: tuple[str, ...] = (
    # clothing & accessories
    "jakke", "bukser", "jeans", "trøje", "skjorte", "kjole", "nederdel",
    "sokker", "strømper", "trusser", "boxershorts", "shorts", "pyjamas",
    "undertøj", "støvle", "sandaler", "sneakers", "løbesko", "træningssko",
    "handsker", "vanter", "halstørklæde", "taske", "kuffert", "t-shirt",
    # home, kitchenware & appliances
    "dyne", "pude", "sengetøj", "sengesæt", "håndklæde", "tæppe", "gardin",
    "lampe", "stearinlys", "fyrfadslys", "bloklys", "lyskæde", "gryde",
    "pande", "kniv", "støvsuger", "kaffemaskine", "airfryer", "blender",
    "mikroovn", "brødrister", "elkedel", "opbevaringsboks",
    # electronics
    "fjernsyn", "høretelefoner", "headset", "højttaler", "mobil", "telefon",
    "computer", "tablet", "printer", "kabel", "oplader", "batteri",
    # garden, diy & leisure
    "plante", "blomst", "buket", "maling", "værktøj", "boremaskine",
    "skruetrækker", "havemøbel", "cykel", "legetøj", "lego", "bamse",
    "dukke", "spil", "gavekort", "pynt", "dekoration",
    # personal care & household chemicals
    "shampoo", "balsam", "tandpasta", "tandbørste", "deodorant", "parfume",
    "barberskraber", "makeup", "make-up", "mascara", "neglelak", "hårfarve",
    "solcreme", "bodylotion", "showergel", "sæbe", "vaskemiddel",
    "skyllemiddel", "rengøringsmiddel", "toiletpapir", "køkkenrulle", "bleer",
    "vådservietter", "servietter",
    # pets & tobacco
    "foder", "kattegrus", "hundesnack", "cigaretter", "tobak", "snus",
)

# Too short to match as a compound's tail without false hits ("Frisko" ice
# cream is not a shoe), so these only count as whole words.
NON_FOOD_WHOLE_WORDS: tuple[str, ...] = (
    "sko", "hue", "tv", "tøj", "bog", "face", "serum", "lotion",
)

_PLURAL = r"(?:e|r|n|s|en|er|ne|et|erne|ene)?\b"
_NON_FOOD = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in NON_FOOD_WORDS) + r")" + _PLURAL
    + r"|\b(?:" + "|".join(re.escape(w) for w in NON_FOOD_WHOLE_WORDS) + r")"
    + _PLURAL
)

# A whole tilbudsavis that isn't groceries, recognised by its title.
_NON_FOOD_CATALOG = re.compile(
    r"nonfood|non-food|legetøj|elektronik|tekstil|halloween|prosonic|"
    r"\bbolig|\bhave\b|byggemarked"
)


def is_food(offer: dict[str, Any]) -> bool:
    """Heuristic food-relevance: the offer's heading, and the title of the
    tilbudsavis it was printed in, both clear of non-food words."""
    if _NON_FOOD_CATALOG.search((offer.get("catalog") or "").lower()):
        return False
    return not _NON_FOOD.search((offer.get("item_name") or "").lower())


_FILLER_WORDS = frozenset(
    "and the with for med og til fra uden eller evt stk pkt pakke dåse glas "
    "spsk tsk dl ltr kg gram fint hakket frisk friske stor store lille små "
    "ca efter smag".split()
)


def _words(text: str | None) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-zæøå]+", (text or "").lower())
        if len(w) >= 3 and w not in _FILLER_WORDS
    }


def _library_pattern(dishes: list[dict[str, Any]]) -> re.Pattern[str] | None:
    """What makes an offer heading "about" the Dish library.

    Ingredient words match a word's end, like the non-food words: "løg"
    finds "rødløg" and "Samsø løg" but not the brand "Løgismose". Title words
    may also start a word — a dish names the product it's built from
    ("Lasagne" → "Lasagneplader", "Chili" → "Chilisauce"), so a library of
    bare titles still steers. Filler and unit words ("med", "stk") are
    dropped; three letters is the floor so "løg" and "ris" still count.
    """
    ingredient_words: set[str] = set()
    title_words: set[str] = set()
    for dish in dishes:
        title_words |= _words(dish.get("title"))
        ingredient_words |= _words(dish.get("ingredients"))
        ingredient_words |= _words(dish.get("substitutes"))
    parts = []
    tail_words = ingredient_words | title_words
    if tail_words:
        parts.append(
            "(?:" + "|".join(re.escape(w) for w in sorted(tail_words)) + ")" + _PLURAL
        )
    if title_words:
        parts.append(r"\b(?:" + "|".join(re.escape(w) for w in sorted(title_words)) + ")")
    return re.compile("|".join(parts)) if parts else None


def select_offers(
    offers: list[dict[str, Any]],
    dishes: list[dict[str, Any]],
    cap: int = MAX_PROMPT_OFFERS,
) -> list[dict[str, Any]]:
    """Food offers ranked for the prompt, capped.

    Three tiers: offers whose heading names something from the Dish library,
    then real markdowns (biggest first), then flat weekly prices. Within a tier
    the preferred shops take turns, so the first shop fetched can't fill every
    slot on its own.
    """
    library = _library_pattern(dishes)

    def tier(offer: dict[str, Any]) -> int:
        heading = (offer.get("item_name") or "").lower()
        if library and library.search(heading):
            return 0
        return 1 if offer.get("discount_percent") else 2

    # tier → shop → that shop's offers, biggest discount first (stable).
    tiers: dict[int, dict[str, list[dict[str, Any]]]] = {0: {}, 1: {}, 2: {}}
    for offer in sorted(
        (o for o in offers if is_food(o)),
        key=lambda o: -(o.get("discount_percent") or 0),
    ):
        tiers[tier(offer)].setdefault(offer["shop"], []).append(offer)

    ranked: list[dict[str, Any]] = []
    for by_shop in tiers.values():
        queues = list(by_shop.values())
        while queues and len(ranked) < cap:
            for queue in queues:
                if queue:
                    ranked.append(queue.pop(0))
            queues = [q for q in queues if q]
    return ranked[:cap]


def _kr(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") + " kr"


def offer_line(ref: str, offer: dict[str, Any]) -> str:
    """One offer as a compact prompt line, led by its short ``[ref]``."""
    parts = [f"[{ref}] {offer['shop']}: {offer['item_name']}"]
    if offer.get("unit_size"):
        parts.append(offer["unit_size"])
    price = _kr(offer["price"]) if offer.get("price") is not None else "price n/a"
    if offer.get("pre_price"):
        price += f" (was {_kr(offer['pre_price'])})"
    parts.append(price)
    if offer.get("valid_to"):
        parts.append(f"until {offer['valid_to']}")
    return " — ".join(parts)


def offer_refs(offers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Short per-run references (``o1``, ``o2``…) → offer, in ranked order.

    Tjek ids are 21 characters; a short ref costs the model far fewer tokens
    to read and to echo back in a Suggestion's discounts.
    """
    return {f"o{i}": offer for i, offer in enumerate(offers, start=1)}


def denormalize_discount(
    offer: dict[str, Any], matched_ingredient: str | None, matched_by: str
) -> dict[str, Any]:
    """The full offer as stored on a Suggestion — every field the UI renders,
    so an archived run still shows its offers after they expire.

    ``matchedBy`` says who tied it to the dish: ``"model"`` (cited by [id])
    or ``"name"`` (the backend matched an ingredient's name to the heading).
    """
    return {
        "offerId": offer["id"],
        "productName": offer["item_name"],
        "description": offer.get("description"),
        "shop": offer["shop"],
        "price": offer.get("price"),
        "originalPrice": offer.get("pre_price"),
        "discountPercent": offer.get("discount_percent"),
        "unitSize": offer.get("unit_size"),
        "validFrom": offer.get("valid_from"),
        "validUntil": offer.get("valid_to"),
        "imageUrl": offer.get("image_url"),
        "matchedIngredient": matched_ingredient,
        "matchedBy": matched_by,
    }


# Seasoning every kitchen already has. An ingredient made only of these is
# never matched by name: nobody shops for salt from a tilbudsavis, and the
# words mostly appear as modifiers ("Tørsaltet peber bacon").
_PANTRY_STAPLES = frozenset(
    "salt havsalt flagesalt peber sort hvid kværnet groft vand".split()
)

# Endings an ingredient word may carry in a heading: plurals and definite
# forms. Narrower than _PLURAL on purpose — "-et" there is mostly the past
# participle ("tørsaltet" is salted, not salt), and "-s" a genitive.
_INGREDIENT_ENDING = r"(?:e|r|n|en|er|ne|erne|ene)?\b"


def _name_words(name: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-zæøå]+", name.lower())
        if len(w) >= 2 and w not in _FILLER_WORDS
    ]


def offer_for_ingredient(
    name: str, offers: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The offer whose heading names an ingredient, or ``None``.

    Every meaningful word of the ingredient must appear in the heading, as a
    whole word or a compound's tail ("æg" → "frilandsæg"). Whole-word hits
    beat compound ones; ties go to the earlier (better-ranked) offer. Plain
    seasoning (salt, pepper, water) is never matched.

    A word only counts where it names the product itself, so two spots are
    ignored: a hyphenated modifier ("Fløde-kartofler" isn't cream) and
    anything after "med" ("Pizza med hvidløg" isn't garlic).
    """
    words = _name_words(name)
    if not words or all(w in _PANTRY_STAPLES for w in words):
        return None
    best: tuple[int, int] | None = None
    best_offer = None
    for index, offer in enumerate(offers):
        heading = (offer.get("item_name") or "").lower()
        # Only the product part of the heading — the bit before any "med".
        heading = re.split(r"\bmed\b", heading, maxsplit=1)[0]
        whole = 0
        for word in words:
            stem = re.escape(word) + _INGREDIENT_ENDING + r"(?!-\w)"
            if re.search(rf"\b{stem}", heading):
                whole += 1
            elif not re.search(stem, heading):
                break
        else:
            score = (-whole, index)
            if best is None or score < best:
                best, best_offer = score, offer
    return best_offer


def attach_offers(
    days: list[dict[str, Any]],
    cited: dict[str, dict[str, Any]],
    food_offers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Swap each Suggestion's offer references for full offers, in place, and
    tie any remaining ingredient to an offer by name.

    ``cited`` is the run's short ref → offer table the model cited from; a ref
    that isn't in it is dropped rather than trusted, and an offer is kept once
    per Suggestion. ``food_offers`` is every food offer at the preferred shops
    — the name matching looks wider than the capped list the model saw.
    Returns counts (and the dropped refs) for the run's log.
    """
    stats: dict[str, Any] = {"model": 0, "name": 0, "dropped": []}
    for day in days:
        for suggestion in day.get("suggestions", []):
            attached: dict[str, dict[str, Any]] = {}
            covered: set[str] = set()
            for ref in suggestion.get("discounts") or []:
                offer = cited.get(ref.get("offerId", ""))
                if offer is None:
                    stats["dropped"].append(ref.get("offerId"))
                    continue
                if offer["id"] not in attached:
                    ingredient = ref.get("matchedIngredient")
                    attached[offer["id"]] = denormalize_discount(
                        offer, ingredient, "model"
                    )
                    covered.add((ingredient or "").lower().strip())
                    stats["model"] += 1
            for ingredient in suggestion.get("ingredients", []):
                name = ingredient.get("name", "")
                if name.lower().strip() in covered:
                    continue
                offer = offer_for_ingredient(name, food_offers)
                if offer is not None and offer["id"] not in attached:
                    attached[offer["id"]] = denormalize_discount(offer, name, "name")
                    stats["name"] += 1
            suggestion["discounts"] = list(attached.values())
    return stats
