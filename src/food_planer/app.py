"""FastAPI application factory and the ``/api`` seam.

``create_app`` wires the JSON :class:`~food_planer.store.Store` and the two
external clients onto the app, mounts the REST API under ``/api`` and, when a
built frontend is present, serves the React shell same-origin. Same origin is
why there is no CORS middleware (see ``spec.md`` → issue #12 provisional
default).

Errors use FastAPI's stock ``{"detail": "..."}`` body with real status codes:
no API versioning, no custom error envelope.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .clients import (
    LLMResult,
    OpenAIClient,
    RealOpenAIClient,
    RealTjekClient,
    TjekClient,
)
from .discounts import (
    MAX_PROMPT_OFFERS,
    OFFER_LIMIT_CEILING,
    OfferCatalog,
    REVIEW_SCHEMA,
    approved_keys,
    attach_offers,
    attach_reviewed,
    bare_ref,
    is_food,
    offer_refs,
    resolve_dealer,
    review_prompt,
    select_offers,
    with_shop_slugs,
)
from .fridge import (
    SCAN_PROMPT,
    SCAN_SCHEMA,
    OnHand,
    add_items,
    clean_name,
    fridge_body,
    scanned_items,
)
from .planning import (
    DEFAULT_PROMPT_TEMPLATE,
    PROMPT_VARIABLES,
    compose_planning_prompt,
    planning_json_schema,
    prompt_values,
    render_prompt_segments,
    unknown_variables,
)
from .recipes import load_all_recipes
from .recipes.matching import (
    MAX_PROMPT_RECIPES,
    RecipeMatch,
    first_paragraph,
    match_dinner_recipes,
    match_recipes,
    minutes,
    parse_ingredient_line,
    recipe_card,
    recipe_link,
    recipe_refs,
    rough_cost,
)
from .shopping_list import (
    merge_shopping_list,
    shopping_list_csv,
    shopping_list_reminders,
    shopping_list_text,
)
from .shops import DANISH_CHAINS, icon_path, save_icon, shop_catalog, slugify
from .store import Store, new_id

log = logging.getLogger("food_planer.planning")

# A generous ceiling for the single planning call; hitting it triggers the
# one truncation retry with days and suggestions-per-day halved.
PLANNING_MAX_OUTPUT_TOKENS = 8000

# A scan sends every photo to the model as image input; a handful of photos
# covers a fridge and its cupboards, and caps what one press can cost.
MAX_SCAN_IMAGES = 8
MAX_SCAN_IMAGE_BYTES = 10 * 1024 * 1024

# Where data/ lives is resolved relative to the running process (the #12
# provisional default): the repo root when launched from there.
DEFAULT_DATA_DIR = Path(os.environ.get("FOOD_PLANNER_DATA_DIR", "data"))
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


# --- Dependency providers ---------------------------------------------------
# These read whatever was wired onto app.state in create_app. Tests override
# get_openai_client / get_tjek_client via app.dependency_overrides.


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_openai_client(request: Request) -> OpenAIClient:
    return request.app.state.openai_client


def get_tjek_client(request: Request) -> TjekClient:
    return request.app.state.tjek_client


def get_offer_catalog(request: Request) -> OfferCatalog:
    return request.app.state.offer_catalog


# --- API request/response models -------------------------------------------


class DishIn(BaseModel):
    """The writable shape of a Dish.

    Only ``title`` is required. ``ingredients``, ``substitutes`` and ``recipe``
    are optional freeform text (each a textarea in the UI). Because ``PUT`` is a
    full replace, an omitted optional field defaults to ``None`` and thereby
    clears whatever was stored before.
    """

    title: str = Field(min_length=1)
    ingredients: str | None = None
    substitutes: str | None = None
    recipe: str | None = None
    favourite: bool = False


class Dish(DishIn):
    id: str


class PlanningSettings(BaseModel):
    """The household's planning preferences — one set for everyone, stored in
    ``data/settings.json``. Every field has a default, so a fresh install is
    plannable straight away."""

    daysToPlan: int = 7
    suggestionsPerDay: int = 2
    knownVsUnknownBias: float = 0.5
    priority: list[str] = Field(
        default_factory=lambda: ["cheap", "quick", "delicious", "healthy"]
    )
    shops: list[str] = Field(default_factory=list)
    inspiration: str = ""
    # How the planner uses imported online recipes: "only" every suggestion
    # is one, "mix" about half, "none" never.
    recipeMode: Literal["only", "mix", "none"] = "mix"


class ShoppingSource(BaseModel):
    suggestionTitle: str
    kind: str


class ShoppingOffer(BaseModel):
    """The tilbudsavis offer an ingredient was on when it was added."""

    shop: str  # as Tjek names the dealer, e.g. "365discount"
    shopSlug: str | None = None  # its settings slug, e.g. "coop-365"
    productName: str
    price: float | None = None


class ShoppingItemIn(BaseModel):
    name: str = Field(min_length=1)
    quantity: str = ""
    source: ShoppingSource | None = None
    offer: ShoppingOffer | None = None
    # A free-text note for a hand-added item ("we're just out") — it rides to
    # the CSV export's Notes column for rows that have no dish behind them.
    note: str = ""


class RemoveItemsIn(BaseModel):
    lineIds: list[str]


class RemindersExportIn(BaseModel):
    # Only the rows behind these line ids; all rows when omitted.
    lineIds: list[str] | None = None


# --- PlanningRuns (issue #23) ----------------------------------------------


class SettingsOverride(BaseModel):
    """The just-for-this-run adjustment behind the settings chip.

    Applied on top of the household's saved PlanningSettings for a single run
    and never written back — the saved defaults survive untouched.
    """

    daysToPlan: int
    suggestionsPerDay: int
    knownVsUnknownBias: float


class PlanningRunIn(BaseModel):
    settingsOverride: SettingsOverride | None = None


class SuggestionIngredient(BaseModel):
    name: str
    quantity: str  # free text: "200 g", "1 pinch"
    # "fresh" (in the fridge) or "staple" (in the pantry) when we have it.
    have: str | None = None
    # A recipe dish's sub-list the line sits under ("Til servering"); null for
    # the main list and for dishes the model wrote.
    group: str | None = None


class SuggestionRecipe(BaseModel):
    """The imported recipe a Suggestion is based on (see recipes.matching.recipe_link)."""

    title: str
    url: str
    source: str | None = None
    thumbnail: str | None = None
    totalTime: str | None = None
    workTime: str | None = None
    servings: str | None = None


class Suggestion(BaseModel):
    title: str
    description: str
    ingredients: list[SuggestionIngredient]
    estimatedCost: float  # DKK
    prepTimeMinutes: int
    sourceDish: str | None  # a Dish id; null means an invented, unknown dish
    # The full offers this dish draws on, denormalized so an archived run
    # still shows them after they expire.
    discounts: list[dict] = Field(default_factory=list)
    recipe: SuggestionRecipe | None = None


class DayPlan(BaseModel):
    day: int
    suggestions: list[Suggestion]


class PlanningRun(BaseModel):
    id: str
    createdAt: str
    status: str  # "success" | "partial" | "failed"
    days: list[DayPlan]
    dayCount: int
    dishIds: list[str] = Field(default_factory=list)
    fridgeSnippet: str = ""
    # Carried only on a partial run, so the UI can't read a short week as full.
    requestedDays: int | None = None
    requestedSuggestionsPerDay: int | None = None
    # How many offers the model was shown, and the preferred chains whose
    # tilbudsavis couldn't be fetched (the run went ahead without them).
    offerCount: int = 0
    offersUnavailable: list[str] = Field(default_factory=list)
    # Why a failed run failed when the model call itself errored (a timeout,
    # an API outage) — shown on the failure banner.
    error: str | None = None


class PlanningRunSummary(BaseModel):
    """The archive row — no suggestions; that's the {id} read."""

    id: str
    createdAt: str
    dayCount: int
    status: str
    fridgeSnippet: str = ""


class PromptIn(BaseModel):
    """The edited planning prompt and its offer limit.

    A full replace, like the other PUTs: ``None`` (or an omitted field) resets
    that part to the built-in default. ``offerLimit`` is how many tilbudsavis
    offers the prompt lists; 0 lists none (ingredients are still matched to
    offers by name after the run).
    """

    template: str | None = None
    offerLimit: int | None = Field(default=None, ge=0, le=OFFER_LIMIT_CEILING)


class PromptPreviewIn(BaseModel):
    """Render a template and offer limit (the saved ones when omitted)."""

    template: str | None = None
    offerLimit: int | None = Field(default=None, ge=0, le=OFFER_LIMIT_CEILING)


class FridgeItemIn(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["fresh", "staple"]


class Shop(BaseModel):
    """One row of the backend-owned Danish-chain catalog (issue #20)."""

    slug: str
    name: str
    hasIcon: bool


def _write_trace(store: Store, run_id: str, trace: dict) -> Path | None:
    """Write a run's debug trace to data/run_logs/<id>.json.

    Best-effort: a failed write is logged, never allowed to fail the run.
    """
    path = store.data_dir / "run_logs" / f"{run_id}.json"
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), "utf-8")
        return path
    except OSError:
        log.exception("run %s: could not write the trace file %s", run_id, path)
        return None


class RecipeCardIngredient(BaseModel):
    text: str  # the line as the recipe writes it
    group: str | None = None  # its sub-heading, e.g. "Til servering"
    name: str  # the shopping item: "500 g porre, i ringe" → "porre"
    quantity: str  # … and "500 g"
    have: str | None = None  # "fresh" | "staple" when it's in the house


class RecipeCounts(BaseModel):
    fresh: int  # ingredients in the fridge
    staple: int  # … in the pantry
    offers: int  # … on offer this week


class RecipeCard(BaseModel):
    """One imported recipe, shaped like a Suggestion card for the Inspiration
    screen (see ``recipes.matching.recipe_card``). The stored record also
    carries the full blog intro and the method; the card links out for those."""

    source: str
    url: str
    title: str
    thumbnail: str | None = None
    servings: str | None = None
    total_time: str | None = None
    categories: list[str] = Field(default_factory=list)
    description: str = ""
    ingredients: list[RecipeCardIngredient]
    discounts: list[dict] = Field(default_factory=list)
    estimatedCost: float  # rough, DKK
    prepTimeMinutes: int | None = None
    counts: RecipeCounts
    recipe: SuggestionRecipe


class RecipeFreshUse(BaseModel):
    item: str  # the Fridge item, as stored
    ingredient: str  # the recipe ingredient that uses it


class RecipeOfferUse(BaseModel):
    ingredient: str
    shop: str
    productName: str
    price: float | None = None
    review: bool = False  # not a 1:1 match; the planner is asked to check it


class RecipeMatchOut(RecipeCard):
    """A recipe the planner would consider this week, and why."""

    score: float
    inPrompt: bool
    fresh: list[RecipeFreshUse]
    offers: list[RecipeOfferUse]


def _settings(store: Store) -> dict:
    """The household's planning settings, with defaults for anything unset."""
    return PlanningSettings(**store["settings"].read()).model_dump()


def _adopt_profile_settings(store: Store) -> None:
    """One-off migration from the per-profile era: a household with no saved
    settings yet takes the first profile's from ``profiles.json`` that has
    any. The old file is left on disk untouched; an unreadable one is skipped."""
    legacy = store.data_dir / "profiles.json"
    if store["settings"].read() or not legacy.exists():
        return
    try:
        profiles = json.loads(legacy.read_text("utf-8")) or []
    except (OSError, ValueError):
        log.warning("ignoring unreadable legacy %s", legacy)
        return
    settings = next(
        (p.get("settings") for p in profiles if isinstance(p, dict) and p.get("settings")),
        None,
    )
    if settings:
        store["settings"].seed(PlanningSettings(**settings).model_dump())


def create_app(
    *,
    data_dir: str | os.PathLike[str] = DEFAULT_DATA_DIR,
    openai_client: OpenAIClient | None = None,
    tjek_client: TjekClient | None = None,
) -> FastAPI:
    app = FastAPI(title="Food Planner")
    app.state.store = Store(data_dir)
    _adopt_profile_settings(app.state.store)
    app.state.openai_client = openai_client or RealOpenAIClient()
    app.state.tjek_client = tjek_client or RealTjekClient()
    app.state.offer_catalog = OfferCatalog()
    # Chains whose logo has been tried this run, so a chain Tjek has no logo
    # for isn't asked again on every page load.
    app.state.logo_attempts = set()

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- Settings: the household's planning preferences, one set ----------

    @api.get("/settings", response_model=PlanningSettings)
    def get_settings(store: Store = Depends(get_store)) -> dict:
        return _settings(store)

    @api.put("/settings", response_model=PlanningSettings)
    async def save_settings(
        body: PlanningSettings, store: Store = Depends(get_store)
    ) -> dict:
        """A full replace: an omitted field reverts to its default."""
        settings = body.model_dump()

        def replace(stored: dict) -> dict:
            stored.clear()
            stored.update(settings)
            return stored

        return await store["settings"].update(replace)

    @api.get("/dishes", response_model=list[Dish])
    def list_dishes(store: Store = Depends(get_store)) -> list[dict]:
        return store["dishes"].read()

    @api.post("/dishes", response_model=Dish, status_code=201)
    async def create_dish(
        body: DishIn, store: Store = Depends(get_store)
    ) -> dict:
        record = {"id": new_id(), **body.model_dump()}

        def add(dishes: list) -> dict:
            dishes.append(record)
            return record

        return await store["dishes"].update(add)

    @api.put("/dishes/{dish_id}", response_model=Dish)
    async def replace_dish(
        dish_id: str, body: DishIn, store: Store = Depends(get_store)
    ) -> dict:
        """Full replace: the stored Dish becomes exactly ``body`` (same id).

        Any field the caller omits reverts to its default, so sending
        ``recipe: null`` (or leaving it out) actually clears the recipe — there
        is no partial-update merge.
        """

        def replace(dishes: list) -> dict:
            for i, dish in enumerate(dishes):
                if dish["id"] == dish_id:
                    record = {"id": dish_id, **body.model_dump()}
                    dishes[i] = record
                    return record
            raise HTTPException(status_code=404, detail="Dish not found")

        return await store["dishes"].update(replace)

    @api.delete("/dishes/{dish_id}", status_code=204)
    async def delete_dish(
        dish_id: str, store: Store = Depends(get_store)
    ) -> None:
        def remove(dishes: list) -> None:
            for i, dish in enumerate(dishes):
                if dish["id"] == dish_id:
                    del dishes[i]
                    return
            raise HTTPException(status_code=404, detail="Dish not found")

        await store["dishes"].update(remove)

    # --- What is in the fridge: fresh items and pantry staples -------------
    # Household-shared. Fresh items come and go by hand (or by a photo scan);
    # pantry staples are assumed always in the house. Every name ever added is
    # remembered so the common-items list grows toward this household's habits.

    @api.get("/fridge")
    def get_fridge(store: Store = Depends(get_store)) -> dict:
        return fridge_body(store["fridge"].read())

    @api.post("/fridge/items", status_code=201)
    async def add_fridge_items(
        body: list[FridgeItemIn], store: Store = Depends(get_store)
    ) -> dict:
        # One call for a single picked chip or a whole confirmed scan.
        now = datetime.now(timezone.utc).isoformat()
        new = [
            {"id": new_id(), "name": clean_name(item.name), "kind": item.kind, "addedAt": now}
            for item in body
        ]
        return fridge_body(
            await store["fridge"].update(lambda fridge: add_items(fridge, new))
        )

    @api.delete("/fridge/items/{item_id}")
    async def remove_fridge_item(
        item_id: str, store: Store = Depends(get_store)
    ) -> dict:
        # Idempotent, like the shopping list: an item already gone is a no-op.
        def remove(fridge: dict) -> dict:
            fridge["items"] = [i for i in fridge["items"] if i["id"] != item_id]
            return fridge

        return fridge_body(await store["fridge"].update(remove))

    @api.delete("/fridge/items")
    async def clear_fridge_items(
        kind: Literal["fresh", "staple"], store: Store = Depends(get_store)
    ) -> dict:
        """Empty one kind — every fresh item, or every pantry staple. The names
        stay remembered, so they're still one tap away in the common items."""

        def clear(fridge: dict) -> dict:
            fridge["items"] = [i for i in fridge["items"] if i["kind"] != kind]
            return fridge

        return fridge_body(await store["fridge"].update(clear))

    @api.post("/fridge/scan")
    async def scan_fridge(
        images: list[UploadFile] = File(...),
        openai: OpenAIClient = Depends(get_openai_client),
    ) -> dict:
        """Name what the photos show. Nothing is saved: the household reviews
        the list and adds what's right through ``POST /fridge/items``, and the
        photos themselves are never kept."""
        if len(images) > MAX_SCAN_IMAGES:
            raise HTTPException(
                status_code=422,
                detail=f"At most {MAX_SCAN_IMAGES} photos per scan",
            )
        payload: list[tuple[str, bytes]] = []
        for image in images:
            mime = image.content_type or ""
            if not mime.startswith("image/"):
                raise HTTPException(
                    status_code=422, detail=f"{image.filename} is not an image"
                )
            data = await image.read()
            if len(data) > MAX_SCAN_IMAGE_BYTES:
                raise HTTPException(
                    status_code=422, detail=f"{image.filename} is too large"
                )
            payload.append((mime, data))
        try:
            result = await openai.scan_fridge(
                prompt=SCAN_PROMPT, images=payload, schema=SCAN_SCHEMA
            )
        except Exception as exc:
            log.exception("fridge scan failed")
            raise HTTPException(
                status_code=502, detail=f"The scan failed: {exc}"
            ) from exc
        if result.status != "completed":
            raise HTTPException(
                status_code=502,
                detail="The model couldn't read the photos — try clearer ones.",
            )
        return {"items": scanned_items(result.output)}

    # --- ShoppingList: one persistent, household-shared list ----------------
    # Merging (sum totals, join mismatched units, preserve each dish's share)
    # lives in the pure ``merge_shopping_list`` function; the API returns the
    # pre-merged rows so the frontend never re-derives them.

    @api.get("/shopping-list")
    def get_shopping_list(store: Store = Depends(get_store)) -> list[dict]:
        return merge_shopping_list(store["shopping_list"].read()["items"])

    @api.post("/shopping-list/items", status_code=201)
    async def add_shopping_items(
        body: list[ShoppingItemIn], store: Store = Depends(get_store)
    ) -> list[dict]:
        # One stored line per submitted item — bulk from a plan or a single
        # hand-typed item are the same call; they merge on read, not on write.
        new_lines = [
            {
                "id": new_id(),
                "name": item.name,
                "quantity": item.quantity,
                "source": item.source.model_dump() if item.source else None,
                "offer": item.offer.model_dump() if item.offer else None,
                "note": item.note,
            }
            for item in body
        ]

        def add(shopping_list: dict) -> list[dict]:
            shopping_list["items"].extend(new_lines)
            return shopping_list["items"]

        items = await store["shopping_list"].update(add)
        return merge_shopping_list(items)

    @api.post("/shopping-list/items/remove")
    async def remove_shopping_items(
        body: RemoveItemsIn, store: Store = Depends(get_store)
    ) -> list[dict]:
        # Removing a merged row deletes every underlying line. Idempotent: ids
        # already gone are a no-op, so a double-tap never errors.
        targets = set(body.lineIds)

        def remove(shopping_list: dict) -> list[dict]:
            shopping_list["items"] = [
                line for line in shopping_list["items"] if line["id"] not in targets
            ]
            return shopping_list["items"]

        items = await store["shopping_list"].update(remove)
        return merge_shopping_list(items)

    # --- Export (issue #30): text to copy, CSV to download ------------------
    # Both formats are generated in the pure ``shopping_list_*`` functions so
    # their fiddly bits (per-dish shares in brackets, CSV quoting, the UTF-8
    # BOM) are testable behind the seam. ``navigator.share`` is deliberately
    # absent — it needs HTTPS, which a plain-HTTP home install doesn't have.

    def _rows(store: Store) -> list[dict]:
        return merge_shopping_list(store["shopping_list"].read()["items"])

    @api.get("/shopping-list/export.txt")
    def export_shopping_list_text(store: Store = Depends(get_store)) -> PlainTextResponse:
        return PlainTextResponse(shopping_list_text(_rows(store)))

    @api.post("/shopping-list/export/reminders")
    def export_shopping_list_reminders(
        body: RemindersExportIn, store: Store = Depends(get_store)
    ) -> dict:
        """The list as reminders for the iOS Shortcut that adds them to
        Påmindelser: every row, or only the rows behind ``lineIds``."""
        rows = _rows(store)
        if body.lineIds is not None:
            wanted = set(body.lineIds)
            rows = [r for r in rows if wanted & set(r["lineIds"])]
        return {"items": shopping_list_reminders(rows)}

    @api.get("/shopping-list/export.csv")
    def export_shopping_list_csv(store: Store = Depends(get_store)) -> Response:
        return Response(
            content=shopping_list_csv(_rows(store)),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="shopping-list.csv"'
            },
        )

    def _offer_limit(store: Store) -> int:
        saved = store["prompt"].read().get("offerLimit")
        return MAX_PROMPT_OFFERS if saved is None else saved

    async def _run_offers(
        settings: dict,
        dishes: list,
        tjek: TjekClient,
        catalog: OfferCatalog,
        limit: int,
    ) -> tuple[dict[str, dict], list[dict], list[str]]:
        """The run's DiscountData as short ref → offer (what the model sees),
        every food offer at the preferred shops (what ingredient names are
        matched against), and the chains that couldn't be fetched. Free-text
        "Other…" shops have no tilbudsavis."""
        names = [n for n in DANISH_CHAINS if slugify(n) in settings.get("shops", [])]
        offers, failed = await catalog.offers_for_shops(names, tjek)
        food = [o for o in offers if is_food(o)]
        return offer_refs(select_offers(food, dishes, cap=limit)), food, failed

    def _recipe_limit(settings: dict) -> int:
        """How many matched recipes a run's prompt lists, per recipeMode: none
        for "none"; for "only", enough to fill every slot twice over."""
        mode = settings.get("recipeMode") or "mix"
        if mode == "none":
            return 0
        if mode == "only":
            slots = settings["daysToPlan"] * settings["suggestionsPerDay"]
            return max(MAX_PROMPT_RECIPES, min(2 * slots, 100))
        return MAX_PROMPT_RECIPES

    async def _household_offers(store: Store, tjek, catalog) -> list[dict]:
        """Every food offer at the household's preferred shops."""
        _, food_offers, _ = await _run_offers(
            _settings(store), store["dishes"].read(), tjek, catalog, _offer_limit(store)
        )
        return food_offers

    async def _review_offer_matches(
        openai: OpenAIClient, pending: list[dict], run_id: str, trace: dict
    ) -> int:
        """Ask the model about the name matches that weren't 1:1 and attach the
        ones it confirms. A failed call attaches none: a missing offer tag is
        better than a wrong one."""
        if not pending:
            return 0
        prompt, refs = review_prompt(pending)
        try:
            result = await openai.review_matches(prompt=prompt, schema=REVIEW_SCHEMA)
        except Exception as exc:
            log.exception("run %s: match review failed", run_id)
            result = LLMResult(status="error", error=f"{type(exc).__name__}: {exc}")
        approved = approved_keys(result.output, refs) if result.status == "completed" else set()
        attached = attach_reviewed(pending, approved)
        trace["matchReview"] = {
            "prompt": prompt,
            "status": result.status,
            "error": result.error,
            "verdicts": copy.deepcopy(result.output),
            "attached": attached,
        }
        log.info(
            "run %s: match review of %d pair(s): %d confirmed (%s)",
            run_id, len(refs), len(approved), result.status,
        )
        return attached

    def _mark_suggestions(days: list, fridge: dict) -> None:
        """Mark each Suggestion ingredient we already have: fresh or staple."""
        on_hand = OnHand.from_fridge(fridge)
        for day in days:
            for suggestion in day.get("suggestions", []):
                for ingredient in suggestion.get("ingredients", []):
                    ingredient["have"] = on_hand.kind(ingredient.get("name", ""))

    def _link_recipes(days: list, recipes: list[RecipeMatch]) -> int:
        """Make each Suggestion based on a listed recipe *that recipe*, 1:1:
        its title, first paragraph, ingredient lines (parsed into shopping
        items) and time replace the model's, the model's offer citations go
        (they named its own ingredients), and the link, thumbnail and servings
        are kept on ``recipe``. A made-up ref is dropped; a suggestion titled
        exactly like a listed recipe is linked even without the ref. Returns
        how many were linked."""
        refs = recipe_refs(recipes)
        by_title = {m.recipe["title"].casefold(): m for m in recipes}
        linked = 0
        for day in days:
            for suggestion in day.get("suggestions", []):
                ref = bare_ref(suggestion.pop("sourceRecipe", None))
                match = refs.get(ref) or by_title.get(suggestion.get("title", "").casefold())
                suggestion["recipe"] = recipe_link(match.recipe) if match else None
                if not match:
                    continue
                linked += 1
                recipe = match.recipe
                suggestion["title"] = recipe["title"]
                suggestion["description"] = (
                    first_paragraph(recipe.get("description")) or suggestion.get("description", "")
                )
                suggestion["ingredients"] = [
                    {**parse_ingredient_line(i["text"]), "group": i.get("group")}
                    for i in recipe.get("ingredients", [])
                ]
                suggestion["discounts"] = []
                suggestion["prepTimeMinutes"] = (
                    minutes(recipe.get("total_time")) or suggestion.get("prepTimeMinutes", 0)
                )
        return linked

    def _run_recipes(
        store: Store, fridge: dict, food_offers: list[dict], limit: int | None
    ) -> list[RecipeMatch]:
        """The imported dinner recipes that use a fresh item or one of the
        week's food offers, best first. Matched against every food offer at
        the preferred shops, not just the capped list the model sees."""
        return match_dinner_recipes(
            load_all_recipes(store.data_dir), fridge, food_offers, limit=limit
        )

    # --- The planning prompt: one household-wide, editable template ---------
    # Values derived from the library and the household's settings are injected
    # wherever a {{variable}} appears. A template naming a variable the planner
    # can't fill is refused on save, so a typo never reaches the model.

    def _prompt_body(store: Store) -> dict:
        saved = store["prompt"].read()["template"]
        return {
            "template": saved or DEFAULT_PROMPT_TEMPLATE,
            "isDefault": saved is None,
            "defaultTemplate": DEFAULT_PROMPT_TEMPLATE,
            "offerLimit": _offer_limit(store),
            "defaultOfferLimit": MAX_PROMPT_OFFERS,
            "offerLimitCeiling": OFFER_LIMIT_CEILING,
            "variables": [
                {"name": name, "description": description}
                for name, description in PROMPT_VARIABLES.items()
            ],
        }

    def _check_template(template: str) -> None:
        unknown = unknown_variables(template)
        if unknown:
            names = ", ".join("{{" + name + "}}" for name in unknown)
            raise HTTPException(
                status_code=422, detail=f"Unknown prompt variable(s): {names}"
            )

    @api.get("/prompt")
    def get_prompt(store: Store = Depends(get_store)) -> dict:
        return _prompt_body(store)

    @api.put("/prompt")
    async def save_prompt(
        body: PromptIn, store: Store = Depends(get_store)
    ) -> dict:
        template = body.template
        if template is not None:
            _check_template(template)
            if not template.strip():
                raise HTTPException(status_code=422, detail="The prompt is empty")
            # Saving the default text verbatim is the same as resetting it, so
            # later improvements to the default still reach this household.
            if template == DEFAULT_PROMPT_TEMPLATE:
                template = None

        def replace(prompt: dict) -> None:
            prompt["template"] = template
            prompt["offerLimit"] = body.offerLimit

        await store["prompt"].update(replace)
        return _prompt_body(store)

    @api.post("/prompt/preview")
    async def preview_prompt(
        body: PromptPreviewIn,
        store: Store = Depends(get_store),
        tjek: TjekClient = Depends(get_tjek_client),
        catalog: OfferCatalog = Depends(get_offer_catalog),
    ) -> dict:
        """The prompt a run would send right now, split into the template's own
        text and each injected value — so the editor can highlight what came
        from where. Nothing is saved and the model is not called."""
        settings = _settings(store)
        template = (
            body.template
            if body.template is not None
            else store["prompt"].read()["template"] or DEFAULT_PROMPT_TEMPLATE
        )
        _check_template(template)
        dishes = store["dishes"].read()
        limit = body.offerLimit if body.offerLimit is not None else _offer_limit(store)
        offers, food_offers, _ = await _run_offers(settings, dishes, tjek, catalog, limit)
        fridge = store["fridge"].read()
        recipes = _run_recipes(store, fridge, food_offers, _recipe_limit(settings))
        values = prompt_values(dishes, settings, offers, fridge, recipes)
        return {"segments": render_prompt_segments(template, values)}

    # --- PlanningRuns: one button, one pass, a whole week (issue #23) -------
    # The whole week comes from a single structured LLM call so the model can
    # avoid repeating a dish across days. The run is persisted regardless of
    # outcome and returned synchronously — a dropped connection loses the wait,
    # not the plan.

    @api.post("/planning-runs", response_model=PlanningRun)
    async def create_planning_run(
        body: PlanningRunIn,
        store: Store = Depends(get_store),
        openai: OpenAIClient = Depends(get_openai_client),
        tjek: TjekClient = Depends(get_tjek_client),
        catalog: OfferCatalog = Depends(get_offer_catalog),
    ) -> dict:
        # The override lives on top of the saved settings for this run only; it
        # is never persisted back.
        settings = _settings(store)
        if body.settingsOverride is not None:
            settings.update(body.settingsOverride.model_dump())

        dishes = store["dishes"].read()
        requested_days = settings["daysToPlan"]
        requested_per_day = settings["suggestionsPerDay"]
        run_id = new_id()
        # Everything that went into and came out of this run, written to
        # data/run_logs/<id>.json at the end — the first stop when a plan
        # looks wrong.
        trace: dict = {
            "runId": run_id,
            "settings": settings,
            "settingsOverride": (
                body.settingsOverride.model_dump() if body.settingsOverride else None
            ),
            "dishCount": len(dishes),
            "calls": [],
        }
        log.info(
            "run %s: planning with settings %s%s",
            run_id, json.dumps(settings, ensure_ascii=False),
            " (per-run override applied)" if body.settingsOverride else "",
        )

        offer_limit = _offer_limit(store)
        offers, food_offers, offers_unavailable = await _run_offers(
            settings, dishes, tjek, catalog, offer_limit
        )
        per_shop: dict[str, int] = {}
        for offer in offers.values():
            per_shop[offer["shop"]] = per_shop.get(offer["shop"], 0) + 1
        trace["offers"] = {
            "foodOffersAtPreferredShops": len(food_offers),
            "limit": offer_limit,
            "shownToModel": len(offers),
            "shownPerShop": per_shop,
            "unavailable": offers_unavailable,
        }
        log.info(
            "run %s: %d food offers at preferred shops %s; %d shown to the "
            "model (limit %d) %s; unavailable: %s",
            run_id, len(food_offers), settings.get("shops", []), len(offers),
            offer_limit, per_shop, offers_unavailable or "none",
        )

        async def call(prompt: str, days: int, per_day: int, label: str):
            log.info("run %s: %s prompt (%d chars):\n%s", run_id, label, len(prompt), prompt)
            started = time.monotonic()
            try:
                result = await openai.create_plan(
                    prompt=prompt,
                    max_output_tokens=PLANNING_MAX_OUTPUT_TOKENS,
                    schema=planning_json_schema(days, per_day),
                )
            except Exception as exc:
                # A timeout or API error is a failed run like any other:
                # persisted, traced and explained — never a bare 500 that
                # leaves no trace of what happened.
                log.exception(
                    "run %s: %s call to the model failed after %.1fs",
                    run_id, label, time.monotonic() - started,
                )
                result = LLMResult(
                    status="error", error=f"{type(exc).__name__}: {exc}"
                )
            elapsed = round(time.monotonic() - started, 1)
            log.info(
                "run %s: %s call finished in %.1fs with status %r; raw output:\n%s",
                run_id, label, elapsed, result.status,
                json.dumps(result.output, ensure_ascii=False, indent=2),
            )
            trace["calls"].append(
                {
                    "label": label,
                    "days": days,
                    "suggestionsPerDay": per_day,
                    "prompt": prompt,
                    "seconds": elapsed,
                    "status": result.status,
                    "error": result.error,
                    "rawOutput": copy.deepcopy(result.output),
                }
            )
            return result

        template = store["prompt"].read()["template"]
        trace["customTemplate"] = template is not None
        fridge = store["fridge"].read()
        recipes = _run_recipes(store, fridge, food_offers, _recipe_limit(settings))
        trace["recipes"] = {
            "mode": settings.get("recipeMode") or "mix",
            "shownToModel": [
                {"title": m.recipe["title"], "url": m.recipe["url"], "score": round(m.score, 2)}
                for m in recipes
            ],
        }
        log.info("run %s: %d matched recipes shown to the model", run_id, len(recipes))
        prompt = compose_planning_prompt(
            dishes, settings, template, offers, fridge, recipes
        )
        result = await call(prompt, requested_days, requested_per_day, "first")

        status = "success"
        output = None
        if result.status == "completed":
            output = result.output
            # The schema pins the counts, but a reply that still comes back
            # short is a partial week — never a success that hides the gap.
            returned = (output or {}).get("days", [])
            if len(returned) < requested_days or any(
                len(day.get("suggestions", [])) < requested_per_day
                for day in returned
            ):
                status = "partial"
        elif result.status in ("refused", "error"):
            # A safety refusal or a failed call fails immediately — no retry.
            # (The client already retried a failed call once.)
            status = "failed"
        elif result.status == "incomplete":
            # Truncation: exactly one retry with days and per-day halved.
            retry_settings = {
                **settings,
                "daysToPlan": max(1, requested_days // 2),
                "suggestionsPerDay": max(1, requested_per_day // 2),
            }
            log.warning(
                "run %s: output truncated; retrying once with %d days x %d",
                run_id, retry_settings["daysToPlan"],
                retry_settings["suggestionsPerDay"],
            )
            retry = await call(
                compose_planning_prompt(
                    dishes, retry_settings, template, offers, fridge, recipes
                ),
                retry_settings["daysToPlan"],
                retry_settings["suggestionsPerDay"],
                "retry",
            )
            if retry.status == "completed":
                status = "partial"
                output = retry.output
            else:
                status = "failed"

        days = (output or {}).get("days", [])
        # Recipe dishes first (their ingredients replace the model's), then what
        # we have (needs no offer), then offers, then the uncertain ones' review.
        linked = _link_recipes(days, recipes)
        _mark_suggestions(days, fridge)
        matched = attach_offers(days, offers, food_offers)
        reviewed = await _review_offer_matches(openai, matched.pop("review"), run_id, trace)
        # A recipe dish's price is ours, not the model's: the same rough sum as
        # its Inspiration card, over its own ingredients and offers.
        for day in days:
            for suggestion in day.get("suggestions", []):
                if suggestion.get("recipe"):
                    suggestion["estimatedCost"] = rough_cost(
                        suggestion["ingredients"], suggestion["discounts"]
                    )
        if matched["dropped"]:
            log.warning(
                "run %s: dropped offer ids the model made up: %s",
                run_id, matched["dropped"],
            )
        # The archive shows which fresh items the run was planned against.
        fridge_text = ", ".join(
            i["name"] for i in fridge["items"] if i["kind"] == "fresh"
        )
        record = {
            "id": run_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "days": days,
            "dayCount": len(days),
            "dishIds": [d["id"] for d in dishes],
            "fridgeSnippet": fridge_text[:120],
            # Only a partial run carries the ask alongside the actuals.
            "requestedDays": requested_days if status == "partial" else None,
            "requestedSuggestionsPerDay": (
                requested_per_day if status == "partial" else None
            ),
            "offerCount": len(offers),
            "offersUnavailable": offers_unavailable,
            # The last call's error, if any — the retry's when there was one.
            "error": trace["calls"][-1]["error"],
        }

        suggestion_count = sum(len(d.get("suggestions", [])) for d in days)
        trace["result"] = {
            "status": status,
            "dayCount": len(days),
            "suggestionCount": suggestion_count,
            "offersCitedByModel": matched["model"],
            "offersMatchedByName": matched["name"],
            "offersConfirmedByReview": reviewed,
            "recipesLinked": linked,
            "droppedOfferIds": matched["dropped"],
            "days": days,
        }
        trace_path = _write_trace(store, run_id, trace)
        log.info(
            "run %s: %s — %d day(s), %d suggestion(s); offers cited by the "
            "model: %d, matched by ingredient name: %d; full trace: %s",
            run_id, status, len(days), suggestion_count, matched["model"],
            matched["name"], trace_path,
        )

        def add(runs: list) -> dict:
            runs.append(record)
            return record

        return await store["planning_runs"].update(add)

    @api.get("/planning-runs", response_model=list[PlanningRunSummary])
    def list_planning_runs(store: Store = Depends(get_store)) -> list[dict]:
        # The household-wide archive as summaries — no suggestions shipped here.
        # Newest first (runs are stored in the order they were made) so the run
        # someone just made, or a partner's recent plan, leads the list. Nothing
        # is pruned: a household makes a handful of runs a week (issue #26).
        return list(reversed(store["planning_runs"].read()))

    @api.get("/planning-runs/{run_id}", response_model=PlanningRun)
    def get_planning_run(
        run_id: str, store: Store = Depends(get_store)
    ) -> dict:
        for run in store["planning_runs"].read():
            if run["id"] == run_id:
                with_shop_slugs(run.get("days", []))
                return run
        raise HTTPException(status_code=404, detail="Planning run not found")

    # --- Recipes: imported from recipe websites by `food-planer-recipes` ----
    # Read-only here; the scraper owns data/recipes/<site>.json.

    @api.get("/recipes", response_model=list[RecipeCard])
    async def list_recipes(
        store: Store = Depends(get_store),
        tjek: TjekClient = Depends(get_tjek_client),
        catalog: OfferCatalog = Depends(get_offer_catalog),
    ) -> list[dict]:
        """Every imported recipe as a card, with this week's offers at the
        household's shops."""
        food_offers = await _household_offers(store, tjek, catalog)
        recipes = load_all_recipes(store.data_dir)
        on_hand = OnHand.from_fridge(store["fridge"].read())
        matched = {m.recipe["url"]: m for m in match_recipes(recipes, on_hand, food_offers)}
        return [recipe_card(r, matched.get(r["url"]), on_hand) for r in recipes]

    @api.get("/recipes/matches", response_model=list[RecipeMatchOut])
    async def list_recipe_matches(
        store: Store = Depends(get_store),
        tjek: TjekClient = Depends(get_tjek_client),
        catalog: OfferCatalog = Depends(get_offer_catalog),
    ) -> list[dict]:
        """Every dinner recipe that uses a fresh item or one of this week's
        offers at the household's shops, best first — the same ranking the
        planner uses, with ``inPrompt`` marking the ones it actually sees
        (none when the household doesn't use online recipes)."""
        food_offers = await _household_offers(store, tjek, catalog)
        limit = _recipe_limit(_settings(store))
        fridge = store["fridge"].read()
        on_hand = OnHand.from_fridge(fridge)
        matches = _run_recipes(store, fridge, food_offers, None)
        return [
            {
                **recipe_card(m.recipe, m, on_hand),
                "score": round(m.score, 2),
                "inPrompt": rank < limit,
                "fresh": [{"item": item, "ingredient": ing} for item, ing in m.fresh.items()],
                "offers": [
                    {
                        "ingredient": o["ingredient"],
                        "shop": o["offer"]["shop"],
                        "productName": o["offer"]["item_name"],
                        "price": o["offer"].get("price"),
                        "review": o["review"],
                    }
                    for o in m.offers
                ],
            }
            for rank, m in enumerate(matches)
        ]

    # --- Shops: the fixed Danish-chain catalog and its logos (issue #20) -----
    # Backend-owned so the discount fetcher and the pill picker share one
    # canonical slug↔chain mapping. Logos live under data/icons/<slug>.<ext>.

    async def _fetch_missing_logos(
        store: Store, tjek: TjekClient, catalog: OfferCatalog, attempts: set[str]
    ) -> None:
        """Download the logo of every chain that has none yet, from its Tjek
        dealer, into data/icons/. Each chain is tried once per run; a chain
        Tjek doesn't carry (or a failed download) keeps its initials badge."""
        icons = store.data_dir / "icons"
        missing = [
            name
            for name in DANISH_CHAINS
            if slugify(name) not in attempts and icon_path(icons, slugify(name)) is None
        ]
        if not missing:
            return
        attempts.update(slugify(name) for name in missing)
        try:
            dealers = await catalog.dealers(tjek)
        except Exception:
            log.warning("shop logos: could not list Tjek dealers", exc_info=True)
            return

        async def fetch(name: str) -> None:
            dealer = resolve_dealer(name, dealers)
            url = dealer and dealer.get("logo")
            if not url:
                log.info("shop logos: Tjek has no logo for %s", name)
                return
            try:
                data, media_type = await tjek.fetch_image(url)
            except Exception:
                log.warning("shop logos: could not fetch %s's logo", name, exc_info=True)
                return
            if save_icon(icons, slugify(name), data, media_type) is None:
                log.warning("shop logos: %s's logo is not a usable image (%s)", name, media_type)

        await asyncio.gather(*(fetch(name) for name in missing))

    @api.get("/shops", response_model=list[Shop])
    async def list_shops(
        request: Request,
        store: Store = Depends(get_store),
        tjek: TjekClient = Depends(get_tjek_client),
        catalog: OfferCatalog = Depends(get_offer_catalog),
    ) -> list[dict]:
        # Logos come from the chains' Tjek dealers the first time they're
        # needed; anything already in data/icons/ (or dropped in by hand) wins.
        await _fetch_missing_logos(store, tjek, catalog, request.app.state.logo_attempts)
        return shop_catalog(store.data_dir / "icons")

    @api.get("/shops/{slug}/icon")
    def get_shop_icon(
        slug: str, store: Store = Depends(get_store)
    ) -> FileResponse:
        path = icon_path(store.data_dir / "icons", slug)
        if path is None:
            raise HTTPException(status_code=404, detail="Shop icon not found")
        return FileResponse(path)

    @api.get("/shops/{slug}/offers")
    async def get_shop_offers(
        slug: str,
        tjek: TjekClient = Depends(get_tjek_client),
        catalog: OfferCatalog = Depends(get_offer_catalog),
    ) -> dict:
        """One chain's current tilbudsavis, as normalised Offers.

        ``dealer`` is null for a chain Tjek doesn't carry (it then has no
        offers). Both listings are cached for a day, so browsing costs Tjek at
        most one call per chain per day. A Tjek failure is a 502.
        """
        name = next((n for n in DANISH_CHAINS if slugify(n) == slug), None)
        if name is None:
            raise HTTPException(status_code=404, detail="Shop not found")
        try:
            result = await catalog.offers_for(name, tjek)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not fetch the tilbudsavis for {name}: {exc}",
            ) from exc
        return {"shop": {"slug": slug, "name": name}, **result}

    app.include_router(api)

    # Serve the built React shell same-origin, when it has been built.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
