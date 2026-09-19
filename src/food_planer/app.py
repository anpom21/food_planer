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

import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .clients import (
    OpenAIClient,
    RealOpenAIClient,
    RealTjekClient,
    TjekClient,
)
from .shopping_list import merge_shopping_list
from .shops import icon_path, shop_catalog
from .store import Store, new_id

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
    """Per-Profile planning preferences (ADR 0001), stored inline on the Profile.

    The Settings screen (a later ticket) owns editing these; here they only need
    a sensible default so a freshly-identified Profile is immediately plannable
    and ``GET /api/profiles/{id}`` has something to embed.
    """

    daysToPlan: int = 7
    suggestionsPerDay: int = 2
    knownVsUnknownBias: float = 0.5
    priority: list[str] = Field(
        default_factory=lambda: ["cheap", "quick", "delicious", "healthy"]
    )
    shops: list[str] = Field(default_factory=list)
    inspiration: str = ""


class IdentifyIn(BaseModel):
    email: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ProfileSummary(BaseModel):
    """The switcher list row — no embedded settings; that's the {id} read."""

    id: str
    email: str
    name: str


class Profile(ProfileSummary):
    settings: PlanningSettings


class ShoppingSource(BaseModel):
    suggestionTitle: str
    kind: str


class ShoppingItemIn(BaseModel):
    name: str = Field(min_length=1)
    quantity: str = ""
    source: ShoppingSource | None = None


class RemoveItemsIn(BaseModel):
    lineIds: list[str]


class Shop(BaseModel):
    """One row of the backend-owned Danish-chain catalog (issue #20)."""

    slug: str
    name: str
    hasIcon: bool


def _normalize_email(email: str) -> str:
    """Email is the lookup key, so fold case and trim before matching/storing.

    Keeps "Ada@Example.com " and "ada@example.com" from becoming two Profiles.
    """
    return email.strip().lower()


def create_app(
    *,
    data_dir: str | os.PathLike[str] = DEFAULT_DATA_DIR,
    openai_client: OpenAIClient | None = None,
    tjek_client: TjekClient | None = None,
) -> FastAPI:
    app = FastAPI(title="Food Planner")
    app.state.store = Store(data_dir)
    app.state.openai_client = openai_client or RealOpenAIClient()
    app.state.tjek_client = tjek_client or RealTjekClient()

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- Profiles: identify & switch (issue #17) ---------------------------
    # Email is a backend lookup key; the frontend keeps only a profileId
    # pointer in localStorage, so the backend is the single source of truth.

    @api.post("/profiles/identify", response_model=Profile)
    async def identify_profile(
        body: IdentifyIn, store: Store = Depends(get_store)
    ) -> dict:
        email = _normalize_email(body.email)
        name = body.name.strip()

        def find_or_create(profiles: list) -> dict:
            # The find-or-create decision lives inside the file lock so two
            # people typing the same new email can't create a duplicate.
            for profile in profiles:
                if profile["email"] == email:
                    return profile  # existing wins; the typed name is discarded
            record = {
                "id": new_id(),
                "email": email,
                "name": name,
                "settings": PlanningSettings().model_dump(),
            }
            profiles.append(record)
            return record

        return await store["profiles"].update(find_or_create)

    @api.get("/profiles", response_model=list[ProfileSummary])
    def list_profiles(store: Store = Depends(get_store)) -> list[dict]:
        return store["profiles"].read()

    @api.get("/profiles/{profile_id}", response_model=Profile)
    def get_profile(
        profile_id: str, store: Store = Depends(get_store)
    ) -> dict:
        for profile in store["profiles"].read():
            if profile["id"] == profile_id:
                return profile
        raise HTTPException(status_code=404, detail="Profile not found")

    @api.put("/profiles/{profile_id}/settings", response_model=Profile)
    async def update_settings(
        profile_id: str,
        body: PlanningSettings,
        store: Store = Depends(get_store),
    ) -> dict:
        """Save a Profile's PlanningSettings alone (issue #19, ADR 0001).

        The Settings screen never round-trips name and email just to save a
        slider: the body is the settings and nothing else. Full replace of the
        inline ``settings`` block, so any field the caller omits reverts to its
        default. Only the named Profile is touched, so one person's save can't
        overwrite their partner's preferences.
        """
        settings = body.model_dump()

        def replace_settings(profiles: list) -> dict:
            for profile in profiles:
                if profile["id"] == profile_id:
                    profile["settings"] = settings
                    return profile
            raise HTTPException(status_code=404, detail="Profile not found")

        return await store["profiles"].update(replace_settings)

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

    # --- Shops: the fixed Danish-chain catalog and its logos (issue #20) -----
    # Backend-owned so the discount fetcher and the pill picker share one
    # canonical slug↔chain mapping. Logos live under data/icons/<slug>.<ext>.

    @api.get("/shops", response_model=list[Shop])
    def list_shops(store: Store = Depends(get_store)) -> list[dict]:
        return shop_catalog(store.data_dir / "icons")

    @api.get("/shops/{slug}/icon")
    def get_shop_icon(
        slug: str, store: Store = Depends(get_store)
    ) -> FileResponse:
        path = icon_path(store.data_dir / "icons", slug)
        if path is None:
            raise HTTPException(status_code=404, detail="Shop icon not found")
        return FileResponse(path)

    app.include_router(api)

    # Serve the built React shell same-origin, when it has been built.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
