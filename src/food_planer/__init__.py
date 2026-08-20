"""Food Planner backend package."""

from __future__ import annotations

import os

from .app import create_app

__all__ = ["create_app", "main"]


def main() -> None:
    """Run the FastAPI app with a single Uvicorn worker.

    A single worker is a hard requirement: the persistence layer keeps its
    state in one in-memory cache per file, so a second worker would see stale
    data. See ``spec.md`` → "Concurrency".
    """
    import uvicorn

    host = os.environ.get("FOOD_PLANNER_HOST", "0.0.0.0")
    port = int(os.environ.get("FOOD_PLANNER_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, workers=1)
