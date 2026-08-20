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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .clients import (
    OpenAIClient,
    RealOpenAIClient,
    RealTjekClient,
    TjekClient,
)
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
    title: str = Field(min_length=1)
    ingredients: list[str] = Field(default_factory=list)
    recipe: str | None = None
    favourite: bool = False


class Dish(DishIn):
    id: str


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

    app.include_router(api)

    # Serve the built React shell same-origin, when it has been built.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
